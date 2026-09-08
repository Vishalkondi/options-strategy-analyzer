"""
End-to-end live path, driven by a fake Kite feed.

Real Zerodha credentials can't be exercised in CI, but the whole chain after
the socket can: tick -> 1-minute bar -> strategy evaluation -> paper trade row
-> websocket broadcast. If this passes, the only thing standing between the
backend and real live data is a valid API key.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from server import signals, ws_relay
from server.database import reset_database_for_tests
from server.live_data_service import LiveDataService


class FakeTicker:
    """Stands in for KiteTicker: records subscriptions, replays ticks."""

    MODE_FULL = "full"

    def __init__(self, api_key, access_token):
        self.api_key = api_key
        self.access_token = access_token
        self.subscribed: list[int] = []
        self.modes: list[tuple] = []
        self.connected = False
        self.closed = False
        self.on_ticks = self.on_connect = self.on_close = None
        self.on_error = self.on_reconnect = self.on_noreconnect = None

    def connect(self, threaded=False):
        self.connected = True
        if self.on_connect:
            self.on_connect(self, {})

    def is_connected(self):
        return self.connected

    def subscribe(self, tokens):
        self.subscribed.extend(tokens)

    def unsubscribe(self, tokens):
        for t in tokens:
            if t in self.subscribed:
                self.subscribed.remove(t)

    def set_mode(self, mode, tokens):
        self.modes.append((mode, tuple(tokens)))

    def close(self):
        self.connected = False
        self.closed = True

    def push(self, ticks):
        self.on_ticks(self, ticks)


@pytest.fixture
def live_service_with_fake_ticker(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr("server.live_data_service.KiteTicker", FakeTicker)
    monkeypatch.setattr("server.live_data_service.get_database", lambda: conn)
    monkeypatch.setattr("server.live_data_service.token_store.get_token", lambda _c: "fake-token")
    monkeypatch.setattr("server.kite_client.api_key", lambda: "fake-key")
    monkeypatch.setattr(signals, "get_database", lambda: conn)
    monkeypatch.setattr(signals, "load_warm_start_bars", lambda symbol, lookback_bars=120: [])
    return LiveDataService(), conn


def _tick(token, price, cumulative_volume, ts):
    return {
        "instrument_token": token,
        "last_price": price,
        "volume_traded": cumulative_volume,
        "exchange_timestamp": ts,
    }


def test_service_starts_and_subscribes_to_watched_instruments(live_service_with_fake_ticker):
    service, _ = live_service_with_fake_ticker
    loop = asyncio.new_event_loop()
    try:
        assert service.start(loop) is True
        assert service.is_running() is True
        service.watch(738561, "RELIANCE", "directional_debit_spread", 1, {})
        assert 738561 in service._ticker.subscribed
        assert service.status()["watched_instruments"] == 1

        service.unwatch(738561)
        assert 738561 not in service._ticker.subscribed
    finally:
        service.stop()
        loop.close()


def test_start_is_idempotent(live_service_with_fake_ticker):
    """The startup hook and the login callback both call start()."""
    service, _ = live_service_with_fake_ticker
    loop = asyncio.new_event_loop()
    try:
        service.start(loop)
        first = service._ticker
        service.start(loop)
        assert service._ticker is first, "second start() must not open a second socket"
    finally:
        service.stop()
        loop.close()


def test_start_without_a_token_is_a_soft_failure(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr("server.live_data_service.KiteTicker", FakeTicker)
    monkeypatch.setattr("server.live_data_service.get_database", lambda: conn)
    service = LiveDataService()
    loop = asyncio.new_event_loop()
    try:
        assert service.start(loop) is False
        assert service.is_running() is False
        assert "token" in (service.last_error or "").lower()
    finally:
        loop.close()


def test_bar_volume_uses_the_delta_of_kites_cumulative_counter(live_service_with_fake_ticker):
    """
    Kite's volume_traded is the running day total. The old code added the whole
    cumulative figure on every tick, so a bar built from three ticks reported
    roughly three times the day's volume.
    """
    service, _ = live_service_with_fake_ticker
    loop = asyncio.new_event_loop()
    try:
        service.start(loop)
        service.watch(1, "TESTCO", "directional_debit_spread", 1, {})
        base = datetime(2026, 1, 1, 9, 15, 0)

        service._on_ticks(None, [_tick(1, 100.0, 1000, base)])
        service._on_ticks(None, [_tick(1, 101.0, 1400, base + timedelta(seconds=20))])
        service._on_ticks(None, [_tick(1, 102.0, 1900, base + timedelta(seconds=40))])

        current = service._bar_builders[1]._current
        assert current["volume"] == 900, "expected 400 + 500, not the cumulative total"
        assert current["open"] == 100.0 and current["close"] == 102.0
    finally:
        service.stop()
        loop.close()


def test_bars_are_stamped_with_the_exchange_timestamp(live_service_with_fake_ticker):
    """Not the server clock -- a lagging server put ticks in the wrong minute."""
    service, _ = live_service_with_fake_ticker
    loop = asyncio.new_event_loop()
    try:
        service.start(loop)
        service.watch(1, "TESTCO", "directional_debit_spread", 1, {})
        exchange_time = datetime(2020, 5, 4, 10, 30, 0)
        service._on_ticks(None, [_tick(1, 100.0, 10, exchange_time)])
        assert service._bar_builders[1]._current["ts"] == exchange_time
    finally:
        service.stop()
        loop.close()


def test_ticks_for_unwatched_or_priceless_instruments_are_ignored(live_service_with_fake_ticker):
    service, _ = live_service_with_fake_ticker
    loop = asyncio.new_event_loop()
    try:
        service.start(loop)
        service.watch(1, "TESTCO", "directional_debit_spread", 1, {})
        service._on_ticks(None, [_tick(999, 100.0, 10, datetime(2026, 1, 1, 9, 15))])
        service._on_ticks(None, [{"instrument_token": 1, "last_price": None}])
        assert service._bar_builders[1]._current is None
    finally:
        service.stop()
        loop.close()


def test_watchlist_survives_a_restart(live_service_with_fake_ticker):
    """Rows in the watchlist table must resubscribe, not sit there dead."""
    service, conn = live_service_with_fake_ticker
    conn.execute(
        """INSERT INTO watchlist (symbol, strategy_id, strategy_version, params_json, instrument_token)
           VALUES ('RELIANCE', 'directional_debit_spread', 1, '{"sma_fast": 5}', 738561)"""
    )
    loop = asyncio.new_event_loop()
    try:
        service.start(loop)
        assert 738561 in service._watch
        assert service._watch[738561]["params"] == {"sma_fast": 5}
        assert 738561 in service._ticker.subscribed
    finally:
        service.stop()
        loop.close()


def test_full_chain_tick_to_paper_trade_and_broadcast(live_service_with_fake_ticker, monkeypatch):
    """
    Feed a rising then falling price series through the live path and assert a
    paper trade is written and an ENTRY signal is broadcast to the relay.
    """
    service, conn = live_service_with_fake_ticker
    broadcasts: list[tuple[str, dict]] = []

    async def fake_broadcast(symbol, message):
        broadcasts.append((symbol, message))

    monkeypatch.setattr(ws_relay, "broadcast", fake_broadcast)

    params = {"sma_fast": 2, "sma_slow": 3, "adx_period": 2, "adx_threshold": 0.0,
              "take_profit_pct": 0.01, "stop_loss_pct": 0.01}
    watch = {
        "symbol": "TESTCO", "strategy_id": "directional_debit_spread",
        "strategy_version": 1, "params": params,
        "raw_state": None, "last_signaled_state": None,
        "open_trade_id": None, "entry_price": None, "open_side": None,
    }

    base = datetime(2026, 1, 1, 9, 15)
    history = []
    for i, close in enumerate([100, 101, 103, 106, 110, 115]):
        history.append({"ts": base + timedelta(minutes=i), "open": close, "high": close + 1,
                        "low": close - 1, "close": close, "volume": 10})
        asyncio.run(signals.on_new_bar(watch, list(history), conn=conn))

    trades = conn.execute("SELECT watch_symbol, side, status FROM paper_trades").fetchall()
    assert trades, "a rising trend should have opened a paper trade"
    assert trades[0][0] == "TESTCO"
    assert trades[0][1] == "bull"

    entries = [m for _, m in broadcasts if m.get("action") == "ENTRY"]
    assert entries, "an ENTRY signal should have been broadcast to subscribed clients"
    assert entries[0]["symbol"] == "TESTCO"
    assert any(m.get("type") == "market_tick" for _, m in broadcasts)


def test_a_second_position_is_not_opened_while_one_is_live(live_service_with_fake_ticker, monkeypatch):
    service, conn = live_service_with_fake_ticker

    async def fake_broadcast(symbol, message):
        return None

    monkeypatch.setattr(ws_relay, "broadcast", fake_broadcast)

    params = {"sma_fast": 2, "sma_slow": 3, "adx_period": 2, "adx_threshold": 0.0,
              "take_profit_pct": 5.0, "stop_loss_pct": 5.0}
    watch = {
        "symbol": "TESTCO", "strategy_id": "directional_debit_spread",
        "strategy_version": 1, "params": params,
        "raw_state": None, "last_signaled_state": None,
        "open_trade_id": None, "entry_price": None, "open_side": None,
    }

    base = datetime(2026, 1, 1, 9, 15)
    history = []
    for i, close in enumerate([100, 101, 103, 106, 110, 115, 120, 125]):
        history.append({"ts": base + timedelta(minutes=i), "open": close, "high": close + 1,
                        "low": close - 1, "close": close, "volume": 10})
        asyncio.run(signals.on_new_bar(watch, list(history), conn=conn))

    open_trades = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='OPEN'").fetchone()[0]
    assert open_trades == 1
