"""
Performance metrics and equity curve for a completed backtest.

Before this, a run reported three numbers: net P&L, trade count, win rate.
None of those tell you whether a strategy is worth trading. A 90% win rate
with one catastrophic loss is a losing strategy; net P&L alone hides the
drawdown you would have had to sit through.

Everything here is derived from the stored trades table, so metrics can be
recomputed for any historical run without re-running the backtest.

Honest limits, stated up front:
- Sharpe and Sortino are computed per-trade, not on a daily equity series, and
  are annualised with a nominal 252-day factor scaled by trade frequency. With
  a handful of trades they are noise. They are reported with the sample size
  so nobody reads a Sharpe of 3.0 off four trades and believes it.
- Drawdown is measured on the closed-trade equity curve, not mark-to-market,
  so intra-trade drawdown is not captured.
"""
from __future__ import annotations

import math
from datetime import date

MIN_TRADES_FOR_RATIOS = 5
TRADING_DAYS_PER_YEAR = 252


def _to_iso(value) -> str:
    if isinstance(value, (date,)):
        return value.isoformat()
    return str(value)


def equity_curve(trades: list[dict], starting_equity: float = 0.0) -> list[dict]:
    """
    Cumulative net P&L after each closed trade, in exit order.

    Point zero is the starting equity so the curve has an origin to plot from.
    """
    ordered = sorted(trades, key=lambda t: (str(t.get("exit_date") or ""), str(t.get("trade_id") or "")))
    equity = float(starting_equity)
    peak = equity
    points = [{
        "index": 0, "date": None, "equity": round(equity, 2),
        "pnl": 0.0, "drawdown": 0.0, "peak": round(peak, 2),
    }]

    for i, trade in enumerate(ordered, start=1):
        pnl = float(trade.get("net_pnl") or 0.0)
        equity += pnl
        peak = max(peak, equity)
        points.append({
            "index": i,
            "date": _to_iso(trade.get("exit_date")) if trade.get("exit_date") else None,
            "equity": round(equity, 2),
            "pnl": round(pnl, 2),
            "drawdown": round(equity - peak, 2),
            "peak": round(peak, 2),
        })
    return points


def _max_drawdown(points: list[dict]) -> tuple[float, float | None]:
    """Largest peak-to-trough fall in absolute terms, and as a percent of peak."""
    worst = 0.0
    worst_pct: float | None = None
    for point in points:
        drop = point["drawdown"]
        if drop < worst:
            worst = drop
            peak = point["peak"]
            worst_pct = (drop / peak * 100) if peak else None
    return round(worst, 2), (round(worst_pct, 2) if worst_pct is not None else None)


def _streaks(trades: list[dict]) -> tuple[int, int]:
    longest_win = longest_loss = current_win = current_loss = 0
    for trade in trades:
        if float(trade.get("net_pnl") or 0.0) > 0:
            current_win += 1
            current_loss = 0
        else:
            current_loss += 1
            current_win = 0
        longest_win = max(longest_win, current_win)
        longest_loss = max(longest_loss, current_loss)
    return longest_win, longest_loss


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _holding_days(trade: dict) -> float | None:
    entry, exit_ = trade.get("entry_date"), trade.get("exit_date")
    if not entry or not exit_:
        return None
    try:
        d1 = date.fromisoformat(_to_iso(entry))
        d2 = date.fromisoformat(_to_iso(exit_))
        return (d2 - d1).days
    except (ValueError, TypeError):
        return None


def compute(trades: list[dict], starting_equity: float = 0.0) -> dict:
    """Full metric set for a run. Safe on an empty or single-trade run."""
    if not trades:
        return {
            "num_trades": 0,
            "reliable": False,
            "note": "No trades. Nothing to measure.",
        }

    ordered = sorted(trades, key=lambda t: (str(t.get("exit_date") or ""), str(t.get("trade_id") or "")))
    pnls = [float(t.get("net_pnl") or 0.0) for t in ordered]
    gross = [float(t.get("gross_pnl") or 0.0) for t in ordered]
    costs = [float(t.get("costs") or 0.0) for t in ordered]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    curve = equity_curve(ordered, starting_equity)
    max_dd, max_dd_pct = _max_drawdown(curve)
    longest_win_streak, longest_loss_streak = _streaks(ordered)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    win_rate = len(wins) / len(pnls)
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    sigma = _stdev(pnls)
    mean_pnl = sum(pnls) / len(pnls)
    downside = _stdev([p for p in pnls if p < 0]) if any(p < 0 for p in pnls) else 0.0

    # Annualisation factor from observed trade frequency, not an assumed one.
    holding = [d for d in (_holding_days(t) for t in ordered) if d is not None]
    avg_holding = (sum(holding) / len(holding)) if holding else None
    trades_per_year = (TRADING_DAYS_PER_YEAR / avg_holding) if avg_holding else None
    ann_factor = math.sqrt(trades_per_year) if trades_per_year else None

    sharpe = (mean_pnl / sigma * ann_factor) if (sigma > 0 and ann_factor) else None
    sortino = (mean_pnl / downside * ann_factor) if (downside > 0 and ann_factor) else None

    reliable = len(pnls) >= MIN_TRADES_FOR_RATIOS

    return {
        "num_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),

        "total_gross_pnl": round(sum(gross), 2),
        "total_costs": round(sum(costs), 2),
        "total_net_pnl": round(sum(pnls), 2),

        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,

        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_trade": round(mean_pnl, 2),
        "expectancy": round(expectancy, 2),
        "largest_win": round(max(pnls), 2),
        "largest_loss": round(min(pnls), 2),

        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "longest_win_streak": longest_win_streak,
        "longest_loss_streak": longest_loss_streak,

        "avg_holding_days": round(avg_holding, 1) if avg_holding is not None else None,
        "pnl_stdev": round(sigma, 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "sortino": round(sortino, 3) if sortino is not None else None,

        "reliable": reliable,
        "note": (
            None if reliable else
            f"Only {len(pnls)} trade(s). Ratios like Sharpe and profit factor are "
            f"not meaningful below {MIN_TRADES_FOR_RATIOS} trades — treat them as noise."
        ),
    }


def load_trades(conn, run_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT trade_id, symbol, strategy_side, entry_date, exit_date,
                  lot_size, lots, gross_pnl, costs, net_pnl, exit_reason
           FROM trades WHERE run_id = ? ORDER BY entry_date""",
        [run_id],
    ).fetchall()
    columns = ["trade_id", "symbol", "strategy_side", "entry_date", "exit_date",
               "lot_size", "lots", "gross_pnl", "costs", "net_pnl", "exit_reason"]
    return [dict(zip(columns, row)) for row in rows]
