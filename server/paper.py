"""Paper-trading service backed by stored market bars; never places broker orders."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import duckdb


def _latest_price(conn: duckdb.DuckDBPyConnection, symbol: str, expiry: str,
                  strike: float, option_type: str) -> float:
    row = conn.execute(
        """SELECT close FROM option_bars
           WHERE underlying=? AND expiry=? AND strike=? AND option_type=? AND close IS NOT NULL
           ORDER BY timestamp DESC LIMIT 1""",
        [symbol, expiry, strike, option_type],
    ).fetchone()
    if row is None:
        raise ValueError("No option price is available for this contract")
    return float(row[0])


def list_positions(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        """SELECT position_id, symbol, expiry, strike, option_type, quantity,
                  entry_price, status, opened_at
           FROM paper_positions WHERE status='open' ORDER BY opened_at DESC"""
    ).fetchall()
    fields = ("position_id", "symbol", "expiry", "strike", "option_type",
              "quantity", "entry_price", "status", "opened_at")
    return [dict(zip(fields, row)) for row in rows]


def open_position(conn: duckdb.DuckDBPyConnection, symbol: str, expiry: str,
                  strike: float, option_type: str, quantity: int) -> dict:
    symbol = symbol.strip().upper()
    option_type = option_type.strip().upper()
    if not symbol or option_type not in ("CE", "PE"):
        raise ValueError("symbol and option_type (CE or PE) are required")
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")
    price = _latest_price(conn, symbol, expiry, strike, option_type)
    position_id = str(uuid.uuid4())
    opened_at = datetime.now(timezone.utc).replace(tzinfo=None)
    conn.execute(
        """INSERT INTO paper_positions
           (position_id, symbol, expiry, strike, option_type, quantity,
            entry_price, status, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
        [position_id, symbol, expiry, strike, option_type, quantity, price, opened_at],
    )
    conn.execute(
        """INSERT INTO paper_orders
           (order_id, position_id, side, quantity, price, status, created_at)
           VALUES (?, ?, 'buy', ?, ?, 'filled', ?)""",
        [str(uuid.uuid4()), position_id, quantity, price, opened_at],
    )
    return {"position_id": position_id, "symbol": symbol, "expiry": expiry,
            "strike": strike, "option_type": option_type, "quantity": quantity,
            "entry_price": price, "status": "open", "opened_at": opened_at}


def close_position(conn: duckdb.DuckDBPyConnection, position_id: str) -> dict:
    position = conn.execute(
        """SELECT symbol, expiry, strike, option_type, quantity, entry_price
           FROM paper_positions WHERE position_id=? AND status='open'""", [position_id]
    ).fetchone()
    if position is None:
        raise ValueError("Open paper position not found")
    symbol, expiry, strike, option_type, quantity, entry_price = position
    exit_price = _latest_price(conn, symbol, str(expiry), strike, option_type)
    closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    pnl = (exit_price - entry_price) * quantity
    conn.execute(
        "UPDATE paper_positions SET status='closed', exit_price=?, pnl=?, closed_at=? WHERE position_id=?",
        [exit_price, pnl, closed_at, position_id],
    )
    conn.execute(
        """INSERT INTO paper_orders
           (order_id, position_id, side, quantity, price, status, created_at)
           VALUES (?, ?, 'sell', ?, ?, 'filled', ?)""",
        [str(uuid.uuid4()), position_id, quantity, exit_price, closed_at],
    )
    return {"position_id": position_id, "exit_price": exit_price, "pnl": pnl,
            "status": "closed", "closed_at": closed_at}
