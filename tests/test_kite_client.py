"""
Tests for the Kite adapter's guard rails.

These cover the exact failure that made the live API look broken in the first
place: a .env holding `your_kite_api_key` passed every truthiness check, so the
backend happily built a login URL with a fake key and blamed Zerodha for the
result.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from server import kite_client, token_store
from server.database import reset_database_for_tests


class _FakeTokenException(Exception):
    pass


_FakeTokenException.__name__ = "TokenException"


class _FakeNetworkException(Exception):
    pass


_FakeNetworkException.__name__ = "NetworkException"


# --- credential validation -------------------------------------------------

@pytest.mark.parametrize("value", [
    "", "   ", "your_kite_api_key", "YOUR_KITE_API_SECRET", "changeme",
    "<paste-key-here>", "none", "replace_me",
])
def test_placeholder_values_are_rejected(value, monkeypatch):
    monkeypatch.setenv("OA_KITE_API_KEY", value)
    with pytest.raises(kite_client.KiteConfigError):
        kite_client.api_key()


def test_real_looking_key_is_accepted(monkeypatch):
    monkeypatch.setenv("OA_KITE_API_KEY", "  abc123xyz  ")
    assert kite_client.api_key() == "abc123xyz"


def test_credentials_status_never_leaks_the_secret(monkeypatch):
    monkeypatch.setenv("OA_KITE_API_KEY", "supersecretkey")
    monkeypatch.setenv("OA_KITE_API_SECRET", "your_kite_api_secret")
    status = kite_client.credentials_status()
    assert status["api_key"] == "configured"
    assert status["api_secret"] == "placeholder"
    assert "supersecretkey" not in str(status)


def test_configuration_problems_names_what_to_fix(monkeypatch):
    monkeypatch.setenv("OA_KITE_API_KEY", "your_kite_api_key")
    monkeypatch.setenv("OA_KITE_API_SECRET", "realsecret")
    problems = kite_client.configuration_problems()
    assert any("OA_KITE_API_KEY" in p and "placeholder" in p for p in problems)
    assert not any("OA_KITE_API_SECRET" in p for p in problems)


# --- error translation -----------------------------------------------------

def test_token_exception_becomes_auth_error():
    with pytest.raises(kite_client.KiteAuthError):
        kite_client.call("testing", lambda: (_ for _ in ()).throw(_FakeTokenException("expired")))


def test_network_exception_becomes_upstream_error():
    with pytest.raises(kite_client.KiteUpstreamError):
        kite_client.call("testing", lambda: (_ for _ in ()).throw(_FakeNetworkException("boom")))


def test_rate_limit_is_its_own_error():
    def _raise():
        raise _FakeNetworkException("Too many requests")
    with pytest.raises(kite_client.KiteRateLimitError):
        kite_client.call("testing", _raise)


def test_successful_call_passes_through():
    assert kite_client.call("testing", lambda x: x + 1, 41) == 42


# --- instrument cache ------------------------------------------------------

def test_instrument_dump_is_downloaded_once_then_cached(monkeypatch):
    kite_client.clear_instrument_cache()
    calls = {"n": 0}

    class FakeKite:
        def instruments(self, exchange):
            calls["n"] += 1
            return [{"tradingsymbol": "RELIANCE", "instrument_token": 738561}]

    monkeypatch.setattr(kite_client, "get_authenticated_kite", lambda: FakeKite())

    assert kite_client.resolve_instrument_token("reliance") == 738561
    assert kite_client.resolve_instrument_token("RELIANCE") == 738561
    assert calls["n"] == 1, "the multi-MB instrument dump must not be refetched per lookup"

    with pytest.raises(ValueError, match="not found"):
        kite_client.resolve_instrument_token("NOSUCHCO")
    kite_client.clear_instrument_cache()


# --- token precedence ------------------------------------------------------

def test_login_flow_token_wins_over_env_token(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(kite_client, "get_database", lambda: conn)
    monkeypatch.setenv("OA_KITE_API_KEY", "realkey")
    monkeypatch.setenv("OA_KITE_ACCESS_TOKEN", "env-token")
    token_store.save_token(conn, "login-flow-token")

    applied = {}

    class FakeKite:
        def set_access_token(self, token):
            applied["token"] = token

    monkeypatch.setattr(kite_client, "_kite", lambda: FakeKite())
    kite_client.get_authenticated_kite()
    assert applied["token"] == "login-flow-token"


def test_env_token_is_the_fallback_when_no_login_has_happened(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(kite_client, "get_database", lambda: conn)
    monkeypatch.setenv("OA_KITE_ACCESS_TOKEN", "env-token")

    applied = {}

    class FakeKite:
        def set_access_token(self, token):
            applied["token"] = token

    monkeypatch.setattr(kite_client, "_kite", lambda: FakeKite())
    kite_client.get_authenticated_kite()
    assert applied["token"] == "env-token"


def test_no_token_anywhere_raises_auth_error(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(kite_client, "get_database", lambda: conn)
    monkeypatch.setenv("OA_KITE_ACCESS_TOKEN", "your_kite_access_token")
    with pytest.raises(kite_client.KiteAuthError):
        kite_client.get_authenticated_kite()


# --- token expiry ----------------------------------------------------------

def test_token_expires_at_the_next_ist_morning_boundary():
    conn = reset_database_for_tests()
    token_store.save_token(conn, "abc")
    assert token_store.get_token(conn) == "abc"

    row = conn.execute("SELECT generated_at, expires_at FROM kite_sessions").fetchone()
    generated_at, expires_at = row
    assert expires_at > generated_at
    # Never more than a day and a half out, whatever the server's timezone is.
    assert expires_at - generated_at <= timedelta(days=1, hours=1)

    ist_expiry = expires_at.replace(tzinfo=timezone.utc).astimezone(token_store.IST)
    assert (ist_expiry.hour, ist_expiry.minute) == (6, 0)


def test_expired_token_is_not_returned():
    conn = reset_database_for_tests()
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    conn.execute(
        "INSERT INTO kite_sessions (id, access_token, generated_at, expires_at) VALUES (1, ?, ?, ?)",
        ["stale", past, past],
    )
    assert token_store.get_token(conn) is None
    assert token_store.token_status(conn)["expired"] is True


def test_clear_token_removes_the_session():
    conn = reset_database_for_tests()
    token_store.save_token(conn, "abc")
    token_store.clear_token(conn)
    assert token_store.get_token(conn) is None
