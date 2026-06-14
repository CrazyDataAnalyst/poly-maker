This summary provides a foundational overview of Market Making (MM) in prediction markets like Polymarket, based on the provided research and practitioner frameworks.

### 1. The Core Objective: "The Brain"
The fundamental problem for a market maker is determining where to stand (price) and how wide to quote (spread) while managing **inventory risk** (accumulating too much of one side) and **adverse selection** (trading against insiders).

*   **The Reservation Price ($r$):** The most critical concept in MM. Your fair value is **not** the market mid-price; it is a function of your current inventory.
    *   **Logic:** $r(s, q, t) = s - q \cdot \gamma \cdot \sigma^2 \cdot (T - t)$, where $s$ is mid-price, $q$ is inventory, $\gamma$ is risk aversion, $\sigma^2$ is volatility, and $(T-t)$ is time to resolution.
    *   **Practical Example:** If the mid-price is $0.50$ but you are **long** 10,000 YES tokens, your reservation price should be $0.48$. You quote more aggressively to sell and less aggressively to buy, pulling your inventory back toward zero.

### 2. Quoting & Risk Management: "The Walls"
*   **Optimal Spread:** This is the distance between your bid and ask quotes. It must be wide enough to compensate for risk but narrow enough to capture trade flow (maker rebates/rewards).
*   **Bounded Inventory (GLFT Model):** In prediction markets, you cannot "delta-hedge" the underlying probability. Therefore, you must set **hard inventory limits ($Q$)** to cap your maximum loss on a single binary outcome.
    *   **Practical Example:** If you are willing to lose a maximum of $50,000 on a $0.50 market, your $Q$ is 100,000 tokens. As you approach this limit, your spreads must widen exponentially until you stop quoting on the exposed side entirely.
*   **Logit Transformation:** Because prices are bounded between 0 and 1, professional models convert prices into **log-odds space** to prevent the math from quoting "impossible" prices (e.g., negative prices).

### 3. Adverse Selection: "The Defensive Shield"
**Adverse Selection** is the nightmare of being "picked off" by informed traders (insiders) who know the outcome before it reflects in the price.

*   **VPIN (Toxicity Metric):** A real-time monitor of volume imbalance. If buy and sell volume become highly asymmetrical, it signals that "toxic" informed flow is active.
    *   **Practical Example:** If VPIN spikes, your bot should immediately trigger a **kill switch**, widening spreads or withdrawing all quotes to avoid being exit liquidity for an insider.
*   **Tail Latency:** In market making, your **slowest 1% of cancels** matters more than your average speed. If you are slow to cancel a stale quote during a news jump, you will be filled at a loss.

### 4. Platform-Specific Mechanics: "The Rules"
*   **FIFO Matching:** Polymarket uses **First-In-First-Out** matching.
    *   **Common Mistake:** Staying at the front of the queue. Stale orders at the front are the first to get hit by a price swing.
    *   **Practical Example:** Professional bots constantly **cancel and replace** their own orders to stay at the *back* of the queue, ensuring they are the last to be hit.
*   **Liquidity Reward Farming:** The goal is often to **never get filled**. You place small orders within 2% of the midpoint to collect LP rewards and rebates while spreading capital across 50–100 small positions to limit the impact of any single toxic fill.

### 5. Common Mistakes to Avoid
1.  **Mid-Price Bias:** Treating the market mid-price as "fair" regardless of your inventory.
2.  **Ignoring the "Phase Transition":** Volatility spikes wildly near event resolution. Market making becomes "suicidal" in the final minutes if you aren't an insider.
3.  **Order Book Desync:** Trusting WebSocket data that has missed a sequence number. Quoting from a stale book leads to immediate losses.
4.  **Ghost Cancels:** Assuming an order is gone because you sent a cancel request; always use a **reconciliation loop** to verify the exchange's actual state.