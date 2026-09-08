"""
Tests for market replay.

Replay's whole purpose is to exercise the real live path without Zerodha, so
these tests assert two things: that the pipeline genuinely runs end to end, and
that replayed data is never labelled as a live feed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from server import live_service as live_service_module
from server import replay as replay_module
from server import signals
from server.database import reset_database_for_tests
from server.main import app
from server.replay import ReplayService


# ADX needs roughly 2 x adx_period bars (default 14) before it produces a
# value at all, so a 25-bar fixture can never fire the default strategy.
def _seed_bars(conn, symbol="TESTCO", n=60, start=100.0):
    base = datetime(2026, 5, 1)
    for i in range(n):
        close = start + i * 1.5
        conn.execute(
            """INSERT INTO equity_bars (symbol, trading_date, timestamp, bar_interval,
               open, high, low, close, volume)
               VALUES (?, ?, ?, '1d', ?, ?, ?, ?, ?)""",
            [symbol, (base + timedelta(days=i)).date(), base + timedelta(days=i),
             close - 0.5, close + 1.0, close - 1.0, close, 1000 + i],
        )


@pytest.fixture
def replay_env(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(replay_module, "get_database", lambda: conn)
    monkeypatch.setattr(live_service_module, "get_database", lambda: conn)
    monkeypatch.setattr(signals, "get_database", lambda: conn)
    _seed_bars(conn)
    return conn


def test_replay_streams_bars_into_the_live_pipeline(replay_env):
    conn = replay_env
    service = ReplayService()

    async def run():
        await service.start("TESTCO", "directional_debit_spread.yaml", speed=1000.0)
        for _ in range(400):
            await asyncio.sleep(0.01)
            if not service.running:
                break
        await service.stop()

    asyncio.run(run())

    assert service.bars_sent == 60
    rows = conn.execute(
        "SELECT COUNT(*), MIN(source) FROM live_market_data WHERE symbol='TESTCO'"
    ).fetchone()
    assert rows[0] == 60, "every replayed bar should be persisted"
    assert rows[1].startswith("replay-"), "replayed rows must be tagged as replay"


def test_replay_produces_paper_trades_through_the_real_strategy(replay_env):
    """A steadily rising series should trip the strategy and open a paper trade."""
    conn = replay_env
    service = ReplayService()

    async def run():
        await service.start("TESTCO", "directional_debit_spread.yaml", speed=1000.0)
        for _ in range(400):
            await asyncio.sleep(0.01)
            if not service.running:
                break
        await service.stop()

    asyncio.run(run())

    trades = conn.execute("SELECT watch_symbol, side FROM paper_trades").fetchall()
    assert trades, "the replay should have generated at least one paper trade"
    assert trades[0][0] == "TESTCO"


def test_replay_broadcasts_ticks_to_dashboard_clients(replay_env, monkeypatch):
    received: list[dict] = []

    async def capture(message):
        received.append(message)

    monkeypatch.setattr(live_service_module.live_service, "broadcast_event", capture)
    service = ReplayService()

    async def run():
        await service.start("TESTCO", "directional_debit_spread.yaml", speed=1000.0)
        for _ in range(400):
            await asyncio.sleep(0.01)
            if not service.running:
                break
        await service.stop()

    asyncio.run(run())

    ticks = [m for m in received if m.get("type") == "market_tick"]
    assert len(ticks) == 60
    entries = [m for m in received if m.get("action") == "ENTRY"]
    assert entries, "signal events must reach the dashboard socket, not only the relay"


def test_two_replays_cannot_run_at_once(replay_env):
    service = ReplayService()

    async def run():
        await service.start("TESTCO", "directional_debit_spread.yaml", speed=2.0)
        try:
            with pytest.raises(ValueError, match="already running"):
                await service.start("TESTCO", "directional_debit_spread.yaml", speed=2.0)
        finally:
            await service.stop()

    asyncio.run(run())


def test_replay_rejects_a_symbol_with_no_stored_data(replay_env):
    service = ReplayService()
    with pytest.raises(ValueError, match="No stored bars"):
        asyncio.run(service.start("NOSUCHCO", "directional_debit_spread.yaml"))


def test_replay_rejects_an_unknown_strategy(replay_env):
    service = ReplayService()
    with pytest.raises(ValueError, match="Strategy file not found"):
        asyncio.run(service.start("TESTCO", "no_such_strategy.yaml"))


def test_stop_is_safe_when_nothing_is_running(replay_env):
    service = ReplayService()
    status = asyncio.run(service.stop())
    assert status["running"] is False


# --- API surface -----------------------------------------------------------

client = TestClient(app)


def test_replay_status_endpoint_is_available():
    body = client.get("/api/live/replay/status").json()
    assert body["running"] is False
    assert "bars_sent" in body


def test_replay_start_reports_a_missing_symbol_clearly():
    response = client.post("/api/live/replay/start", json={"symbol": "NOSUCHCO"})
    assert response.status_code == 400
    assert "no stored bars" in response.json()["detail"].lower()


def test_live_status_exposes_replay_state():
    body = client.get("/api/live/status").json()
    assert "replay" in body
    assert body["replay"]["running"] is False


def test_dashboard_labels_replay_prices_as_replay(monkeypatch):
    """The snapshot must say 'replay', never 'kite', while a replay is running."""
    from server.live_market import live_market_service
    from server.replay import replay_service

    monkeypatch.setattr(type(replay_service), "running", property(lambda self: True))
    monkeypatch.setattr(replay_service, "symbol", "TESTCO", raising=False)
    monkeypatch.setitem(replay_module.last_prices, "TESTCO", {
        "price": 123.45, "open": 120.0, "high": 124.0, "low": 119.0,
        "volume": 500, "timestamp": "2026-05-01T00:00:00",
    })
    live_market_service._cache = None

    body = client.get("/api/live/market").json()
    assert body["source"] == "replay"
    assert "not a live feed" in body["source_detail"]
    assert body["symbols"]["TESTCO"]["source"] == "replay"
    assert body["symbols"]["TESTCO"]["price"] == 123.45
    live_market_service._cache = None
