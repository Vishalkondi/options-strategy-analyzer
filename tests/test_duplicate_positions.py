"""
Regression: restarting a replay (or re-registering a watch) must not open a
second position on top of one that is already OPEN.

The bug: the in-memory watch dict is rebuilt on every start with
open_trade_id=None, so the "is a position already open?" check consulted
process memory that had just been wiped. Three replay runs produced three
identical OPEN rows at the same entry price.

The fix: the database is the source of truth for what is open.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from server import live_service as live_service_module
from server import replay as replay_module
from server import signals
from server.database import reset_database_for_tests
from server.replay import ReplayService


def _seed_rising_bars(conn, symbol="TESTCO", n=60):
    base = datetime(2026, 5, 1)
    for i in range(n):
        close = 100.0 + i * 1.5
        conn.execute(
            """INSERT INTO equity_bars (symbol, trading_date, timestamp, bar_interval,
               open, high, low, close, volume)
               VALUES (?, ?, ?, '1d', ?, ?, ?, ?, ?)""",
            [symbol, (base + timedelta(days=i)).date(), base + timedelta(days=i),
             close - 0.5, close + 1.0, close - 1.0, close, 1000],
        )


@pytest.fixture
def env(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(replay_module, "get_database", lambda: conn)
    monkeypatch.setattr(live_service_module, "get_database", lambda: conn)
    monkeypatch.setattr(signals, "get_database", lambda: conn)
    _seed_rising_bars(conn)
    return conn


async def _run_replay_to_completion(service, symbol="TESTCO"):
    await service.start(symbol, "directional_debit_spread.yaml", speed=1000.0)
    for _ in range(400):
        await asyncio.sleep(0.01)
        if not service.running:
            break
    await service.stop()


def test_restarting_a_replay_does_not_duplicate_an_open_position(env):
    conn = env

    async def run():
        for _ in range(3):
            await _run_replay_to_completion(ReplayService())

    asyncio.run(run())

    open_rows = conn.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN'"
    ).fetchone()[0]
    assert open_rows <= 1, f"three replay runs left {open_rows} open positions; expected at most 1"


def test_adopt_open_trade_reattaches_a_fresh_watch(env):
    conn = env
    conn.execute(
        """INSERT INTO paper_trades
           (paper_trade_id, watch_symbol, strategy_id, side, entry_ts, entry_price, status)
           VALUES ('trade-1', 'TESTCO', 'directional_debit_spread', 'bull', ?, 150.0, 'OPEN')""",
        [datetime(2026, 5, 10)],
    )
    watch = {
        "symbol": "TESTCO", "strategy_id": "directional_debit_spread",
        "strategy_version": 1, "params": {},
        "raw_state": None, "last_signaled_state": None,
        "open_trade_id": None, "entry_price": None, "open_side": None,
    }
    signals.adopt_open_trade(watch, conn=conn)

    assert watch["open_trade_id"] == "trade-1"
    assert watch["entry_price"] == 150.0
    assert watch["open_side"] == "bull"


def test_adopt_ignores_closed_positions(env):
    conn = env
    conn.execute(
        """INSERT INTO paper_trades
           (paper_trade_id, watch_symbol, strategy_id, side, entry_ts, entry_price, status)
           VALUES ('trade-closed', 'TESTCO', 'directional_debit_spread', 'bull', ?, 150.0, 'CLOSED')""",
        [datetime(2026, 5, 10)],
    )
    watch = {
        "symbol": "TESTCO", "strategy_id": "directional_debit_spread",
        "strategy_version": 1, "params": {},
        "raw_state": None, "last_signaled_state": None,
        "open_trade_id": None, "entry_price": None, "open_side": None,
    }
    signals.adopt_open_trade(watch, conn=conn)
    assert watch["open_trade_id"] is None


def test_adopt_is_scoped_to_the_symbol_and_strategy(env):
    conn = env
    conn.execute(
        """INSERT INTO paper_trades
           (paper_trade_id, watch_symbol, strategy_id, side, entry_ts, entry_price, status)
           VALUES ('other', 'OTHERCO', 'directional_debit_spread', 'bull', ?, 150.0, 'OPEN')""",
        [datetime(2026, 5, 10)],
    )
    watch = {
        "symbol": "TESTCO", "strategy_id": "directional_debit_spread",
        "strategy_version": 1, "params": {},
        "raw_state": None, "last_signaled_state": None,
        "open_trade_id": None, "entry_price": None, "open_side": None,
    }
    signals.adopt_open_trade(watch, conn=conn)
    assert watch["open_trade_id"] is None, "another symbol's position must not be adopted"
