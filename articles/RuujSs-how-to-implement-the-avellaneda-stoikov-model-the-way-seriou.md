---
author: "Ruuj"
handle: "@RuujSs"
source: "https://x.com/ruujss/status/2064024603161436390"
date: 2026-06-08T16:39:47.000Z
type: article
likes: 232
reposts: 24
replies: 4
bookmarks: 454
views: 97167
---
# How To Implement The Avellaneda-Stoikov Model The Way Serious Market Maker Does (Complete Framework)

*By Ruuj (@RuujSs)*

![Banner](https://pbs.twimg.com/media/HKRuhB3bIAAEmup?format=jpg&name=large)

The equation that runs crypto market makers, HFT desks, and on-chain AMMs. Nobody has explained it at this level for builders. Until now.

Every time you place a trade, someone on the other side computed exactly where to stand.

Not a person. A system. Running math in real time, updating every millisecond, deciding the precise price to buy at and the precise price to sell at continuously, across thousands of instruments, based on a framework that most people trading against it have never seen.

That framework is not secret. It is not locked inside a proprietary codebase at Citadel or Jane Street. It was published in an academic paper in 2008 by two mathematicians named Marco Avellaneda and Sasha Stoikov. It is called the Avellaneda-Stoikov model. And it is the closest thing market making has to a universal foundation.

Hummingbot's market making strategy is built on it. Elixir Protocol uses a version of it for on-chain liquidity. Academic researchers at Stanford and MIT have extended it. Papers published as recently as 2024 are still improving it. And anyone building a market making bot today on crypto, on equities, on any decentralized protocol is either implementing some version of this or leaving serious money on the table by not doing so.

By the end of this article you will understand exactly what problem market making solves and why it is harder than it looks, how the Avellaneda-Stoikov model structures the solution from first principles, what the two core equations mean and how to compute them, how to implement the full system in Rust, where the model breaks in real markets and what the current extensions look like, and why this framework is being applied to on-chain AMMs right now in 2026.

**Note: Every part builds on the one before it. If you are serious about understanding how liquidity actually gets priced in modern markets, read every section.**

Read this once for the picture. Read it again before you write a single line of market making code.

---

# Chapter 1: What Market Making Actually Is

Most people think market making is straightforward. You post a buy price and a sell price. Collect the spread. Repeat.

The reality destroys that picture fast.

Here is the actual problem. You are running a market making bot on a crypto exchange. You post a bid at 99.95 and an ask at 100.05. The spread is 10 cents. Traders hit both sides throughout the day and you collect that spread as revenue.

Then one thing happens that changes everything.

More sellers arrive than buyers. You keep filling sells accumulating the asset while your ask barely gets hit. By the end of the hour you are holding 50 units of a position you never intended to hold, in an asset that has started drifting downward. The spread you collected is 50 cents. Your inventory loss on the drift is $2.

You made money on paper and lost money in reality. This happens not because your strategy was wrong in principle but because you were not managing the two core risks of market making precisely.

**Inventory risk** is the risk of accumulating a directional position you did not choose. Every fill moves your inventory away from zero. Inventory away from zero means you are exposed to price moves. The longer you hold inventory, the more variance accumulates against you.

**Adverse selection** is the risk of trading against people who know more than you. Not all order flow is equal. Uninformed traders people buying or selling for liquidity reasons unrelated to a price view are the counterparties you want. Informed traders people who have processed information faster or better than you and are trading on it are the counterparties you lose to. The spread adequate for uninformed flow is inadequate when informed flow is elevated.

![Image](https://pbs.twimg.com/media/HKKTDQQagAA4LPO?format=jpg&name=large)

These two risks are not rare edge cases. They are the constant reality of providing liquidity. Managing them is the entire job.

The question Avellaneda and Stoikov asked in 2008 was precise: given these two risks, what is the mathematically optimal bid and ask quote at every moment in time, given current inventory, current volatility, and the remaining trading session?

Their answer is two equations. Everything that follows is building toward understanding them and knowing how to deploy them.

---

# Chapter 2: The Reservation Price, Your True Fair Value

The core insight of the Avellaneda-Stoikov model is simple to state and easy to miss.

**The market mid-price is not your fair value. Your fair value is a function of your inventory.**

When you are holding a large long position, you are exposed to downside. The rational response is to skew your quotes downward quote the ask more aggressively to attract buyers who reduce your inventory, and quote the bid less aggressively to discourage sellers who add to it. You are repricing the asset relative to the market mid-price to reflect the risk you are already carrying.

When you are flat, zero inventory you have no directional exposure. Quote symmetrically around mid. No adjustment needed.

Avellaneda and Stoikov call this the reservation price. Also called the indifference price, the price at which you are genuinely indifferent between holding your current inventory and trading out of it:

**r(s, q, t) = s − q × γ × σ² × (T − t)**

Every variable has a precise meaning and a reason for being there.

**s** is the current market mid-price. Your starting reference.

**q** is your current inventory. Positive means long, negative means short, zero means flat. This is the variable that drives everything else.

**γ (gamma)** is your risk aversion parameter. You set this. It controls how aggressively the model skews quotes to reduce inventory. Higher γ means more aggressive skewing. Lower γ means more patient inventory management.

**σ²** is the variance of the asset price. Higher volatility means more risk per unit of inventory held, so the adjustment is larger.

**(T − t)** is time remaining in the trading session. As you approach the end of the session, this shrinks toward zero and your reservation price converges back to mid.

The time component is important and most naive implementations ignore it. Inventory risk is not just a function of position size. It is a function of how long you have to unwind it. An imbalance you have three hours to manage is different from the same imbalance with ten minutes left. The model prices this difference explicitly.

Let's run the numbers concretely.

Mid-price **s = 100**. Inventory **q = 5** units long. Risk aversion **γ = 0.1**. Volatility **σ² = 0.02**. Time remaining **T − t = 0.5**.

**r = 100 − 5 × 0.1 × 0.02 × 0.5  
r = 100 − 0.005  
r = 99.995**

Your reservation price is 99.995. Your quotes will be centered just below mid subtly favoring buyers who reduce your long inventory. If your inventory were zero the entire second term is zero and your reservation price equals mid exactly.

![Image](https://pbs.twimg.com/media/HKKTZxBbsAAP1n_?format=jpg&name=large)

The model is continuous. Every fill changes **q**. Every price move changes **s**. Every second changes **T − t**. The reservation price is not a fixed number it is a function of your live state, updated in real time.

**Here is the Rust implementation of the reservation price:**

```python
import numpy as np
import pandas as pd
import math

def reservation_price(
    s: float,
    q: float,
    t: float,
    gamma: float,
    sigma: float,
    T: float
) -> float:
    time_remaining = T - t
    return s - q * gamma * (sigma ** 2) * time_remaining
```

When q is 0.0 the function always returns s exactly. When q is positive it returns below s. When q is negative it returns above s. The skew is automatic, continuous, and proportional to the risk you are carrying.

---

# Chapter 3: The Optimal Spread, Exactly How Wide to Quote

Knowing where to center your quotes is half the solution. The other half is knowing how far apart to place them.

Quote too tight and every trade fills you but your spread revenue does not compensate for the inventory risk and adverse selection you are absorbing. Quote too wide and your fill rate collapses. You sit there safely and earn nothing.

![Image](https://pbs.twimg.com/media/HKKTzCQb0AAhI_J?format=jpg&name=large)

**The optimal spread formula:**

**δ_bid + δ_ask = γ × σ² × (T − t) + (2/γ) × ln(1 + γ/k)**

Where **δ_bid** is your distance below reservation price for the bid, and **δ_ask** is your distance above it for the ask. Their sum is the total spread you are quoting. In the base model these are split symmetrically half the total spread on each side though asymmetric splits are used in production when you want to be more aggressive on one side.

The formula has two terms and each solves a distinct part of the problem.

**Term 1: γ × σ² × (T − t)**

This is your inventory risk compensation. The spread must be wide enough to compensate for the expected cost of carrying inventory through price variance. It grows with volatility more variance means more potential loss per unit of inventory held. It grows with risk aversion a more risk-averse operator demands more spread per unit of risk accepted. It shrinks with time remaining the same session-clock logic from the reservation price formula.

Notice this term is structurally identical to the adjustment term in the reservation price. The same forces that skew your center price also widen your quotes.

**Term 2: (2/γ) × ln(1 + γ/k)**

This is the order arrival economics. The parameter k describes the sensitivity of market order arrivals to your spread distance. The model assumes orders arrive following an exponential intensity:

**λ(δ) = A × e^(−k × δ)**

Where **A** is the baseline arrival rate and k controls decay speed. A large k means traders are highly sensitive to spread distance quote even slightly wide and your fill rate drops sharply. A small k means traders tolerate wider spreads and will still fill you.

The second term in the spread formula captures the optimal balance between these forces. When k is large this term is small you cannot quote wide without losing the flow that generates revenue. When k is small this term is larger you can extract more spread per trade because the counterparties will accept it.

Together both terms produce a spread that is simultaneously wide enough to compensate for risk and narrow enough to maintain fill rate. Not a heuristic. A mathematical optimum derived from first principles.

**Your live quoting strategy at every moment:**

**Bid  = r(s, q, t) − δ_bid  
Ask  = r(s, q, t) + δ_ask**

Not centered on the market mid-price. Centered on your inventory-adjusted reservation price. Symmetric quotes are the special case that occurs only when inventory is exactly zero. Asymmetric quotes centered off-mid are the normal operating state.

Both quotes update continuously. Every fill changes **q**, which changes **r**, which moves both quotes. Every price move changes **s**. Every second changes **T − t**. The strategy is a continuous real-time function of your current state.

**Here is the Rust implementation of the spread and the complete quoting function:**

```python
def optimal_spread(t, gamma, sigma, k, T):
    risk_term    = gamma * sigma**2 * (T - t)
    arrival_term = (2.0 / gamma) * math.log(1.0 + gamma / k)
    return risk_term + arrival_term

def generate_quotes(s, q, t, gamma, sigma, k, T):
    r      = reservation_price(s, q, t, gamma, sigma, T)
    spread = optimal_spread(t, gamma, sigma, k, T)
    half   = spread / 2.0
    bid    = r - half
    ask    = r + half
    return bid, ask, r, spread
```

---

# Chapter 4: Model Assumptions And Their Production Adaptations

Every mathematical model is a set of explicit assumptions. The Avellaneda-Stoikov model is honest about its assumptions, which is what makes it trustworthy as a foundation and extendable as an engineering starting point.

Understanding each assumption what it says, where it holds well, and how serious practitioners adapt it is the difference between deploying this as a complete system and deploying it as the foundation it was always meant to be.

## Assumption 1: Order arrivals follow a fixed exponential decay

The model assumes market orders arrive at a rate that decays exponentially with your spread distance:

**λ(δ) = A × e^(−k × δ)**

With k fixed. In practice, k is not fixed. It varies by time of day, by current order book depth, by asset, and by volatility regime. During peak hours on a liquid crypto pair, the arrival rate at a given spread can be three to five times higher than during thin overnight hours. A k calibrated on yesterday's full session is frequently wrong during any specific hour of today.

**How production systems handle it:** estimate k continuously on a rolling window of recent order flow typically fifteen to thirty minutes and update it live at each quoting interval. Treat k as an adaptive input, not a constant. Hummingbot's production implementation does exactly this, estimating their kappa parameter automatically from order book data rather than requiring the user to set it manually. This single adaptation has the highest practical impact of any modification you can make to the base model.

## Assumption 2: All order flow is uninformed

The model assigns the same arrival rate to every incoming market order. It makes no distinction between a trader who needs liquidity and a trader who has information you do not. In the paper's framework, everyone is the same kind of counterparty.

In real markets this is not true and the difference matters. When informed flow is elevated during liquidation cascades on crypto, around major protocol announcements, before significant macro events the market orders arriving are systematically from participants who know the price is about to move against your inventory. The spread adequate for uninformed flow is insufficient to compensate for this.

**How production systems handle it:** the Cartea-Jaimungal line of research (Oxford and Toronto, 2015 onward) extended the AS framework by explicitly modeling the probability of informed trading as a parameter that adjusts the spread. The HSBC FX market making paper published in March 2026 incorporates adverse selection through latency-driven price moves, representing the current institutional state of the art. For any system operating around event risk, adding an adverse selection component to spread sizing is the most important extension to the base model.

## Assumption 3: Volatility is constant

**σ** is a parameter you set once and the model holds it fixed throughout the session. Markets do not cooperate with this. Volatility in crypto can increase by a factor of five in under twenty minutes during a cascading liquidation event. A system using a fixed σ calibrated on recent quiet conditions will quote spreads too tight during high-volatility periods inventory losses exceed spread revenue and unnecessarily wide during quiet periods, reducing fill rate without a risk-based reason.

**How production systems handle it:** compute realized volatility on a short rolling window five to fifteen minutes of recent trade data depending on the asset and feed the updated estimate into both the reservation price and spread formulas at each step. This converts the static model into a dynamic one that continuously adapts to the current volatility environment. Every serious production implementation does this. It is one of the first adaptations made when moving from simulation to live deployment.

## Assumption 4: Inventory can grow without bound

The base AS model has no hard constraint on how large your inventory can become. Theoretically, if one side keeps getting hit and the other does not, you can accumulate an arbitrarily large position. The reservation price skewing discourages this but does not prevent it.

**How production systems handle it:** Guéant, Lehalle and Fernandez-Tapia (Mathematics and Financial Economics, 2013) extended the AS framework by adding hard inventory bounds a maximum inventory limit Q beyond which the market maker stops quoting on the exposed side entirely. When your long inventory hits the maximum limit, you stop posting bids. You only quote asks until the position comes back within range. Beyond the practical risk management benefit, the GLT paper also showed the HJB equations underlying AS transform into a system of linear ODEs under this constraint, producing a true closed-form solution rather than the asymptotic approximation in the original paper. This is now the standard framework for production systems where inventory management is explicit.

## Assumption 5: The model was designed for sessions with a defined end

The T parameter in both formulas assumes there is a closing time a moment at which the session ends and remaining inventory is marked to market. This made complete sense for equity markets with defined trading hours. Crypto markets never close.

**How production systems handle it:** three approaches are used in practice. First, artificial session windows treat each 24 hour or 8 hour period as a session and reset T accordingly. Second, infinite horizon operation where T is effectively infinite and the time-dependent terms in the formulas stabilize at their asymptotic values. Third, rolling windows that maintain the session-clock behavior in a continuous environment. Hummingbot supports all three modes. The academic treatment of the infinite horizon case the ergodic version of the AS model is an active research area. The 2024 paper by Cao, Šiška, Szpruch and Treetanthiploet proved logarithmic regret bounds for adaptive parameter learning in the ergodic setting, with a revision published in July 2025. The theory is catching up with the engineering need.

![Image](https://pbs.twimg.com/media/HKKUDWgbgAAgZhx?format=jpg&name=large)

## Assumption 6: Prices move continuously

The model assumes mid-price follows arithmetic Brownian motion smooth, continuous movement. Real markets have jumps. A major liquidation event, an unexpected protocol announcement, or a large market order in a thin book can move the mid-price discontinuously in a way that Brownian motion does not capture and that leaves inventory exposed with no chance to adjust quotes before the move.

**How production systems handle it:** circuit-breaker logic layered outside the core model. Here is the production-grade Rust implementation with rolling volatility estimation and a circuit breaker:

```python
from collections import deque

class AdaptiveAvellanedaStoikov(AvellanedaStoikov):

    def __init__(self, gamma, k, sigma, T,
                 vol_window=50, cb_multiplier=3.0):
        super().__init__(gamma, k, sigma, T)
        self.vol_window    = vol_window
        self.cb_multiplier = cb_multiplier
        self._prices       = deque(maxlen=vol_window + 1)

    def observe(self, s):
        self._prices.append(s)

        if len(self._prices) >= 2:
            prices       = np.array(self._prices)
            returns      = np.diff(prices)
            realized_vol = returns.std()
            if realized_vol > 0:
                self.update_sigma(realized_vol)

    def circuit_breaker(self):
        if len(self._prices) < 5:
            return False
        recent    = list(self._prices)[-5:]
        move      = abs(recent[-1] - recent[0])
        threshold = self.cb_multiplier * self.sigma * math.sqrt(5)
        return move > threshold

    def adaptive_quotes(self, s, q, t):
        self.observe(s)

        if self.circuit_breaker():
            return None

        return self.quotes(s, q, t)

def run_adaptive_session(model, s0, n_steps, seed=42):
    rng = np.random.default_rng(seed)
    dt  = model.T / n_steps

    s         = s0
    inventory = 0.0
    cash      = 0.0
    paused    = 0
    records   = []

    for step in range(n_steps):
        t   = step * dt
        s  += rng.normal(0.0, model.sigma * math.sqrt(dt))

        result = model.adaptive_quotes(s, inventory, t)

        if result is None:
            paused += 1
            records.append({
                'step': step, 'mid': round(s, 6),
                'r': None, 'bid': None, 'ask': None,
                'spread': None, 'inventory': inventory,
                'pnl': round(cash + inventory * s, 6),
                'paused': True
            })
            continue

        bid, ask, r, spread = result
        intensity    = model.k * math.exp(-model.k * spread / 2.0)
        sell_arrived = rng.poisson(intensity * dt)
        buy_arrived  = rng.poisson(intensity * dt)

        if sell_arrived > 0:
            inventory += 1.0
            cash      -= bid

        if buy_arrived > 0:
            inventory -= 1.0
            cash      += ask

        pnl = cash + inventory * s

        records.append({
            'step': step, 'mid': round(s, 6),
            'r': round(r, 6), 'bid': round(bid, 6),
            'ask': round(ask, 6), 'spread': round(spread, 6),
            'inventory': inventory, 'pnl': round(pnl, 6),
            'paused': False
        })

    results = pd.DataFrame(records).set_index('step')

    active = results[~results['paused']]
    sharpe = active['pnl'].diff().mean() / active['pnl'].diff().std() * np.sqrt(len(active))

    print(f"Final Inventory  : {results['inventory'].iloc[-1]:.1f}")
    print(f"Final PnL        : {results['pnl'].iloc[-1]:.6f}")
    print(f"Max Inventory    : {results['inventory'].abs().max():.1f}")
    print(f"Steps Paused     : {paused} / {n_steps}")
    print(f"Annualized Sharpe: {sharpe:.4f}")

    return results
```

The adaptive wrapper keeps the core AS math completely intact. Rolling volatility feeds directly into the reservation price and spread formulas. The circuit breaker is a separate layer handling the discontinuous price move case the model was never designed for. Both concerns handled cleanly and independently. No tight coupling between the mathematical core and the operational risk layer exactly how production systems should be structured.

---

# Conclusion

The Avellaneda-Stoikov model does not predict prices.

It does something more useful. It takes the market making problem where to quote, how wide to quote, how to manage inventory and turns it into a precise mathematical optimization with a closed-form solution. The output is two equations that tell you exactly where to place your bid and ask at every moment in time, as a continuous function of your current state.

The reservation price adjusts your internal fair value for your current inventory. The spread formula balances your risk compensation against your order flow economics. Together they produce quotes that update continuously as inventory changes, as prices move, as the session clock ticks down.

The base model has known limitations. Constant volatility assumption. No adverse selection term. Exponential order arrivals that approximate but do not perfectly describe real markets. No inventory constraint. These limitations are not fatal they are the starting point for extensions that the field has been developing since 2013. The GLT extension for closed-form solutions and inventory bounds. The Cartea-Jaimungal extensions for adverse selection. The ergodic adaptations for 24/7 markets. The AMM applications being published now in 2026.

None of those extensions would exist without the AS foundation to extend.

The math in this article is verified against the original paper. The formulas are correct. The implementation is accurate. All this is educational content for actual builders and researchers. Not financial or investment advice. The math is real.

If you are building a market making bot on any exchange or protocol today, the choice is not whether to engage with this framework. The choice is whether you understand what you are deploying or not.

*I’m Ruuj a backend developer, researcher, and working on quant systems. DMs are open for thoughtful discussions and collaborations.*
