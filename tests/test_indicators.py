"""Unit tests: small synthetic series, verifying mechanics only.
Not evidence of financial correctness (see GAP_ANALYSIS B2)."""
from server.indicators import sma, adx


def test_sma_basic():
    values = [1, 2, 3, 4, 5]
    out = sma(values, 3)
    assert out == [None, None, 2, 3, 4]


def test_sma_period_1_equals_input():
    values = [10, 20, 30]
    assert sma(values, 1) == [10, 20, 30]


def test_adx_returns_none_when_insufficient_bars():
    high = [10, 11, 12]
    low = [9, 10, 11]
    close = [9.5, 10.5, 11.5]
    out = adx(high, low, close, period=14)
    assert out == [None, None, None]


def test_adx_strong_uptrend_is_high():
    # Strictly increasing range each bar -> strongly directional -> ADX should be high once warmed up
    n = 40
    high = [100 + i * 2 for i in range(n)]
    low = [99 + i * 2 for i in range(n)]
    close = [99.5 + i * 2 for i in range(n)]
    out = adx(high, low, close, period=14)
    later_vals = [v for v in out[28:] if v is not None]
    assert later_vals, "expected ADX to warm up within 40 bars"
    assert all(v > 50 for v in later_vals)
