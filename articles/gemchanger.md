# X Thread

Original post: https://x.com/gemchange_ltd/status/2025313265551651240
Captured: 2026-06-13T15:33:05.258Z
Order: original-post-first
Posts: 1
Root author: gemchanger (@gemchange_ltd)

---

## 1/1 — Post by gemchanger (@gemchange_ltd)

Post ID: 2025313265551651240
Source: https://x.com/gemchange_ltd/status/2025313265551651240
Reply to: none

Stats:
- Replies: 43
- Reposts: 152
- Quotes: 43
- Likes: 1,305
- Bookmarks: 3,508
- Impressions: 927,422

Text:

> http://x.com/i/article/2025291550276902912

Article:

**How Jump Trading, Jane Street, and a Guy With $10K Fighting Over the Same Polymarket Order Book**
Source: https://x.com/i/article/2025313265551651240

Plan is simple:
Part I: The Machine You're Trading Against
Part II: The Reservation Price (Or: The Single Most Important Number in Market Making)
Part III: The Bounded Inventory Problem (Guéant-Lehalle-Fernandez-Tapia)
Part IV: The Adverse Selection Nightmare (Glosten-Milgrom and Why Insiders Destroy Market Makers)
Part V: What the Bots Actually Do (The Production Stack)
Part VI: The Technical Infrastructure
Part VII: What This All Means
I want to tell you about a mass extinction event happening in real time.
In early 2024, an anonymous developer who goes by @defiance_cr built a market-making bot on Polymarket.

Starting capital: $10,000.
At peak, it was printing $700-800 a day.
That's roughly 2,700% annualized.

He was one of maybe "3-4 serious liquidity providers" on the entire platform. His description of the competitive landscape: "incredibly underdeveloped compared to traditional crypto markets - mostly individual traders clicking buttons."
By February 2026, he open-sourced the bot and posted a note: "this bot is NOT profitable in current market conditions due to increased competition."
What happened between those two dates is the story of this article.
In February 2026, Bloomberg reported that Jump Trading - the same Jump that moves billions through CME futures and was one of the largest Ethereum validators reached agreements to take equity stakes in both Polymarket and Kalshi.
Not just to trade.

To own pieces of the platforms in exchange for providing liquidity.
They hired approximately 20 people for a dedicated prediction-markets desk. DRW started recruiting for the same thing, offering $200K base salaries.
Susquehanna (SIG) had already been providing institutional liquidity on Kalshi since April 2024.
An account called "JaneStreetIndia" (later renamed "Account88888")

https://polymarket.com/@Account88888?via=8
appeared on Polymarket and extracted $360,000 in 25 days trading 15-minute crypto markets attribution is speculative since anyone can pick a username, but the trading pattern was unmistakably algorithmic.
Meanwhile, one anonymous sports market maker profiled in Polymarket's newsletter risks up to $300,000 on a single NFL Sunday.
The platform itself processed over $9 billion in volume in 2024 (up from $73 million in 2023 - a 120× increase) and exceeded $13 billion in 2025. Bot accounts representing just 3.7% of addresses generate 37.4% of total transaction volume.
This is the environment. And the math behind it is what separates the 0.04% of addresses that captured 71% of all realized gains from the 70% of addresses that lost money.
Let's get into it.
 
Part I: The Machine You're Trading Against
How Polymarket's order book actually works
Before we can talk about market-making math, you need to understand what you're quoting into.
Polymarket runs a hybrid-decentralized Central Limit Order Book (CLOB).
Orders are signed off-chain as EIP-712 messages, matched by Polymarket's centralized operator, and settled atomically on-chain via the Polygon network. The operator's powers are strictly bounded - it can match crossing orders but cannot set prices, execute unauthorized trades, or censor participants.
Here's what makes the plumbing interesting. There are three ways an order can fill:
Direct Transfer. You want to buy YES tokens. Someone else is selling YES tokens. Tokens change hands. Simple.
Minting. You want to buy YES at $0.70. Someone else wants to buy NO at $0.30. The system locks $1.00 USDC as collateral and creates a new YES + NO token pair, giving one to each of you. This is how new supply enters the market.
Merging (Burning). You want to sell YES at $0.60. Someone else wants to sell NO at $0.40. Equal quantities of YES and NO tokens are destroyed and $1.00 USDC collateral is released back. Supply exits the market.
The invariant P(YES) + P(NO) = $1.00 isn't a convention. It's enforced at the smart contract level through this minting/merging mechanism. Every token pair is backed by exactly $1 of USDC collateral.
Under the hood, all of this runs on Gnosis' Conditional Token Framework (CTF). Each binary market creates two ERC-1155 position IDs:
 
For multi-outcome mutually exclusive markets (e.g., "Who wins the 2028 election?" with 8 candidates), a separate NegRiskAdapter wraps USDC into WrappedCollateral to enable NO→YES conversions across outcomes.
The fee structure matters for market makers. Most markets carry 0% fees for both makers and takers. Fee-enabled markets (15-minute crypto, select sports) use a formula designed to be nearly invisible at extreme prices:
fee = baseRate × min(price, 1 − price) × size
That min(price, 1 − price) factor caps the effective rate at ~1.56% when p = 0.50 and drives it toward zero as prices approach 0 or 1. Taker fees get redistributed daily as maker rebates.
Tick sizes are $0.01 or $0.001 depending on the market. Valid prices range from $0.01 to $0.99. Rate limits: 3,000 order requests per 10-minute window.
This is what you're quoting into. Now let's talk about how to quote.
 
Part II: The Reservation Price (Or: The Single Most Important Number in Market Making)
The Avellaneda-Stoikov framework
In 2008, Marco Avellaneda and Sasha Stoikov published a paper that became the Bible of quantitative market making. The question they answered: if you're a market maker quoting bid and ask prices on a limit order book, and you're risk-averse, and you have inventory that you'd prefer not to hold overnight - what are the mathematically optimal quotes?
Their answer starts with three assumptions about the world.
The mid-price follows arithmetic Brownian motion:
 
Order arrivals are Poisson processes whose intensity decreases exponentially with your quote distance from mid:
 
The further you quote from the current price, the less likely someone hits your order. A is the baseline arrival rate (how active the market is), and κ measures how sensitive traders are to price - high κ means traders won't chase, low κ means they'll cross wide spreads.
The market maker's preferences are CARA (Constant Absolute Risk Aversion) with parameter γ:
 
The optimization problem: maximize expected terminal utility of wealth at time TT T, choosing bid offset δ^b and ask offset δ^a from mid-price at every instant.
 
where X_T​ is cash and q_T S_T is the mark-to-market value of inventory. This leads to a Hamilton-Jacobi-Bellman PDE that, under the CARA assumption, separates into a tractable form.
The key result - the one that every market-making desk in the world uses some version of - is the reservation price:
 
Read this carefully.
It says: the fair price at which the market maker is indifferent to trading is the mid-price, shifted linearly by inventory.
If you're long (q>0q > 0 q>0), your reservation price drops below mid - you want to sell.
If you're short (q<0q < 0 q<0), it rises above mid - you want to buy.
The shift scales with three things:
how risk-averse you are (γ)
how volatile the asset is (σ^2)
how much time you have left (T−t).
The optimal spread (total bid-ask distance) is:
 
Two terms, two sources of edge.
The first term is inventory risk compensation - wider spreads when the world is volatile.
The second term is the pure informational profit from being a market maker - this persists even if you're risk-neutral.
As γ→0, the first term vanishes but the second doesn't. You always earn something from providing liquidity.
Individual quotes are skewed around the reservation price:
 
When you're flat (q = 0), quotes are symmetric around mid. As inventory grows long, your ask tightens (you quote more aggressively to sell) and your bid widens (you're less eager to buy more).
This is elegant. This is also wrong for prediction markets.
Why prediction markets break the standard model
Here's the problem. Avellaneda-Stoikov was built for equities. It assumes three things that prediction markets violate:
Problem 1: Unbounded prices.
Arithmetic Brownian motion lets the price wander
Solution:
Work in log-odds space. This is the logistic sigmoid - the same function in every neural network. Prices are guaranteed to stay in (0,1)
Problem 2: Terminal binary settlement.
Equities have continuous terminal values. Prediction markets settle at exactly 0 or exactly 1. As t→T, the price must converge to one of two absorbing barriers.
The "volatility" doesn't just decrease - it undergoes a phase transition. Near resolution, the price becomes dominated by belief about which barrier it's heading toward, not smooth diffusion.
Problem 3: Event-driven jumps.
Avellaneda-Stoikov assumes continuous paths. But prediction market prices jump discontinuously - an election is called, a goal is scored, a court ruling drops. You need a jump-diffusion model, not pure Brownian motion.
Dalen (2025) proposed what may become the standard pricing kernel for prediction markets - the logit jump-diffusion:
 
This decomposes prediction market risk into four factors:
delta (directional exposure)
gamma (curvature / sensitivity to news)
belief-vega (sensitivity to σ_b)
cross-event correlation
For a market maker, this means you can systematically characterize your risk - and start hedging it.
Problem 4: No delta-hedging.
In equity market making, if you accumulate too much inventory, you can hedge by trading the underlying.
In prediction markets, the "underlying" is an unobservable probability. There's no replicating portfolio. You can't buy "the probability that Trump wins" on another exchange to hedge your Polymarket inventory.
This means market makers must manage inventory risk entirely through spread adjustment, position limits, and cross-market hedging of correlated events - which brings us to the next framework.
 
Part III: The Bounded Inventory Problem (Guéant-Lehalle-Fernandez-Tapia)
Why position limits aren't optional
Imagine you're market-making the "Will BTC hit $150K by June?" contract.
Your Avellaneda-Stoikov model says the reservation price is $0.42. You start quoting $0.40 bid / $0.44 ask. People start buying YES tokens from you. Your inventory goes short. The model adjusts - your reservation price rises, your ask tightens. More buying. More inventory.
At what point do you stop?
In traditional equity market making, this question has a soft answer - you can always hedge.
In prediction markets, there's a hard answer: if you're short 100,000 YES tokens at an average entry of $0.40, and the event resolves YES, you owe $100,000 and collected $40,000. That's a $60,000 loss. From a single market.
Guéant, Lehalle, and Fernandez-Tapia (2013) solved this by introducing explicit inventory bounds ∣q∣≤Q into the Avellaneda-Stoikov framework and deriving closed-form optimal quotes:
 
For prediction markets, Q maps directly to maximum tolerable loss from a single binary outcome.
If you can stomach losing 50,000 on one market, and the price is $0.50, then $Q = 100,000  tokens. The GLFT framework ensures your spreads naturally widen as you approach that limit, and your quotes disappear entirely when you hit it.
Guéant (2017) further extended this to multi-asset market making, which is directly applicable to Polymarket because you're often making markets in multiple correlated outcomes simultaneously (all state election markets, multiple NFL games, etc.).
 
Part IV: The Adverse Selection Nightmare (Glosten-Milgrom and Why Insiders Destroy Market Makers)
Why the spread exists and why it's not about greed
Every spread in every market in the world exists primarily for one reason: adverse selection. Some of the people hitting your quotes know more than you do. The spread is the tax you charge to survive the fact that you're occasionally trading against people with better information.
The zero-profit ask price (the price at which you're indifferent to selling) is the expected value conditional on someone wanting to buy:
 
Because informed traders buy when V=1V = 1 V=1 (probability p weighted by informed fraction μ), and noise traders buy regardless.
Similarly:
 
At p=0.5, the spread simplifies to exactly μ. The spread is the informed trader fraction. Even a risk-neutral, competitive market maker in a frictionless market must charge a positive spread - zero spread means guaranteed losses to insiders.
In prediction markets, this is existentially dangerous. Information asymmetry can be extreme: campaign staff know private polling data, athletes know their own injury status, corporate insiders know regulatory decisions before they're public. Near resolution, μ effectively approaches 1, and market making becomes suicidal.
Kyle's lambda - measuring price impact
Kyle (1985) adds another lens. The price impact coefficient λ measures how much each unit of net order flow moves the price:
 
Higher λ = lower liquidity = more adverse selection.
In prediction markets, λ spikes near resolution.
As the outcome approaches certainty, σv\sigma_v σv​ increases (the binary outcome is about to resolve) while σ_u​ may decrease (casual traders exit). This creates a toxic environment where the remaining flow is predominantly informed.
VPIN a real-time toxicity alarm
How do you detect that informed traders are arriving before they clean you out?
Easley, López de Prado, and O'Hara (2012) developed VPIN (Volume-Synchronized Probability of Informed Trading), which estimates the proportion of toxic flow in real time:
 
If buy volume and sell volume are balanced, flow is noise.
If they're imbalanced, someone with information is aggressively buying or selling.
VPIN spiked to extreme levels more than 2 hours before the 2010 Flash Crash.
In prediction markets, VPIN serves as a real-time kill switch trigger:
when VPIN rises sharply, the market maker widens spreads or withdraws quotes entirely
Research from Krypton Labs found DeFi/AMM trade toxicity approximately 3.88× higher than centralized exchange toxicity - suggesting prediction market makers face elevated adverse selection simply by operating on-chain.
 
Part V: What the Bots Actually Do (The Production Stack)
Where theory meets Polymarket's incentive structure
The spread-setting algorithm combines four layers:
Layer 1
A base spread from Avellaneda-Stoikov/GLFT, scaled to the market's realized belief volatility across multiple timeframes (3h, 24h, 7d, 30d).
Layer 2
An inventory-skew component that shifts the midpoint based on current position. Long inventory -> lower reservation price -> tighter ask, wider bid.
Layer 3
A reward-optimization overlay. Polymarket distributes roughly $12 million annually in liquidity rewards. The reward formula uses a quadratic spread function that penalizes orders far from midpoint. Two-sided quoting earns approximately 3× the rewards of single-sided. The bot optimizes quote placement against the max_incentive_spread parameter to maximize rebate capture while maintaining risk constraints.
Layer 4
A toxicity filter that widens or withdraws quotes when VPIN or volume anomalies signal informed trading.
Dutch Book detection
If the sum of all outcome prices in a mutually exclusive market deviates from $1.00, buy the cheap side. This is pure arbitrage.
Conditional hedging
A long position in "Trump wins Pennsylvania" can be partially hedged with a short position in "Trump wins the election," since Pennsylvania is highly correlated with the national outcome. The hedge ratio depends on the conditional probability structure.
Cross-platform arbitrage
Identical events priced differently on Polymarket vs. Other Platform. BTC $70K YES at $0.45 on Polymarket vs. NO at $0.48 on Other Platform implies 7 cents of free money, minus execution risk and fees.
The kill switch architecture for a production bot:
Good-Till-Date (GTD) orders auto-expire before known high-impact events (election calls, Fed announcements), preventing stale quotes from being adversely filled.
cancelAll() API calls halt all outstanding orders on detection of error conditions, position breaches, or toxicity spikes.
Staged withdrawal near resolution
spreads widen progressively as event resolution approaches. In the final minutes of a high-impact event, quotes are fully withdrawn. The Glosten-Milgrom adverse selection cost dominates all other considerations near expiry - a market maker quoting $0.95/$0.97 when insiders know the outcome faces catastrophic expected losses.
The average arbitrage window has compressed from 12.3 seconds in 2024 to 2.7 seconds in Q1 2026, with 73% of arbitrage profits captured by sub-100ms bots. The competitive frontier is moving from "can you run a bot" to "can you run a bot that processes NLP on live news feeds faster than Jump Trading's 20-person desk."
 
Part VI: The Technical Infrastructure
Four-module bot architecture
Data Collector
WebSocket connections for real-time orderbook updates. Tracks sequence numbers to detect missed messages. Maintains a local orderbook copy with incremental updates. Handles reconnection with exponential backoff.
Strategy Engine
Computes fair value via Bayesian probability model (the LMSR-like belief layer). Calculates optimal spreads via Avellaneda-Stoikov/GLFT (the execution layer). Applies inventory skew. Determines order sizes via Kelly criterion.
Order Manager
Batch order placement via postOrders(). Cancel/replace cycles for requoting. GTD expiration management. PostOnly flag (added January 2026) to ensure limit-only execution.
Risk Manager
Position limit enforcement. VPIN monitoring. Kill switch logic. Real-time P&L tracking. CTF splitting/merging for capital management.
Latency
Off-chain matching is near-instantaneous.
On-chain settlement occurs within Polygon's ~2-second block times.
Gas costs average ~$0.007 per transaction - negligibly cheap.
Professional market makers target sub-10ms total round-trip, achievable with colocated VPS near Polygon nodes.
The critical race isn't placing orders - it's canceling them. The ability to cancel stale quotes before an informed trader adversely fills you is the single most important latency metric.
 
Part VII: What This All Means
Let me put this bluntly. The remaining edge belongs to participants who can do three things simultaneously:
Price events more accurately than the market (superior probability models, faster information processing, proprietary data).
Manage the unique risk structure of binary outcomes (the logit transformation, jump-diffusion calibration, terminal settlement mechanics, no delta-hedging).
Execute at institutional quality (sub-10ms latency, robust kill switches, capital-efficient CTF splitting, cross-market hedging across thousands of correlated contracts).
If you can do all three, there's still money on the table. But the window where $10K and a Python script could compete is closed.
The firms that understood this first already have their 20-person desks built.
References & Resources
Core papers:
Avellaneda & Stoikov, "High-Frequency Trading in a Limit Order Book" (2008)
Guéant, Lehalle, Fernandez-Tapia, "Dealing with the Inventory Risk" (2013)
Guéant, "Optimal Market Making" (2017)
Hanson, "Logarithmic Market Scoring Rules for Modular Combinatorial Information Aggregation" (2003/2007)
Chen & Pennock, "A Utility Framework for Bounded-Loss Market Makers" (2007)
Glosten & Milgrom, "Bid, Ask, and Transaction Prices in a Specialist Market" (1985)
Kyle, "Continuous Auctions and Insider Trading" (1985)
Easley, López de Prado, O'Hara, "Flow Toxicity and Liquidity in a High-Frequency World" (2012)
Dalen, "Toward Black-Scholes for Prediction Markets" (2025), arXiv:2510.15205
Lorig, Zhou, Zou, "Optimal Bookmaking" (2021)
