"""
Contract tests for the live-data surface: how the Zerodha sync narrows the
option universe, and what HTTP status the API returns when Kite is not usable.

The status codes matter because the frontend has to tell three situations
apart: "your .env is wrong" (400), "log in again" (401) and "Zerodha is having
a bad day" (502). The old build returned 400 for all three, or a 500 with a
stack trace.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from server import kite_client, token_store, zerodha
from server.database import reset_database_for_tests
from server.main import app


# ---------------------------------------------------------------------------
# Zerodha sync
# ---------------------------------------------------------------------------

class FakeChainKite:
    """A full option chain: 21 strikes, both option types, one expiry."""

    def __init__(self, fail_tokens: set[int] | None = None):
        self.historical_calls: list[int] = []
        self.instrument_calls: list[str] = []
        self.fail_tokens = fail_tokens or set()

    def instruments(self, exchange):
        self.instrument_calls.append(exchange)
        if exchange == "NSE":
            return [
                {"tradingsymbol": "TESTCO", "instrument_token": 1,
                 "instrument_type": "EQ", "segment": "NSE"},
                {"tradingsymbol": "TESTCO", "instrument_token": 99,
                 "instrument_type": "EQ", "segment": "BSE"},  # wrong exchange
            ]
        chain = []
        token = 100
        for strike in range(900, 1101, 10):
            for option_type in ("CE", "PE"):
                chain.append({
                    "name": "TESTCO", "tradingsymbol": f"TESTCO{strike}{option_type}",
                    "instrument_token": token, "expiry": date(2026, 8, 27),
                    "strike": float(strike), "instrument_type": option_type, "lot_size": 50,
                })
                token += 1
        return chain

    def historical_data(self, token, start, end, interval, oi=False):
        self.historical_calls.append(token)
        if token in self.fail_tokens:
            raise RuntimeError("simulated contract failure")
        if token == 1:
            return [{"date": datetime(2026, 8, 20), "open": 999, "high": 1005,
                     "low": 995, "close": 1000, "volume": 1000}]
        return [{"date": datetime(2026, 8, 20), "open": 4, "high": 5,
                 "low": 3, "close": 4.5, "volume": 20, "oi": 10}]


@pytest.fixture(autouse=True)
def _no_throttle_in_tests(monkeypatch):
    monkeypatch.setattr(zerodha.settings, "KITE_HISTORICAL_THROTTLE", 0.0)


def test_sync_windows_strikes_around_atm_instead_of_the_whole_chain(monkeypatch):
    """
    Pulling every strike of the nearest expiry is what triggers Zerodha's rate
    limit. With spot at 1000 and a +/-5 window we expect 11 strikes x 2 types.
    """
    conn = reset_database_for_tests()
    fake = FakeChainKite()
    monkeypatch.setattr(zerodha, "_kite_client", lambda: fake)
    monkeypatch.setattr(zerodha.settings, "SYNC_MAX_CONTRACTS", 100)
    monkeypatch.setattr(zerodha.settings, "SYNC_STRIKE_WINDOW", 5)

    result = zerodha.sync_market_data(conn, "testco", date_start="2026-08-01", date_end="2026-08-24")

    assert result["contracts_requested"] == 22
    strikes = [r[0] for r in conn.execute(
        "SELECT DISTINCT strike FROM option_bars ORDER BY strike"
    ).fetchall()]
    assert min(strikes) == 950.0 and max(strikes) == 1050.0
    assert any("windowed" in w for w in result["warnings"])


def test_sync_caps_the_number_of_contracts(monkeypatch):
    conn = reset_database_for_tests()
    fake = FakeChainKite()
    monkeypatch.setattr(zerodha, "_kite_client", lambda: fake)
    monkeypatch.setattr(zerodha.settings, "SYNC_MAX_CONTRACTS", 4)

    result = zerodha.sync_market_data(conn, "testco", date_start="2026-08-01", date_end="2026-08-24")

    assert result["contracts_requested"] == 4
    # 1 equity call + 4 option calls, and nothing more.
    assert len(fake.historical_calls) == 5
    assert any("capped" in w for w in result["warnings"])


def test_one_bad_contract_does_not_abort_the_whole_sync(monkeypatch):
    conn = reset_database_for_tests()
    # Tokens are laid out strike-major from 900: strike 950 is the 6th strike,
    # so its CE/PE pair is 110/111. Both sit inside the window we request.
    fake = FakeChainKite(fail_tokens={110, 111})
    monkeypatch.setattr(zerodha, "_kite_client", lambda: fake)
    monkeypatch.setattr(zerodha.settings, "SYNC_MAX_CONTRACTS", 6)

    result = zerodha.sync_market_data(
        conn, "testco", date_start="2026-08-01", date_end="2026-08-24",
        strikes=[950.0, 960.0, 970.0],
    )

    assert result["option_rows"] > 0, "surviving contracts should still be written"
    assert len(result["contracts_failed"]) == 2
    assert any("failed" in w for w in result["warnings"])


def test_sync_picks_the_nse_equity_row_not_a_lookalike(monkeypatch):
    conn = reset_database_for_tests()
    fake = FakeChainKite()
    monkeypatch.setattr(zerodha, "_kite_client", lambda: fake)
    monkeypatch.setattr(zerodha.settings, "SYNC_MAX_CONTRACTS", 2)

    zerodha.sync_market_data(conn, "testco", date_start="2026-08-01", date_end="2026-08-24")
    assert fake.historical_calls[0] == 1, "should use the NSE-segment EQ instrument"


def test_demo_symbol_is_refused_before_any_network_call(monkeypatch):
    conn = reset_database_for_tests()

    def _boom():
        raise AssertionError("must not contact Zerodha for a demo symbol")

    monkeypatch.setattr(zerodha, "_kite_client", _boom)
    with pytest.raises(ValueError, match="demo"):
        zerodha.sync_market_data(conn, "DEMOSTK")


def test_inverted_date_range_is_rejected(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(zerodha, "_kite_client", lambda: FakeChainKite())
    with pytest.raises(ValueError, match="cannot be after"):
        zerodha.sync_market_data(conn, "testco", date_start="2026-08-24", date_end="2026-08-01")


# ---------------------------------------------------------------------------
# API status codes
# ---------------------------------------------------------------------------

client = TestClient(app)


def test_health_reports_database_and_kite_state():
    body = client.get("/api/health").json()
    assert body["status"] in ("ok", "degraded")
    assert "database" in body and "kite_authenticated" in body


def test_diagnostics_explains_the_blocker_without_leaking_secrets(monkeypatch):
    monkeypatch.setenv("OA_KITE_API_KEY", "your_kite_api_key")
    body = client.get("/api/kite/diagnostics").json()
    assert body["ready"] is False
    assert body["problems"], "a placeholder key must be reported as a problem"
    assert body["credentials"]["api_key"] == "placeholder"
    assert body["next_step"]


def test_placeholder_credentials_return_400_not_500(monkeypatch):
    monkeypatch.setenv("OA_KITE_API_KEY", "your_kite_api_key")
    response = client.get("/api/kite/login-url")
    assert response.status_code == 400
    assert response.json()["error"] == "kite_not_configured"


def test_missing_token_returns_401(monkeypatch):
    monkeypatch.setenv("OA_KITE_API_KEY", "realkey")
    monkeypatch.setenv("OA_KITE_ACCESS_TOKEN", "your_kite_access_token")
    monkeypatch.setattr(token_store, "get_token", lambda _c: None)
    response = client.post("/api/live/sync", json={"symbol": "RELIANCE"})
    assert response.status_code == 401
    assert response.json()["error"] == "kite_reauth_required"


def test_upstream_failure_returns_502(monkeypatch):
    def _explode(*_a, **_k):
        raise kite_client.KiteUpstreamError("Zerodha is down")

    monkeypatch.setattr("server.main.sync_market_data", _explode)
    response = client.post("/api/live/sync", json={"symbol": "RELIANCE"})
    assert response.status_code == 502
    assert response.json()["error"] == "kite_upstream_error"


def test_rate_limit_returns_429(monkeypatch):
    def _explode(*_a, **_k):
        raise kite_client.KiteRateLimitError("Too many requests")

    monkeypatch.setattr("server.main.sync_market_data", _explode)
    response = client.post("/api/live/sync", json={"symbol": "RELIANCE"})
    assert response.status_code == 429


def test_demo_symbol_sync_is_rejected_with_guidance():
    response = client.post("/api/live/sync", json={"symbol": "DEMOSTK"})
    assert response.status_code == 400
    assert "demo" in response.json()["detail"].lower()


def test_live_market_labels_simulated_data_as_simulated(monkeypatch):
    """
    The dashboard must never present fabricated prices as real. When Kite is
    unavailable the payload still renders, but tagged.
    """
    monkeypatch.setattr(token_store, "get_token", lambda _c: None)
    monkeypatch.setenv("OA_KITE_ACCESS_TOKEN", "your_kite_access_token")
    from server.live_market import live_market_service
    live_market_service._cache = None

    body = client.get("/api/live/market").json()
    assert body["type"] == "market_snapshot"
    assert body["source"] == "simulated"
    assert body["source_detail"]
    assert all(s["source"] == "simulated" for s in body["symbols"].values())


def test_live_market_uses_real_quotes_when_kite_is_available(monkeypatch):
    from server.live_market import live_market_service

    def fake_quote(keys):
        return {
            key: {"last_price": 2900.5, "ohlc": {"close": 2838.39, "open": 2850,
                                                 "high": 2910, "low": 2840},
                  "volume": 1234, "last_trade_time": "2026-09-04 15:29:59"}
            for key in keys
        }

    monkeypatch.setattr("server.live_market.kite_client.quote", fake_quote)
    live_market_service._cache = None

    body = client.get("/api/live/market").json()
    assert body["source"] == "kite"
    reliance = body["symbols"]["RELIANCE"]
    assert reliance["price"] == 2900.5
    assert reliance["previous_close"] == 2838.39
    assert reliance["change"] == pytest.approx(62.11, abs=0.01)
    live_market_service._cache = None
