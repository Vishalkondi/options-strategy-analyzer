"""
Unit tests for server/signals.py -- the live incremental signal path.

These do NOT touch Kite. They call on_new_bar() directly with synthetic
in-memory bar histories, the same way test_engine.py drives run_backtest()
with synthetic equity_bars. The point is to prove the live wiring (entry
fires, exit fires, paper_trades gets written, no duplicate positions)
before it is ever connected to a real tick stream -- catching exactly the
kind of bug (e.g. the int/float param issue found earlier) that only shows
up when the code actually runs.
"""
from __future__ import annotations

import asyncio
import datetime

import pytest

from server.database import reset_database_for_tests
from server import signals


DEFAULT_PARAMS = {
    "sma_fast": 5, "sma_slow": 20, "adx_period": 14, "adx_threshold": 20,
    "otm_offset_strikes": 2, "take_profit_pct": 0.05, "stop_loss_pct": 0.05,
    "lot_size": 1, "lots": 1,
}


def _new_watch(symbol="TESTCO", strategy_id="directional_debit_spread", params=None) -> dict:
    return {
        "symbol": symbol, "strategy_id": strategy_id, "strategy_version": 1,
        "params": params or dict(DEFAULT_PARAMS),
        "raw_state": None, "last_signaled_state": None,
        "open_trade_id": None, "entry_price": None, "open_side": None,
    }


def _trending_bars(n=40, start_price=1000.0, step=3.0) -> list[dict]:
    """Steady uptrend bars -- same shape test_engine.py uses to reliably
    warm up SMA(5)/SMA(20) and push ADX(14) past a 20 threshold."""
    bars = []
    ts = datetime.datetime(2026, 1, 1, 9, 15)
    price = start_price
    for i in range(n):
        price += step
        bars.append({
            "ts": ts + datetime.timedelta(minutes=i),
            "open": price - 1, "high": price + 2, "low": price - 2,
            "close": price, "volume": 1000,
        })
    return bars


def _run(coro):
    return asyncio.run(coro)


def test_no_signal_on_insufficient_history():
    """Fewer bars than the slow SMA period -> no entry, no crash."""
    conn = reset_database_for_tests()
    watch = _new_watch()
    bars = _trending_bars(n=10)  # < sma_slow=20
    for i in range(1, len(bars) + 1):
        _run(signals.on_new_bar(watch, bars[:i], conn=conn))
    assert watch["open_trade_id"] is None
    count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
    assert count == 0


def test_entry_fires_on_confirmed_uptrend():
    """A steady, ADX-confirmed uptrend should eventually fire a bull entry
    and write exactly one OPEN paper_trades row -- using evaluate_latest_bar,
    the same function generate_signals() uses for backtests."""
    conn = reset_database_for_tests()
    watch = _new_watch()
    bars = _trending_bars(n=40)

    for i in range(1, len(bars) + 1):
        _run(signals.on_new_bar(watch, bars[:i], conn=conn))

    assert watch["open_trade_id"] is not None
    assert watch["open_side"] == "bull"

    rows = conn.execute(
        "SELECT status, side, watch_symbol, strategy_id FROM paper_trades"
    ).fetchall()
    assert len(rows) == 1
    status, side, symbol, strategy_id = rows[0]
    assert status == "OPEN"
    assert side == "bull"
    assert symbol == "TESTCO"
    assert strategy_id == "directional_debit_spread"


def test_no_duplicate_entry_while_position_open():
    """Once a position is open, further bars in the same direction must
    NOT open a second paper trade."""
    conn = reset_database_for_tests()
    watch = _new_watch()
    bars = _trending_bars(n=50)

    for i in range(1, len(bars) + 1):
        _run(signals.on_new_bar(watch, bars[:i], conn=conn))

    count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
    assert count == 1  # not one per bar after entry


def test_exit_fires_at_take_profit():
    """After entry, a big enough further move in the same direction should
    close the position with exit_reason='target' and a positive net_pnl."""
    conn = reset_database_for_tests()
    watch = _new_watch(params={**DEFAULT_PARAMS, "take_profit_pct": 0.02, "stop_loss_pct": 0.5})
    bars = _trending_bars(n=60, step=3.0)  # entry fires ~bar 27; leaves room for a 2% move after

    for i in range(1, len(bars) + 1):
        _run(signals.on_new_bar(watch, bars[:i], conn=conn))
        if watch["open_trade_id"] is not None:
            break
    assert watch["open_trade_id"] is not None, "entry never fired -- test setup problem, not exit logic"

    # Keep feeding bars until the 2% take-profit is hit.
    for i in range(i + 1, len(bars) + 1):
        _run(signals.on_new_bar(watch, bars[:i], conn=conn))
        if watch["open_trade_id"] is None:
            break

    assert watch["open_trade_id"] is None, "position never closed within the synthetic uptrend"
    row = conn.execute(
        "SELECT exit_reason, net_pnl, status FROM paper_trades ORDER BY entry_ts DESC LIMIT 1"
    ).fetchone()
    exit_reason, net_pnl, status = row
    assert exit_reason == "target"
    assert status == "CLOSED"
    assert net_pnl > 0


def test_exit_fires_at_stop_loss():
    """A bull entry followed by a price reversal past stop_loss_pct should
    close with exit_reason='stop' and a negative net_pnl."""
    conn = reset_database_for_tests()
    watch = _new_watch(params={**DEFAULT_PARAMS, "take_profit_pct": 0.5, "stop_loss_pct": 0.02})
    up_bars = _trending_bars(n=35, step=3.0)  # entry fires ~bar 27

    i = 0
    for i in range(1, len(up_bars) + 1):
        _run(signals.on_new_bar(watch, up_bars[:i], conn=conn))
        if watch["open_trade_id"] is not None:
            break
    assert watch["open_trade_id"] is not None, "entry never fired -- test setup problem, not exit logic"

    entry_price = watch["entry_price"]
    last_ts = up_bars[i - 1]["ts"]
    # Feed a sharp reversal until the 2% stop is breached.
    reversal = []
    price = entry_price
    for j in range(20):
        price -= entry_price * 0.01  # -1%/bar
        reversal.append({
            "ts": last_ts + datetime.timedelta(minutes=j + 1),
            "open": price + 1, "high": price + 2, "low": price - 2,
            "close": price, "volume": 1000,
        })

    history = up_bars[:i]
    for bar in reversal:
        history = history + [bar]
        _run(signals.on_new_bar(watch, history, conn=conn))
        if watch["open_trade_id"] is None:
            break

    assert watch["open_trade_id"] is None, "position never closed within the synthetic reversal"
    row = conn.execute(
        "SELECT exit_reason, net_pnl, status FROM paper_trades ORDER BY entry_ts DESC LIMIT 1"
    ).fetchone()
    exit_reason, net_pnl, status = row
    assert exit_reason == "stop"
    assert status == "CLOSED"
    assert net_pnl < 0


def test_load_warm_start_bars_handles_missing_data_gracefully():
    """No equity_bars for the symbol -> empty list, not an exception."""
    conn = reset_database_for_tests()
    import server.database as db_module
    original = db_module._conn
    db_module._conn = conn
    try:
        bars = signals.load_warm_start_bars("NOSUCHSYMBOL")
    finally:
        db_module._conn = original
    assert bars == []
