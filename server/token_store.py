"""
Owns the single daily Kite access token.

Nothing else in this codebase reads or writes access tokens directly, so
there is exactly one place that knows what a valid token looks like and one
place to change if storage ever changes.

Expiry rule: Zerodha invalidates an access token every morning regardless of
when it was issued. We store the boundary as 06:00 IST on the next calendar
day after issue, in UTC, and compare in UTC -- so the check does not silently
shift when the machine's local timezone is not IST.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import duckdb

IST = timezone(timedelta(hours=5, minutes=30))
_TOKEN_EXPIRY_IST = time(6, 0)  # Kite sessions die at ~6am IST the next day


def _utc_now() -> datetime:
    """Naive UTC -- DuckDB TIMESTAMP columns here are timezone-free."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_expiry_utc(now_utc: datetime) -> datetime:
    now_ist = now_utc.replace(tzinfo=timezone.utc).astimezone(IST)
    boundary = now_ist.replace(
        hour=_TOKEN_EXPIRY_IST.hour, minute=_TOKEN_EXPIRY_IST.minute,
        second=0, microsecond=0,
    )
    if boundary <= now_ist:
        boundary += timedelta(days=1)
    return boundary.astimezone(timezone.utc).replace(tzinfo=None)


def save_token(conn: duckdb.DuckDBPyConnection, access_token: str) -> None:
    now = _utc_now()
    conn.execute("DELETE FROM kite_sessions")
    conn.execute(
        "INSERT INTO kite_sessions (id, access_token, generated_at, expires_at) VALUES (1, ?, ?, ?)",
        [access_token, now, _next_expiry_utc(now)],
    )


def get_token(conn: duckdb.DuckDBPyConnection) -> str | None:
    row = conn.execute(
        "SELECT access_token, expires_at FROM kite_sessions WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    access_token, expires_at = row
    if expires_at is None or _utc_now() >= expires_at:
        return None
    return access_token


def clear_token(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("DELETE FROM kite_sessions")


def token_status(conn: duckdb.DuckDBPyConnection) -> dict:
    row = conn.execute(
        "SELECT generated_at, expires_at FROM kite_sessions WHERE id = 1"
    ).fetchone()
    token = get_token(conn)
    return {
        "has_valid_token": token is not None,
        "generated_at": row[0].isoformat() if row and row[0] else None,
        "expires_at": row[1].isoformat() if row and row[1] else None,
        "expired": bool(row) and token is None,
    }
