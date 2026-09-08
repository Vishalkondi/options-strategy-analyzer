"""
Centralized Zerodha Kite Connect REST client.

Every Kite REST call in this codebase goes through this module. Nothing else
constructs a KiteConnect object, reads credentials, or touches access tokens.

Responsibilities
----------------
- Read Kite credentials lazily from the environment / .env (so editing .env
  and restarting is enough -- no code change, no import-order surprises).
- Reject placeholder credentials loudly instead of sending them to Zerodha
  and getting an opaque 403/502 back.
- Generate the login URL and exchange request_token -> access_token.
- Hand out an authenticated KiteConnect client using the token stored by
  token_store (the daily login flow), falling back to OA_KITE_ACCESS_TOKEN.
- Resolve NSE instrument tokens, with a TTL cache (the instrument dump is
  a multi-MB download -- fetching it per lookup is what makes "live" feel
  broken).
- Translate every kiteconnect exception into one of three typed errors so
  the API layer can map them to sane HTTP codes instead of leaking a 500.

This module NEVER places orders.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from server import token_store
from server.database import get_database

logger = logging.getLogger("kite_client")

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

try:
    from kiteconnect import KiteConnect
except ImportError:  # pragma: no cover - exercised only when the dep is absent
    KiteConnect = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Typed errors. The API layer maps these to HTTP codes in server/main.py.
# ---------------------------------------------------------------------------

class KiteConfigError(RuntimeError):
    """Credentials are missing, blank, or still the placeholder text. -> HTTP 400"""


class KiteAuthError(RuntimeError):
    """No valid access token, or Zerodha rejected the one we have. -> HTTP 401"""


class KiteUpstreamError(RuntimeError):
    """Zerodha was reachable but failed, or was not reachable at all. -> HTTP 502"""


class KiteRateLimitError(KiteUpstreamError):
    """Zerodha rate limit hit. -> HTTP 429"""


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

# Values that look filled-in but are not. This is the exact failure that made
# the live API look broken: .env held `your_kite_api_key`, `bool(value)` was
# True, so every check passed and Zerodha returned garbage.
_PLACEHOLDERS = {
    "", "none", "null", "todo", "changeme", "change_me", "xxx", "xxxx",
    "your_kite_api_key", "your_kite_api_secret", "your_kite_access_token",
    "your-api-key", "your-api-secret", "api_key", "api_secret", "access_token",
}


def _is_placeholder(value: str) -> bool:
    cleaned = value.strip().strip("\"'").lower()
    if cleaned in _PLACEHOLDERS:
        return True
    return cleaned.startswith(("your_", "your-", "<", "replace_", "insert_"))


def _read(name: str) -> str:
    return (os.environ.get(name) or "").strip().strip("\"'")


def api_key() -> str:
    value = _read("OA_KITE_API_KEY")
    if _is_placeholder(value):
        raise KiteConfigError(
            f"OA_KITE_API_KEY is not set to a real value in {ENV_FILE}. "
            "Copy the API key from https://developers.kite.trade/apps and restart the backend."
        )
    return value


def api_secret() -> str:
    value = _read("OA_KITE_API_SECRET")
    if _is_placeholder(value):
        raise KiteConfigError(
            f"OA_KITE_API_SECRET is not set to a real value in {ENV_FILE}. "
            "Copy the API secret from https://developers.kite.trade/apps and restart the backend."
        )
    return value


def env_access_token() -> str | None:
    """Legacy manually-pasted token. Only used if the login flow has not run."""
    value = _read("OA_KITE_ACCESS_TOKEN")
    return None if _is_placeholder(value) else value


def credentials_status() -> dict[str, Any]:
    """Safe diagnostics. Never returns a credential value."""
    def state(name: str) -> str:
        raw = _read(name)
        if not raw:
            return "missing"
        return "placeholder" if _is_placeholder(raw) else "configured"

    return {
        "kiteconnect_installed": KiteConnect is not None,
        "env_file": str(ENV_FILE),
        "env_file_exists": ENV_FILE.exists(),
        "api_key": state("OA_KITE_API_KEY"),
        "api_secret": state("OA_KITE_API_SECRET"),
        "env_access_token": state("OA_KITE_ACCESS_TOKEN"),
    }


def configuration_problems() -> list[str]:
    """Human-readable list of what still blocks live data. Empty == ready."""
    problems: list[str] = []
    if KiteConnect is None:
        problems.append("kiteconnect is not installed (pip install -r requirements.txt)")
    if not ENV_FILE.exists():
        problems.append(f"{ENV_FILE} does not exist (copy .env.example to .env)")
    for label, name in (("API key", "OA_KITE_API_KEY"), ("API secret", "OA_KITE_API_SECRET")):
        raw = _read(name)
        if not raw:
            problems.append(f"{name} is missing -- add your Kite {label} to .env")
        elif _is_placeholder(raw):
            problems.append(f"{name} is still the placeholder value -- replace it with your real Kite {label}")
    return problems


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

def _translate(exc: Exception, context: str) -> Exception:
    """Map any kiteconnect / network failure onto our typed errors."""
    name = type(exc).__name__
    message = str(exc)

    if name in ("TokenException",):
        return KiteAuthError(
            f"Zerodha rejected the access token while {context}. "
            "The token expires every morning -- log in again via /api/kite/login-url."
        )
    if name in ("PermissionException",):
        return KiteAuthError(f"Zerodha denied permission while {context}: {message}")
    if name in ("NetworkException", "DataException", "GeneralException", "InputException"):
        if "too many requests" in message.lower() or "429" in message:
            return KiteRateLimitError(f"Zerodha rate limit hit while {context}. Slow down and retry.")
        return KiteUpstreamError(f"Zerodha request failed while {context}: {message}")
    if isinstance(exc, (KiteConfigError, KiteAuthError, KiteUpstreamError)):
        return exc
    return KiteUpstreamError(f"Unexpected Kite failure while {context}: {name}: {message}")


def call(context: str, fn, *args, **kwargs):
    """Run a Kite SDK call and normalise its failure mode."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, then re-typed
        raise _translate(exc, context) from exc


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------

_client_lock = threading.Lock()
_client: Any = None
_client_key: str | None = None


def _kite() -> Any:
    """One KiteConnect instance per API key, for this process."""
    if KiteConnect is None:
        raise KiteConfigError("kiteconnect is not installed. Run: pip install kiteconnect")
    key = api_key()
    global _client, _client_key
    with _client_lock:
        if _client is None or _client_key != key:
            _client = KiteConnect(api_key=key)
            _client_key = key
        return _client


def login_url() -> str:
    """URL the user opens in a browser to start the daily Zerodha login."""
    return call("building the login URL", _kite().login_url)


def exchange_request_token(request_token: str) -> str:
    """Swap the request_token Zerodha redirected back with for an access_token."""
    request_token = (request_token or "").strip()
    if not request_token:
        raise KiteConfigError("request_token is empty.")

    secret = api_secret()
    data = call(
        "exchanging the request token",
        _kite().generate_session, request_token, api_secret=secret,
    )
    if not isinstance(data, dict) or not data.get("access_token"):
        raise KiteUpstreamError("Zerodha session response did not contain an access_token.")

    access_token = str(data["access_token"]).strip()
    token_store.save_token(get_database(), access_token)
    clear_instrument_cache()
    logger.info("Kite access token stored; valid until the next expiry boundary.")
    return access_token


def get_authenticated_kite() -> Any:
    """
    KiteConnect client with today's access token applied.

    Token precedence: the one saved by the login flow, then the legacy
    OA_KITE_ACCESS_TOKEN in .env. Raises KiteAuthError when neither exists,
    so callers never silently talk to Zerodha unauthenticated.
    """
    token = token_store.get_token(get_database()) or env_access_token()
    if not token:
        raise KiteAuthError(
            "kite_reauth_required: no valid Kite access token. "
            "Open /api/kite/login-url, complete the Zerodha login, and the callback will store one."
        )
    kite = _kite()
    kite.set_access_token(str(token).strip())
    return kite


def profile() -> dict[str, Any]:
    """Cheapest possible authenticated round-trip -- proves the token really works."""
    data = call("fetching the Kite profile", get_authenticated_kite().profile)
    return {
        "user_id": data.get("user_id"),
        "user_name": data.get("user_name"),
        "broker": data.get("broker"),
        "email": data.get("email"),
    }


def logout() -> None:
    token_store.clear_token(get_database())
    clear_instrument_cache()


# ---------------------------------------------------------------------------
# Instrument cache (TTL). The dump is several MB -- do not refetch per lookup.
# ---------------------------------------------------------------------------

INSTRUMENT_TTL_SECONDS = float(os.environ.get("OA_INSTRUMENT_TTL_SECONDS", "21600"))  # 6h

_instrument_lock = threading.Lock()
_instrument_cache: dict[str, tuple[float, list[dict]]] = {}
_token_by_symbol: dict[str, int] = {}


def instruments(exchange: str = "NSE", force_refresh: bool = False) -> list[dict]:
    """Cached instrument dump for an exchange ('NSE', 'NFO')."""
    exchange = exchange.upper()
    now = time.time()
    with _instrument_lock:
        cached = _instrument_cache.get(exchange)
        if cached and not force_refresh and (now - cached[0]) < INSTRUMENT_TTL_SECONDS:
            return cached[1]

    data = call(f"downloading the {exchange} instrument list", get_authenticated_kite().instruments, exchange)
    if not data:
        raise KiteUpstreamError(f"Zerodha returned no {exchange} instruments.")

    with _instrument_lock:
        _instrument_cache[exchange] = (now, data)
        if exchange == "NSE":
            _token_by_symbol.clear()
            for item in data:
                symbol = str(item.get("tradingsymbol", "")).strip().upper()
                token = item.get("instrument_token")
                if symbol and token is not None:
                    try:
                        _token_by_symbol[symbol] = int(token)
                    except (TypeError, ValueError):
                        continue
    return data


def resolve_instrument_token(symbol: str) -> int:
    """NSE equity trading symbol -> Kite instrument_token."""
    if not isinstance(symbol, str):
        raise ValueError("symbol must be a string")
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol cannot be empty")

    with _instrument_lock:
        if symbol in _token_by_symbol:
            return _token_by_symbol[symbol]

    instruments("NSE")

    with _instrument_lock:
        if symbol in _token_by_symbol:
            return _token_by_symbol[symbol]
    raise ValueError(f"NSE equity instrument not found for symbol {symbol!r}")


def clear_instrument_cache() -> None:
    with _instrument_lock:
        _instrument_cache.clear()
        _token_by_symbol.clear()


def clear_kite_client_cache() -> None:
    global _client, _client_key
    with _client_lock:
        _client = None
        _client_key = None


# ---------------------------------------------------------------------------
# Market data helpers
# ---------------------------------------------------------------------------

def quote(instrument_keys: list[str]) -> dict[str, Any]:
    """Full quote for keys like 'NSE:RELIANCE'."""
    if not instrument_keys:
        return {}
    return call("fetching quotes", get_authenticated_kite().quote, instrument_keys)


def ltp(instrument_keys: list[str]) -> dict[str, Any]:
    """Last traded price only -- cheaper than quote()."""
    if not instrument_keys:
        return {}
    return call("fetching last traded prices", get_authenticated_kite().ltp, instrument_keys)


def historical_data(instrument_token: int, start, end, interval: str = "day", oi: bool = False):
    return call(
        f"downloading {interval} candles for instrument {instrument_token}",
        get_authenticated_kite().historical_data, instrument_token, start, end, interval, False, oi,
    )
