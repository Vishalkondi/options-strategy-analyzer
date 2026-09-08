"""
Scheduler tests.

The behaviours that matter most here are the negative ones: that a cycle with
no credentials FAILS and is recorded as failed rather than inventing prices,
and that a failing cycle never stops the loop.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from server import capture as capture_module
from server import kite_client
from server import scheduler as scheduler_module
from server.database import reset_database_for_tests
from server.scheduler import CaptureScheduler, market_is_open


@pytest.fixture
def env(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(scheduler_module, "get_database", lambda: conn)
    monkeypatch.setattr(capture_module, "get_database", lambda: conn)
    monkeypatch.setattr(scheduler_module.settings, "SCHEDULER_SYMBOLS", ["RELIANCE"])
    monkeypatch.setattr(scheduler_module.settings, "SCHEDULER_MAX_RETRIES", 2)
    monkeypatch.setattr(scheduler_module.settings, "SCHEDULER_RETRY_BACKOFF", 0.01)
    return conn


def _quote(price=2900.0):
    return {"NSE:RELIANCE": {
        "instrument_token": 738561, "last_price": price, "last_quantity": 25,
        "volume": 1_000_000, "average_price": price - 1,
        "last_trade_time": datetime(2026, 9, 7, 10, 30, 0),
        "ohlc": {"open": 2880.0, "high": 2950.0, "low": 2870.0, "close": 2890.0},
        "oi": 10500, "buy_quantity": 500, "sell_quantity": 450,
        "depth": {"buy": [{"price": price - 0.5, "quantity": 100}],
                  "sell": [{"price": price + 0.5, "quantity": 120}]},
    }}


# ---------------------------------------------------------------------------
# The honest-failure requirement
# ---------------------------------------------------------------------------

def test_missing_credentials_produce_a_failed_cycle_not_fake_data(env, monkeypatch):
    """
    The single most important test here. With no Kite credentials the cycle
    must record FAILED and write no market rows -- never substitute simulated
    prices, which would be indistinguishable from real ones later.
    """
    conn = env

    def no_creds(_keys):
        raise kite_client.KiteConfigError("OA_KITE_API_KEY is still the placeholder value")

    monkeypatch.setattr(scheduler_module.kite_client, "quote", no_creds)
    result = asyncio.run(CaptureScheduler().run_cycle(trigger="manual"))

    assert result["status"] == "FAILED"
    assert "placeholder" in result["error"]
    assert result["total_records"] == 0
    assert conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM live_market_data").fetchone()[0] == 0

    row = conn.execute("SELECT status, error FROM capture_cycles").fetchone()
    assert row[0] == "FAILED"
    assert row[1], "a failed cycle must record why"


def test_expired_token_fails_the_cycle_and_is_not_retried(env, monkeypatch):
    calls = {"n": 0}

    def expired(_keys):
        calls["n"] += 1
        raise kite_client.KiteAuthError("token expired")

    monkeypatch.setattr(scheduler_module.kite_client, "quote", expired)
    result = asyncio.run(CaptureScheduler().run_cycle())

    assert result["status"] == "FAILED"
    assert calls["n"] == 1, "auth errors will not fix themselves; retrying only delays the truth"


# ---------------------------------------------------------------------------
# Successful cycles
# ---------------------------------------------------------------------------

def test_successful_cycle_writes_records_and_audits_itself(env, monkeypatch):
    conn = env
    monkeypatch.setattr(scheduler_module.kite_client, "quote", lambda keys: _quote())

    result = asyncio.run(CaptureScheduler().run_cycle(trigger="manual"))

    assert result["status"] == "SUCCESS"
    assert result["symbols_captured"] == 1
    assert result["total_records"] > 0
    assert result["cycle_id"]                       # unique identifier per cycle
    assert result["started_at"] and result["finished_at"]

    assert conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM live_market_data").fetchone()[0] == 1

    cycle = conn.execute(
        """SELECT cycle_number, status, ticks_inserted, bars_inserted,
                  total_records, duration_ms, trigger
           FROM capture_cycles"""
    ).fetchone()
    assert cycle[1] == "SUCCESS"
    assert cycle[2] == 1 and cycle[3] == 1
    assert cycle[4] > 0
    assert cycle[5] is not None
    assert cycle[6] == "manual"


def test_each_cycle_gets_a_unique_id_and_an_incrementing_number(env, monkeypatch):
    conn = env
    monkeypatch.setattr(scheduler_module.kite_client, "quote", lambda keys: _quote())
    scheduler = CaptureScheduler()

    first = asyncio.run(scheduler.run_cycle())
    second = asyncio.run(scheduler.run_cycle())

    assert first["cycle_id"] != second["cycle_id"]
    assert second["cycle_number"] == first["cycle_number"] + 1
    assert conn.execute("SELECT COUNT(*) FROM capture_cycles").fetchone()[0] == 2


def test_history_is_never_overwritten(env, monkeypatch):
    """Requirement 7: every cycle appends; earlier cycles stay untouched."""
    conn = env
    monkeypatch.setattr(scheduler_module.kite_client, "quote", lambda keys: _quote())
    scheduler = CaptureScheduler()
    for _ in range(3):
        asyncio.run(scheduler.run_cycle())

    rows = conn.execute(
        "SELECT cycle_number, status FROM capture_cycles ORDER BY cycle_number"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2, 3]
    assert all(r[1] in ("SUCCESS", "PARTIAL") for r in rows)


def test_repeat_capture_of_the_same_minute_does_not_duplicate_rows(env, monkeypatch):
    """Requirement 8: dedupe is enforced by the database keys, not by luck."""
    conn = env
    monkeypatch.setattr(scheduler_module.kite_client, "quote", lambda keys: _quote())
    scheduler = CaptureScheduler()

    asyncio.run(scheduler.run_cycle())
    asyncio.run(scheduler.run_cycle())   # identical quote, same timestamp

    assert conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM live_market_data").fetchone()[0] == 1
    # Both cycles are still recorded, even though the second inserted nothing.
    assert conn.execute("SELECT COUNT(*) FROM capture_cycles").fetchone()[0] == 2
    second = conn.execute(
        "SELECT total_records FROM capture_cycles ORDER BY cycle_number DESC LIMIT 1"
    ).fetchone()[0]
    assert second == 0, "a duplicate capture should honestly report zero new rows"


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

def test_transient_failure_is_retried_then_succeeds(env, monkeypatch):
    attempts = {"n": 0}

    def flaky(keys):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise kite_client.KiteUpstreamError("connection reset")
        return _quote()

    monkeypatch.setattr(scheduler_module.kite_client, "quote", flaky)
    result = asyncio.run(CaptureScheduler().run_cycle())

    assert result["status"] == "SUCCESS"
    assert result["attempts"] == 2


def test_retries_are_exhausted_then_the_cycle_fails(env, monkeypatch):
    def always_down(keys):
        raise kite_client.KiteUpstreamError("Zerodha unreachable")

    monkeypatch.setattr(scheduler_module.kite_client, "quote", always_down)
    result = asyncio.run(CaptureScheduler().run_cycle())

    assert result["status"] == "FAILED"
    assert "unreachable" in result["error"]


def test_one_bad_symbol_does_not_fail_the_whole_cycle(env, monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "SCHEDULER_SYMBOLS", ["RELIANCE", "MISSINGCO"])
    monkeypatch.setattr(scheduler_module.kite_client, "quote", lambda keys: _quote())

    result = asyncio.run(CaptureScheduler().run_cycle())
    assert result["status"] == "PARTIAL"
    assert result["symbols_requested"] == 2
    assert result["symbols_captured"] == 1


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def test_loop_survives_a_cycle_that_raises(env, monkeypatch):
    """A single bad cycle must not end the scheduler for the whole process."""
    calls = {"n": 0}

    async def exploding_cycle(trigger="scheduler", scheduled_at=None):
        calls["n"] += 1
        raise RuntimeError("catastrophic cycle failure")

    monkeypatch.setattr(scheduler_module.settings, "SCHEDULER_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(scheduler_module.settings, "SCHEDULER_RUN_ON_STARTUP", False)

    scheduler = CaptureScheduler()
    scheduler.run_cycle = exploding_cycle

    async def run():
        scheduler.start()
        await asyncio.sleep(0.3)
        await scheduler.stop()

    asyncio.run(run())
    assert calls["n"] >= 2, "the loop must keep scheduling after a cycle raises"


def test_scheduler_can_be_disabled(env, monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "SCHEDULER_ENABLED", False)
    scheduler = CaptureScheduler()

    async def run():
        started = scheduler.start()
        await scheduler.stop()
        return started

    assert asyncio.run(run()) is False


def test_status_summarises_success_and_failure_counts(env, monkeypatch):
    conn = env
    calls = {"n": 0}

    def alternating(keys):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise kite_client.KiteConfigError("no key")
        return _quote(2900.0 + calls["n"])

    monkeypatch.setattr(scheduler_module.kite_client, "quote", alternating)
    scheduler = CaptureScheduler()
    for _ in range(4):
        asyncio.run(scheduler.run_cycle())

    status = scheduler.status(conn=conn)
    assert status["cycles_total"] == 4
    assert status["cycles_succeeded"] == 2
    assert status["cycles_failed"] == 2
    assert status["last_cycle"] is not None
    assert status["interval_minutes"] > 0


def test_history_returns_cycles_newest_first(env, monkeypatch):
    conn = env
    monkeypatch.setattr(scheduler_module.kite_client, "quote", lambda keys: _quote())
    scheduler = CaptureScheduler()
    for _ in range(3):
        asyncio.run(scheduler.run_cycle())

    history = scheduler.history(conn=conn)
    assert len(history) == 3
    assert history[0]["cycle_number"] == 3
    assert "ticks_inserted" in history[0]


# ---------------------------------------------------------------------------
# Market hours
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.mark.parametrize("when,expected", [
    (datetime(2026, 9, 7, 10, 30, tzinfo=IST), True),    # Monday mid-session
    (datetime(2026, 9, 7, 9, 15, tzinfo=IST), True),     # open
    (datetime(2026, 9, 7, 15, 30, tzinfo=IST), True),    # close
    (datetime(2026, 9, 7, 8, 0, tzinfo=IST), False),     # pre-open
    (datetime(2026, 9, 7, 16, 0, tzinfo=IST), False),    # after hours
    (datetime(2026, 9, 5, 11, 0, tzinfo=IST), False),    # Saturday
    (datetime(2026, 9, 6, 11, 0, tzinfo=IST), False),    # Sunday
])
def test_market_hours(when, expected):
    assert market_is_open(when) is expected


def test_cycle_records_whether_the_market_was_open(env, monkeypatch):
    conn = env
    monkeypatch.setattr(scheduler_module.kite_client, "quote", lambda keys: _quote())
    asyncio.run(CaptureScheduler().run_cycle())
    assert conn.execute("SELECT market_open FROM capture_cycles").fetchone()[0] is not None
