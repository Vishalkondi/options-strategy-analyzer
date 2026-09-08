"""
Directional Call/Put Debit Spread — REFERENCE IMPLEMENTATION.

This is Vishal's own reference build, not validated client-supplied source
(GAP_ANALYSIS B1 is still open). It exists so the engine has something
real to run end-to-end against the demo fixtures. Before trusting any
result: reconcile entry/exit logic, strike selection, and P&L formulas
against your actual validated strategy code.

Entry logic:
  - SMA(fast) vs SMA(slow) crossover on daily close, gated by ADX(period) > adx_threshold
  - SMA_fast > SMA_slow  -> Bull Call Debit Spread (buy ATM CE, sell OTM CE)
  - SMA_fast < SMA_slow  -> Bear Put Debit Spread  (buy ATM PE, sell OTM PE)
  - One position open at a time per symbol

Exit logic (first one hit):
  - take_profit_pct on spread value
  - stop_loss_pct on spread value
  - expiry date reached
  - end of available data (demo-data limitation, not a real exit rule)

Position sizing: fixed 1 lot. Real lot size is unresolved (GAP_ANALYSIS B6);
`lot_size` param defaults to 1 as an explicit placeholder, not a real NSE lot size.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from server.indicators import adx, sma


@dataclass
class Signal:
    trading_date: str
    direction: str  # 'bull' | 'bear'


@dataclass
class StrategyParams:
    sma_fast: int = 5
    sma_slow: int = 20
    adx_period: int = 14
    adx_threshold: float = 20.0
    otm_offset_strikes: int = 2   # how many strike-steps OTM the short leg sits
    take_profit_pct: float = 0.5  # close spread at 50% of max theoretical gain estimate proxy (spread value move)
    stop_loss_pct: float = 0.5
    lot_size: int = 1
    lots: int = 1


def _signal_for_bar(
    i: int, fast: list[float | None], slow: list[float | None], adx_vals: list[float | None],
    adx_threshold: float, raw_state: str | None, last_signaled_state: str | None,
) -> tuple[str | None, str | None]:
    """
    The single entry-rule check, evaluated for one bar index. Both the
    batch backtest loop (generate_signals) and the live incremental path
    (evaluate_latest_bar) call this exact function -- there is no second
    copy of the crossover/ADX-gate logic anywhere.

    Returns (updated_raw_state, fired_direction_or_None).
    """
    f, s, a = fast[i], slow[i], adx_vals[i]
    if f is None or s is None:
        return raw_state, None
    if f > s:
        raw_state = "bull"
    elif f < s:
        raw_state = "bear"
    # if f == s, raw_state carries over unchanged

    trending = a is not None and a > adx_threshold
    if trending and raw_state is not None and raw_state != last_signaled_state:
        return raw_state, raw_state
    return raw_state, None


def generate_signals(dates: list[str], close: list[float], high: list[float],
                      low: list[float], params: StrategyParams) -> list[Signal]:
    """
    Tracks the raw SMA-crossover regime independently of ADX availability,
    and fires a signal the first time ADX confirms trend strength for a
    regime that hasn't already been signaled — rather than requiring the
    crossover and the ADX threshold to land on the exact same bar (which
    misses regimes that started before ADX finished warming up).
    """
    fast = sma(close, params.sma_fast)
    slow = sma(close, params.sma_slow)
    adx_vals = adx(high, low, close, params.adx_period)

    signals: list[Signal] = []
    raw_state: str | None = None
    last_signaled_state: str | None = None
    for i in range(len(dates)):
        raw_state, fired = _signal_for_bar(i, fast, slow, adx_vals, params.adx_threshold,
                                            raw_state, last_signaled_state)
        if fired:
            signals.append(Signal(trading_date=dates[i], direction=fired))
            last_signaled_state = fired
    return signals


def evaluate_latest_bar(
    dates: list[str], close: list[float], high: list[float], low: list[float],
    params: StrategyParams, raw_state: str | None, last_signaled_state: str | None,
) -> tuple[str | None, str | None]:
    """
    Live-mode entry point. Recomputes indicators over the full bar history
    supplied (oldest -> newest, most recent bar last) and checks only that
    last bar via the exact same _signal_for_bar the backtest loop uses.

    Recomputing indicators over the whole history on every new bar is
    intentional, not an optimization shortcut: it guarantees the live
    ADX/SMA values are bit-for-bit what the backtest would have computed
    over the same series, which is what "same strategy engine" requires.
    For a single-user tool with bar histories in the hundreds, this is
    cheap. Returns (updated_raw_state, fired_direction_or_None).
    """
    fast = sma(close, params.sma_fast)
    slow = sma(close, params.sma_slow)
    adx_vals = adx(high, low, close, params.adx_period)
    i = len(dates) - 1
    return _signal_for_bar(i, fast, slow, adx_vals, params.adx_threshold, raw_state, last_signaled_state)


def nearest_strike(spot: float, strikes: list[float]) -> float:
    return min(strikes, key=lambda k: abs(k - spot))


def pick_legs(direction: str, spot: float, strikes_sorted: list[float], otm_offset: int) -> tuple[float, float, str]:
    """Returns (buy_strike, sell_strike, option_type)."""
    atm = nearest_strike(spot, strikes_sorted)
    atm_idx = strikes_sorted.index(atm)
    if direction == "bull":
        sell_idx = min(atm_idx + otm_offset, len(strikes_sorted) - 1)
        return atm, strikes_sorted[sell_idx], "CE"
    else:
        sell_idx = max(atm_idx - otm_offset, 0)
        return atm, strikes_sorted[sell_idx], "PE"
