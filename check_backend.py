#!/usr/bin/env python3
"""
One-command backend health check.

    python check_backend.py            # check everything, no network calls to Zerodha
    python check_backend.py --live     # also make one real authenticated Kite call

Run this before blaming the frontend. It tells you, in order:
  1. Are the Python dependencies installed?
  2. Does the DuckDB database open and does the schema apply?
  3. Do the offline endpoints (import, backtest, runs, trades) work?
  4. Is Kite configured with real credentials, and is there a valid token?
  5. With --live: does Zerodha actually answer an authenticated request?

Exit code is 0 when everything that can work does, 1 otherwise.
"""
from __future__ import annotations

import argparse
import sys

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

_failures = 0
_warnings = 0


def ok(message: str, detail: str = "") -> None:
    print(f"  {GREEN}PASS{RESET}  {message}" + (f"  {DIM}{detail}{RESET}" if detail else ""))


def warn(message: str, detail: str = "") -> None:
    global _warnings
    _warnings += 1
    print(f"  {YELLOW}WARN{RESET}  {message}" + (f"\n        {DIM}{detail}{RESET}" if detail else ""))


def fail(message: str, detail: str = "") -> None:
    global _failures
    _failures += 1
    print(f"  {RED}FAIL{RESET}  {message}" + (f"\n        {DIM}{detail}{RESET}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def check_dependencies() -> bool:
    section("1. Dependencies")
    missing = []
    for module in ("fastapi", "uvicorn", "duckdb", "pandas", "pydantic", "yaml", "dotenv"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        fail(f"missing packages: {', '.join(missing)}", "pip install -r requirements.txt")
        return False
    ok("core packages importable")

    try:
        import kiteconnect  # noqa: F401
        ok("kiteconnect installed")
    except ImportError:
        fail("kiteconnect is not installed", "pip install kiteconnect  (live data will not work without it)")
    return True


DB_LOCKED = False


def _is_lock_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "being used by another process" in text or "already open" in text or "lock" in text


def check_database() -> bool:
    """DuckDB allows one writer process at a time. If the backend is already
    running, that is not a fault -- say so and skip the checks that need the
    file, rather than dumping a traceback."""
    global DB_LOCKED
    section("2. Database")
    try:
        from server.config import settings
        from server.database import get_database
        conn = get_database()
        conn.execute("SELECT 1").fetchone()
        ok("DuckDB opened", str(settings.DB_PATH))
    except Exception as exc:  # noqa: BLE001
        if _is_lock_error(exc):
            DB_LOCKED = True
            warn("the database is locked by the running backend",
                 "That is expected -- DuckDB allows one writer at a time.\n"
                 "        Stop uvicorn (Ctrl+C in its window) and run this again,\n"
                 "        or just check the running server: http://127.0.0.1:8000/api/kite/diagnostics")
            return False
        fail(f"could not open the database: {exc}")
        return False

    expected = ["equity_bars", "option_bars", "runs", "trades", "trade_legs",
                "imports", "strategies", "kite_sessions", "watchlist",
                "live_market_data", "paper_trades", "paper_positions"]
    present = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    missing = [t for t in expected if t not in present]
    if missing:
        fail(f"missing tables: {', '.join(missing)}")
    else:
        ok(f"all {len(expected)} tables present")

    equity = conn.execute("SELECT COUNT(*) FROM equity_bars").fetchone()[0]
    options = conn.execute("SELECT COUNT(*) FROM option_bars").fetchone()[0]
    if equity == 0 and options == 0:
        warn("no market data loaded", "POST /api/import with {\"path\": \"demo\"} to load the demo fixtures")
    else:
        ok("market data present", f"{equity} equity bars, {options} option bars")
    return True


def check_api() -> bool:
    section("3. Offline API (no Zerodha needed)")
    if DB_LOCKED:
        warn("skipped -- the database is locked by the running backend",
             "Stop uvicorn and re-run, or browse http://127.0.0.1:8000/docs")
        return False
    try:
        from fastapi.testclient import TestClient
        from server.main import app
    except Exception as exc:  # noqa: BLE001
        fail(f"the app could not be imported: {exc}")
        return False

    try:
        client_cm = TestClient(app)
        client_cm.__enter__()
    except Exception as exc:  # noqa: BLE001
        fail(f"the app failed to start: {exc}")
        return False

    with client_cm as client:
        health = client.get("/api/health")
        if health.status_code == 200 and health.json().get("status") == "ok":
            ok("/api/health", health.json().get("version", ""))
        else:
            fail(f"/api/health returned {health.status_code}", health.text[:200])

        for endpoint in ("/api/stats", "/api/symbols", "/api/strategies",
                         "/api/runs", "/api/imports", "/api/trades?limit=1",
                         "/api/live/status", "/api/paper/positions"):
            response = client.get(endpoint)
            if response.status_code == 200:
                ok(endpoint)
            else:
                fail(f"{endpoint} returned {response.status_code}", response.text[:200])

        strategies = client.get("/api/strategies").json()
        symbols = client.get("/api/symbols").json()
        if strategies and symbols:
            run = client.post("/api/runs", json={
                "strategy_file": strategies[0]["file"], "symbol": symbols[0],
            })
            if run.status_code == 200:
                body = run.json()
                ok("backtest ran end to end",
                   f"status={body.get('status')} trades={body.get('num_trades')}")
            else:
                fail(f"backtest failed with {run.status_code}", run.text[:200])
        else:
            warn("skipped the backtest check", "no strategies or no imported symbols yet")
    return True


def check_kite(live: bool) -> bool:
    section("4. Zerodha Kite configuration")
    from server import kite_client, token_store
    from server.database import get_database

    problems = kite_client.configuration_problems()
    status = kite_client.credentials_status()
    print(f"  {DIM}.env: {status['env_file']} (exists={status['env_file_exists']}){RESET}")
    print(f"  {DIM}api_key={status['api_key']}  api_secret={status['api_secret']}  "
          f"env_access_token={status['env_access_token']}{RESET}")

    if problems:
        for problem in problems:
            fail(problem)
        print(f"\n  {DIM}Fix: open the .env file in a text editor -- these are file contents,"
              f"\n  not commands to type at the prompt:"
              f"\n      notepad .env          (Windows)"
              f"\n      nano .env             (macOS / Linux)"
              f"\n  Set OA_KITE_API_KEY and OA_KITE_API_SECRET to the values from"
              f"\n  https://developers.kite.trade/apps, save, then restart the backend.{RESET}")
        return False
    ok("API key and secret look real")

    if DB_LOCKED:
        warn("cannot read the stored token while the backend holds the database",
             "Check the running server instead: http://127.0.0.1:8000/api/kite/diagnostics")
        return True

    token = token_store.token_status(get_database())
    if token["has_valid_token"]:
        ok("a valid access token is stored", f"expires {token['expires_at']}")
    elif token["expired"]:
        warn("the stored access token has expired",
             "Kite tokens die every morning. Open /api/kite/login-url and log in again.")
    else:
        warn("no access token stored yet",
             "Open GET /api/kite/login-url, complete the Zerodha login, and the "
             "callback will store one automatically.")

    if not live:
        print(f"\n  {DIM}Re-run with --live to make a real authenticated call to Zerodha.{RESET}")
        return True

    section("5. Live Zerodha round-trip")
    try:
        profile = kite_client.profile()
        ok("authenticated call succeeded", f"user_id={profile.get('user_id')}")
    except kite_client.KiteAuthError as exc:
        fail("Zerodha rejected the token", str(exc))
        return False
    except kite_client.KiteConfigError as exc:
        fail("credentials are not usable", str(exc))
        return False
    except kite_client.KiteUpstreamError as exc:
        fail("Zerodha could not be reached", str(exc))
        return False

    try:
        token = kite_client.resolve_instrument_token("RELIANCE")
        ok("instrument lookup works", f"RELIANCE -> {token}")
    except Exception as exc:  # noqa: BLE001
        fail(f"instrument lookup failed: {exc}")

    try:
        quotes = kite_client.quote(["NSE:RELIANCE"])
        price = quotes.get("NSE:RELIANCE", {}).get("last_price")
        ok("live quote received", f"RELIANCE last price {price}")
    except Exception as exc:  # noqa: BLE001
        fail(f"live quote failed: {exc}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Options Strategy Analyzer backend.")
    parser.add_argument("--live", action="store_true",
                        help="also make a real authenticated call to Zerodha")
    args = parser.parse_args()

    print("Options Strategy Analyzer - backend check")

    if check_dependencies():
        check_database()
        check_api()
        check_kite(args.live)

    print()
    if _failures:
        print(f"{RED}{_failures} check(s) failed{RESET}"
              + (f", {_warnings} warning(s)" if _warnings else ""))
        return 1
    if _warnings:
        print(f"{GREEN}Backend is working.{RESET} {_warnings} warning(s) - "
              "usually just missing Kite credentials or a token.")
        return 0
    print(f"{GREEN}All checks passed.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
