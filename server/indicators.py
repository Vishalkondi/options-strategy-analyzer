"""
Standard technical indicators (textbook formulas).

NOT YET RECONCILED against a client-validated indicator source
(GAP_ANALYSIS B2 — several defensible variants of ADX/RSI/etc. exist and
this module picks one). Treat as a reference implementation, not the
source of truth, until compared against real validated code/results.
"""
from __future__ import annotations


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        if i + 1 < period:
            continue
        window = values[i + 1 - period: i + 1]
        out[i] = sum(window) / period
    return out


def true_range(high: list[float], low: list[float], close: list[float]) -> list[float]:
    tr = [high[0] - low[0]]
    for i in range(1, len(high)):
        tr.append(max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        ))
    return tr


def adx(high: list[float], low: list[float], close: list[float], period: int = 14) -> list[float | None]:
    """Wilder's ADX. Returns None until enough bars accumulate (needs ~2*period)."""
    n = len(high)
    if n < period + 1:
        return [None] * n

    plus_dm = [0.0]
    minus_dm = [0.0]
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)

    tr = true_range(high, low, close)

    def wilder_smooth(series: list[float], period: int) -> list[float | None]:
        out: list[float | None] = [None] * len(series)
        if len(series) < period:
            return out
        first = sum(series[:period])
        out[period - 1] = first
        for i in range(period, len(series)):
            out[i] = out[i - 1] - (out[i - 1] / period) + series[i]
        return out

    tr_smooth = wilder_smooth(tr, period)
    plus_dm_smooth = wilder_smooth(plus_dm, period)
    minus_dm_smooth = wilder_smooth(minus_dm, period)

    dx: list[float | None] = [None] * n
    for i in range(n):
        if tr_smooth[i] in (None, 0) or plus_dm_smooth[i] is None or minus_dm_smooth[i] is None:
            continue
        plus_di = 100 * (plus_dm_smooth[i] / tr_smooth[i])
        minus_di = 100 * (minus_dm_smooth[i] / tr_smooth[i])
        denom = plus_di + minus_di
        dx[i] = 100 * abs(plus_di - minus_di) / denom if denom else 0.0

    out: list[float | None] = [None] * n
    valid_dx = [v for v in dx if v is not None]
    start = next((i for i, v in enumerate(dx) if v is not None), None)
    if start is None or len(dx) - start < period:
        return out
    first_adx = sum(dx[start:start + period]) / period  # type: ignore[arg-type]
    adx_index = start + period - 1
    out[adx_index] = first_adx
    for i in range(adx_index + 1, n):
        if dx[i] is None:
            continue
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period  # type: ignore[operator]
    return out
