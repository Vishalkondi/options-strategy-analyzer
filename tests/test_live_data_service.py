"""
Unit tests for server/live_data_service.py's BarBuilder -- the tick -> 1-minute
OHLCV resampling logic. Pure in-memory, no Kite connection needed.
"""
from __future__ import annotations

import datetime

from server.live_data_service import BarBuilder


def test_ticks_within_same_minute_build_one_bar():
    b = BarBuilder("TESTCO")
    t0 = datetime.datetime(2026, 1, 1, 9, 15, 0)
    assert b.add_tick(100.0, 10, t0) is None
    assert b.add_tick(101.0, 5, t0 + datetime.timedelta(seconds=20)) is None
    assert b.add_tick(99.5, 7, t0 + datetime.timedelta(seconds=40)) is None
    assert b.history == []
    assert b._current["open"] == 100.0
    assert b._current["high"] == 101.0
    assert b._current["low"] == 99.5
    assert b._current["close"] == 99.5
    assert b._current["volume"] == 22


def test_tick_in_next_minute_finishes_previous_bar():
    b = BarBuilder("TESTCO")
    t0 = datetime.datetime(2026, 1, 1, 9, 15, 0)
    b.add_tick(100.0, 10, t0)
    b.add_tick(102.0, 5, t0 + datetime.timedelta(seconds=30))
    finished = b.add_tick(103.0, 8, t0 + datetime.timedelta(minutes=1, seconds=1))
    assert finished is not None
    assert finished["open"] == 100.0
    assert finished["high"] == 102.0
    assert finished["low"] == 100.0
    assert finished["close"] == 102.0
    assert finished["volume"] == 15
    assert b.history == [finished]
    assert b._current["open"] == 103.0


def test_warm_start_bars_are_seeded_into_history():
    warm = [{"ts": "2025-12-31", "open": 90, "high": 91, "low": 89, "close": 90.5, "volume": 100}]
    b = BarBuilder("TESTCO", warm_start_bars=warm)
    assert b.history == warm
    t0 = datetime.datetime(2026, 1, 1, 9, 15, 0)
    b.add_tick(100.0, 10, t0)
    finished = b.add_tick(101.0, 5, t0 + datetime.timedelta(minutes=1))
    assert b.history == [warm[0], finished]
