---
author: "gautam"
handle: "@gnarayan"
source: "https://x.com/gnarayan/status/2065433699064103017"
date: 2026-06-12T13:59:02.000Z
type: article
likes: 147
reposts: 12
replies: 15
bookmarks: 289
views: 39527
---
# Everything I Learned Market Making/Algotrading Prediction Markets

*By gautam (@gnarayan)*

![Banner](https://pbs.twimg.com/media/HKIEYYYWkAAFGs-?format=jpg&name=large)

I’m still relatively new to running my own trading strategies, but over the past few months I’ve been building and maintaining a profitable prediction market trading system.

A lot of trading system content talks about strategy at a high level, but the real difficulty is often in the messy implementation details: cancels that do not actually cancel, order books that desync, rate limits, partial fills, etc. My hope is that this writeup gives other builders a more realistic picture of what they are likely to run into when building live trading systems from scratch.

**I also plan to open-source much of the codebase in the future, so stay tuned for that.**

# How I Found This Opportunity

In order for prediction markets to exist, they need market makers: traders who provide liquidity on both sides of the order book and try to earn the bid-ask spread. On large, liquid exchanges like Kalshi, competitive markets often compress spreads to around 1¢, but on smaller prediction market exchanges with less competitive liquidity, spreads can widen considerably. 

![Image](https://pbs.twimg.com/media/HKF-e5QXMAA7xd9?format=png&name=large)

Earlier this year, I identified one such exchange by analyzing publicly available market data. Spreads were super wide, yet volume was surprisingly high: NBA and MLB markets were reaching $100K to $300K in volume while averaging ~7¢ spreads. On a 50¢ contract, a 7¢ spread represents 14% of the midpoint price, or roughly 7% gross theoretical spread capture. 

7% is *huge*.

To put that into perspective, on Kalshi the spreads on many sports markets are usually 1¢. A 1¢ spread around a 50¢ contract implies roughly $1K of theoretical profit on $100K of two-sided maker volume.

A maker doing the **SAME** $100K of two-sided volume on the illiquid smaller prediction market implies roughly** $7K of theoretical profit. **

Even after fees, the edge still looked unusually large. It was the kind of opportunity that felt too obvious to ignore, so I wanted to see if I could build a real system to capture it.

# My Implementation

The first version was very basic: I built a simple quoting engine on the smaller exchange that used Kalshi’s liquidity as a reference for when and where to place quotes.

The quoting engine takes some variables into account (maker fees, taker fees, maker rebates, top-of-book liquidity and pricing on the larger exchange) and based on those variables decides where to place limit orders and how much size each limit order should have.

Example:

- Let's say the spread on the smaller exchange is 7¢ (top bid: 46¢, top ask: 53¢) and the spread on Kalshi is 1¢ (top bid: 49¢, top ask: 50¢)
- Quoting engine: Tighten spread on smaller exchange by 1¢ on each side by placing a limit bid order at 47¢ and a limit ask order at 52¢
- Now the spread on the smaller exchange has reduced to 5¢ and we become the best bid and best ask, therefore incoming taker flow is more likely to trade against our quotes
- If someone hits our **bid** for X contracts @ 47¢ on the smaller exchange, then we sell X contracts on Kalshi for 49¢. Having bought for 47¢ and sold for 49¢, we lock in an immediate 2¢ profit on each contract **bought**
- If someone lifts our **ask** for X contracts @ 52¢ on the smaller exchange, then we buy X contracts on Kalshi for 50¢. Having bought for 50¢ and sold for 52¢, we lock in an immediate 2¢ profit on each contract **sold**

The idea is that this would run in a loop, constantly monitoring the larger exchange's liquidity and updating our current live limit orders on the smaller exchange. 

For the first few days, I did decent volume and even made a few bucks, but this is where I started to run into real problems. Sophisticated competitors began joining and my infrastructure needed serious scaling.

## Technical Details

At a high level, the** first iteration** of the system had three main parts:

1. Market Data and Normalization
2. Quote Engine
3. Live Order State and Risk

![Image](https://pbs.twimg.com/media/HKV7197WEAAKI-Z?format=jpg&name=large)

**→ Market Data and Normalization**

The system continuously streams order books from both exchanges over WebSocket streams. One exchange is where I place maker quotes (the smaller, illiquid exchange), and the other exchange is where I hedge after I get filled (e.g. Kalshi, Polymarket). 

A big design decision was separating exchange-specific market data from the quote engine. Each exchange has its own API shape, message format, order book representation, precision rules, and update semantics. I did not want the quote engine to know about any of that. The quote engine should only answer one question:

*Given the current normalized market state, what orders should be live?*

To make that possible, I built adapters that converted raw WebSocket messages into a shared internal order book format.

Normalizing these books was important because prediction market exchanges do not always expose equivalent contracts in the same way. By converting everything into the same internal format, the quote engine could reason about every venue the same way. 

![Image](https://pbs.twimg.com/media/HKWFK1CX0AAwAm_?format=png&name=large)

This also made it much easier to add new hedge venues later. Instead of rewriting the strategy each time, I only needed to write a new adapter that transformed that venue’s raw book into the normalized format.

**→ Quote Engine**

After the books across the different exchanges are normalized, the quoting engine reads the latest normalized snapshot and decides what limit orders should be live on the smaller exchange. For each candidate quote, it walks the hedge exchange's order book to see how much size is actually available and at what cost. 

The hard part was not finding a profitable quote (finding a profitable quote is relatively straightforward). The hard part was figuring out whether that quote would **still be** profitable by the time someone traded against it.

A resting limit order is basically a free option you give to the rest of the market. If my quote was stale by even a small amount, faster traders were able to hit it before I canceled. Because of this, the quote engine had to think about way more than just the current spread. It had to think about how fast the hedge book was moving, how fresh my data was, how long cancels took, and how much edge I needed as a buffer.

In practice, the quote decision became something closer to taking the expected edge + maker rebates and subtracting:

- maker fees
- hedge taker fees
- expected slippage
- latency buffer
- adverse selection buffer
- inventory/risk buffer

And only if a trade was profitable after all of that did the system place or keep a quote.

Another lesson was that average latency mattered less than tail latency. If my system was usually fast but occasionally slow, those slow moments were exactly when I was most likely to get picked off. The bad fills did not come from normal conditions. They came from the worst 1% of moments: volatile markets, delayed websocket updates, cancel throttling, or sudden liquidity gaps. Because of that, I started caring more about stale-data checks, quote TTLs, and worst-case behavior than average performance.

A simplified version of the full quoting logic looks like this:

1. Read latest books from both exchanges
2. Check available hedge liquidity
3. Calculate max profitable maker quote
4. Compare against current live orders
5. Place, cancel, or replace quotes
6. If filled, immediately hedge on the larger exchange
7. Update live order state and risk state
8. Repeat

**→ Live Order State and Risk**

Live order state was yet another important piece. The quote engine computed what orders it wanted to have live, but the system also needed a separate place to track what orders were currently working on the exchange. 

The live order state tracked things like:

- order id
- team / outcome
- price
- remaining quantity

![Image](https://pbs.twimg.com/media/HKWNszzWUAAE8t4?format=png&name=large)

One example of how live state is used by the quoting engine is illustrated in the image below. On each cycle, the engine first computes the quotes it wants to have live, then compares those desired quotes against the orders it believes are currently working on the exchange. That comparison determines whether the system should place a new order, keep an existing one, or replace a stale quote.

![Image](https://pbs.twimg.com/media/HKWM1d8XoAAIGAP?format=jpg&name=large)

Live order state also connected into hedging and risk logic. When a maker quote was filled on the smaller exchange, the fill event told the system how much size needed to be hedged on the larger exchange. After the hedge attempt completed, the system updated its risk state, especially the amount of unhedged exposure. If the hedge failed, only partially filled, or if market data became stale, the bot could stop quoting or cancel existing maker orders. 

# Problems I Ran Into and How I Fixed Them

This section is the main reason I wanted to write this article. These are the kinds of problems that are easy to underestimate before you start building, but almost impossible to avoid once real money, live APIs, and other traders are involved. 

I’m not going to cover **EVERY** bug, edge case, or failure mode here. Instead, I want to focus on the issues that felt most representative of running a real production trading system, and the ones I think other builders are most likely to run into. 

**→ Speed / Colocation**

The first major constraint was speed. The initial version of the system was **intentionally** **scrappy**: I wrote some parts of the initial system in Python and ran it from my laptop because I wanted to validate the opportunity quickly before spending time optimizing infrastructure. Once volume increased and markets became more volatile, the limitations were obvious. Liquidity could disappear before I was able to hedge, and sometimes my limit orders would go stale and get picked off, not because the strategy was wrong, but because the initial infrastructure was never built for low-latency execution.

My solution for this was straightforward:

- Completely rewriting my codebase in Rust
- Deploying code on an AWS EC2 instance with lower network latency to the venues I was trading on

These reduced latency meaningfully, and I noticed an immediate improvement in my ability to get hedges filled before the market moved away.

**→ Adverse Selection **

Another major problem was adverse selection. In trading, adverse selection happens when more informed traders hit your resting limit orders and trade against you. 

Early on, this was manageable because the exchange was less competitive. But as more sophisticated players entered the market, it became obvious that some traders were running bots specifically designed to pick off stale orders. If my bot left an outdated quote resting for even a short period of time, it would often get hit immediately.

Reducing it was really the result of improving the entire system: lower latency, better stale-data checks, faster cancels, more conservative edge buffers, reconciliation, and smarter quote placement. 

**→ Order Reconciliation (Ghost Cancels, Ghost Fills)**

In live trading, my local system’s view of open orders could **diverge** from what was actually live on the venue. For example, let's say an exchange returned a successful HTTP 200 OK response for a cancel request, but the order did not actually cancel. My local system would assume the order was gone, while in reality it was still resting on the exchange. 

This is very dangerous because if the bot believed an order had been canceled, fully filled, or otherwise removed when it was still active, that stale order could sit on the book and get picked off by another trader (adverse selection). 

I fixed this by building a reconciliation loop:

- Instead of trusting my local state, the system regularly compared my local order tracker against the exchange’s live orders
- If the API showed an order that my system thought should no longer exist, the system treated it as stale and canceled it again
- If an order was partially filled, the system recalculated the remaining open quantity and updated the hedge logic accordingly

This became one of the most important pieces of infrastructure because it prevented small state mismatches, stale orders, and partial-fill edge cases from turning into expensive execution mistakes.

**→ Weird Partial Fill Edge Cases**

Partial fills created a lot of edge cases. A quote could be partially filled while the bot was trying to cancel or replace it, which meant the system had to constantly recalculate remaining exposure instead of assuming orders were either fully live, fully canceled, or fully filled. The same issue could also happen on the hedge leg: if the system tried to hedge a fill but only got partially filled on the hedge venue, it had to decide whether to chase the remaining size, route somewhere else, or temporarily carry the exposure.

Example: 

- Quote engine: place a bid for 1,000 contracts at 47¢ on the smaller exchange
- Price moves; quotes are now stale
- Quote engine: sends a cancel/replace. But before the cancel fully resolves, someone hits 300 contracts of that order

Now my system has to know:

- 300 contracts filled and need to be hedged
- 700 contracts may still be live, canceled, or pending cancel
- I should NOT hedge 1,000 contracts
- I should NOT ignore the 300 contracts that managed to fill

If my bot assumes the order was fully canceled, it misses the 300-contract exposure. If it assumes the full 1,000 filled, it over-hedges by 700.

**→ WebSocket / Order Book Desync**

Live WebSocket data is not automatically safe to trust. A local order book is only accurate if it starts from a valid snapshot and then receives every update in order. If a message is missed, delayed, or applied incorrectly, the bot can end up quoting from a book that no longer matches the real exchange.

This is bad because the quote engine depends on the hedge book being accurate. If my local view says there is size available at 49¢, but that liquidity is already gone, then the system may place quotes that cannot actually be hedged.

My fix was to treat market data quality as part of the risk system. If a book became stale, missed sequence checks, or had not updated recently, the bot would stop quoting and cancel existing maker orders. I also used full snapshots to bootstrap local books before trusting incremental WebSocket updates.

**→ Observability**

Early on, debugging bad trades was harder than it needed to be. When something went wrong, I needed to answer questions like: What did my bot think the book looked like? Why did it place that quote? Did the cancel actually work? What hedge price did it use? Was the trade profitable after fees?

Adding more structured logging around quote decisions, order events, fills, hedge attempts, reconciliation, and risk checks made it much easier to reconstruct what happened after a bad fill and separate strategy problems from infrastructure problems.

**→ Basis / Resolution Risk (Differing Outcomes)**

As I expanded into crypto prediction markets, I found even wider spreads on the smaller exchange, with some markets averaging around 15¢. These were profitable, but they introduced basis risk: the “same” market on Kalshi or Polymarket and the smaller exchange did not always resolve the same way, which led to thousands of dollars in losses.

# Some Other Improvements I Made

After I fixed many of the initial bugs, I became more confident in the system and began doing more volume. I also started to encounter more and more sophisticated traders and I went all in on improvements. Some of the more notable improvements include:

**→ Smart Order Routing**

One of the biggest improvements was adding smart order routing. Fees and liquidity differed from venue to venue and an event on Exchange A might have higher liquidity and lower fees than Exchange B and vice versa. This let the system compare hedge prices, fees, available size, and execution risk across venues before deciding where to route.

The goal was simple: for every fill on the smaller exchange, hedge wherever the net expected outcome was best Sometimes that was Kalshi, sometimes it was Polymarket, regardless, this improved realized edge because the bot was no longer tied to a single hedge venue.

**→ Quoting Off Depth Ladders**

Another improvement was quoting off the full hedge depth ladder instead of only using the top of the book.

The first version of the system mostly quoted off the larger exchange's best bid and ask. That worked, but it limited how much size I could quote because I was only using the liquidity available at the very top level.

I changed the system to look deeper into the hedging venue’s order books and place multiple corresponding quote levels on the smaller exchange. For example, if there were bids at 49¢, 48¢, and 47¢, the bot could quote different bid levels on the smaller exchange, with each level priced to preserve enough edge after fees and buffers.

This improved profits because the bot could use more available hedge liquidity instead of only trading against the top of book. It increased the amount of safe quotable size, generated more fills, and let the strategy scale volume.

**→ Independent Crypto Pricing Model**

Eventually, I also built a separate pricing model for crypto prediction markets. Unlike the sports markets, this system did not rely on a prediction market as the main source of hedge liquidity. Instead, it priced markets independently and hedged exposure through more traditional crypto venues.

I’m keeping this section intentionally brief because the crypto system became its own project and deserves a full write-up of its own. 

# Conclusion

Building this system was one of the best learning experiences I’ve had. What started as a simple quoting bot quickly turned into a much deeper lesson in market structure, latency, APIs, hedging, stale orders, adverse selection, and risk management.

The biggest takeaway is that strategy is only one part of the problem. A quote that looks profitable in a spreadsheet can become unprofitable in production if your data is stale, your cancel is delayed, your local order state is wrong, or one of a hundred other things goes wrong.

These are the exact problems I wish I had understood before starting, and hopefully this writeup gives other builders a better starting point. 

Best of luck!