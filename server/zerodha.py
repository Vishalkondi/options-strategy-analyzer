"""
Zerodha/Kite adapter for historical equity and option candles.

What changed and why
--------------------
1. Authentication now goes through kite_client, which prefers the token saved
   by the daily login flow. The old code read OA_KITE_ACCESS_TOKEN straight
   from .env, so a user could log in successfully through the UI and still be
   told "set OA_KITE_ACCESS_TOKEN" on the very next sync.
2. Option contracts are windowed around ATM and hard-capped. The old code
   pulled every strike of the nearest expiry -- hundreds of historical_data
   calls fired back-to-back, which Zerodha answers with rate-limit errors.
3. Calls are throttled to stay under Kite's ~3 requests/second historical limit.
4. Instrument dumps are cached in kite_client instead of re-downloaded twice
   per sync.
5. Per-contract failures are collected and reported instead of aborting the
   whole sync.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from server import kite_client
from server.config import settings

logger = logging.getLogger("zerodha")

DEMO_SYMBOLS = {"DEMOSTK"}
IST = ZoneInfo("Asia/Kolkata")


def _kite_client() -> Any:
    """Authenticated Kite client (login-flow token first, .env token second)."""
    return kite_client.get_authenticated_kite()


def _as_date(value: str | None, fallback: date) -> date:
    return date.fromisoformat(value) if value else fallback


def _normalise_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError("Symbol must be a string.")
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Symbol cannot be empty.")
    return symbol


def _candle_date(candle_timestamp):
    return candle_timestamp.date() if hasattr(candle_timestamp, "date") else candle_timestamp


def _pick_equity(instruments: list[dict], symbol: str) -> dict | None:
    """
    Match the NSE *equity* row, not an index or an ETF that happens to share
    the trading symbol. Tolerates instrument dicts that omit the optional
    keys (the test fakes do).
    """
    for item in instruments:
        if str(item.get("tradingsymbol", "")).strip().upper() != symbol:
            continue
        instrument_type = item.get("instrument_type")
        segment = item.get("segment")
        if instrument_type not in (None, "EQ"):
            continue
        if segment not in (None, "NSE"):
            continue
        return item
    return None


def _select_contracts(
    option_instruments: list[dict],
    expiry: str | None,
    strikes: list[float] | None,
    spot: float | None,
    trading_date: date,
) -> tuple[list[dict], list[str]]:
    """Narrow the option universe to something a single sync can actually fetch."""
    notes: list[str] = []

    if expiry:
        expiry_date = date.fromisoformat(expiry)
        option_instruments = [i for i in option_instruments if i.get("expiry") == expiry_date]
    else:
        future = sorted({
            i["expiry"] for i in option_instruments
            if i.get("expiry") is not None and i["expiry"] >= trading_date
        })
        if future:
            option_instruments = [i for i in option_instruments if i.get("expiry") == future[0]]
            notes.append(f"expiry defaulted to nearest available: {future[0]}")

    if strikes:
        wanted = {float(s) for s in strikes}
        option_instruments = [i for i in option_instruments if float(i.get("strike", 0)) in wanted]
    elif spot is not None and option_instruments:
        # Window around ATM instead of the whole chain.
        available = sorted({float(i.get("strike", 0)) for i in option_instruments})
        if available:
            atm = min(available, key=lambda k: abs(k - spot))
            atm_index = available.index(atm)
            window = settings.SYNC_STRIKE_WINDOW
            lo = max(0, atm_index - window)
            hi = min(len(available), atm_index + window + 1)
            keep = set(available[lo:hi])
            option_instruments = [i for i in option_instruments if float(i.get("strike", 0)) in keep]
            notes.append(
                f"strikes windowed to +/-{window} around ATM {atm:g} (spot {spot:g}); "
                "pass explicit strikes to override"
            )

    option_instruments.sort(key=lambda i: (i.get("expiry") or trading_date, float(i.get("strike", 0)),
                                           str(i.get("instrument_type"))))

    cap = settings.SYNC_MAX_CONTRACTS
    if cap and len(option_instruments) > cap:
        notes.append(
            f"contract count capped at {cap} of {len(option_instruments)} "
            "(raise OA_SYNC_MAX_CONTRACTS to fetch more)"
        )
        option_instruments = option_instruments[:cap]

    return option_instruments, notes


def sync_market_data(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    date_start: str | None = None,
    date_end: str | None = None,
    expiry: str | None = None,
    strikes: list[float] | None = None,
) -> dict[str, Any]:
    """
    Fetch daily equity and selected option-contract history from Zerodha
    into DuckDB. Real NSE symbols only -- demo symbols go through /api/import.
    """
    symbol = _normalise_symbol(symbol)
    if symbol in DEMO_SYMBOLS:
        raise ValueError(
            f"{symbol} is a demo/local symbol and cannot be synchronized from "
            "Zerodha. Use Data Manager -> Import instead."
        )

    kite = _kite_client()

    today = datetime.now(IST).date()
    start = _as_date(date_start, today - timedelta(days=365))
    end = _as_date(date_end, today)
    if start > end:
        raise ValueError(f"Start date {start} cannot be after end date {end}.")

    now = datetime.now(IST).replace(tzinfo=None)
    trading_date = now.date()
    throttle = settings.KITE_HISTORICAL_THROTTLE
    warnings: list[str] = []

    # --- equity ------------------------------------------------------------
    equity = _pick_equity(kite.instruments("NSE"), symbol)
    if equity is None:
        raise ValueError(
            f"NSE equity instrument not found for symbol {symbol!r}. "
            f"{symbol!r} must be a valid NSE trading symbol."
        )

    equity_rows = 0
    last_close: float | None = None
    candles = kite.historical_data(equity["instrument_token"], start, end, "day")
    for candle in candles:
        conn.execute(
            """INSERT OR REPLACE INTO equity_bars
               (symbol, trading_date, timestamp, bar_interval, open, high, low, close,
                prev_close, vwap, volume, turnover, total_trades, deliverable_qty,
                deliverable_pct, import_id)
               VALUES (?, ?, ?, '1d', ?, ?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL)""",
            [symbol, _candle_date(candle["date"]), candle["date"], candle["open"],
             candle["high"], candle["low"], candle["close"], candle.get("volume")],
        )
        equity_rows += 1
        last_close = candle["close"]

    if equity_rows == 0:
        warnings.append(f"Zerodha returned no equity candles for {symbol} between {start} and {end}.")

    # --- options -----------------------------------------------------------
    nfo = kite.instruments("NFO")
    option_instruments = [
        i for i in nfo
        if i.get("name") == symbol and i.get("instrument_type") in ("CE", "PE")
    ]
    if not option_instruments:
        warnings.append(f"No NFO option contracts found for {symbol}.")

    option_instruments, notes = _select_contracts(
        option_instruments, expiry, strikes, last_close, trading_date
    )
    warnings.extend(notes)

    option_rows = 0
    failed_contracts: list[str] = []

    for index, instrument in enumerate(option_instruments):
        if throttle and index:
            time.sleep(throttle)
        try:
            option_candles = kite.historical_data(
                instrument["instrument_token"], start, end, "day", oi=True
            )
        except Exception as exc:  # noqa: BLE001 -- one bad contract must not kill the sync
            label = instrument.get("tradingsymbol") or instrument.get("instrument_token")
            failed_contracts.append(f"{label}: {exc}")
            logger.warning("Skipping contract %s: %s", label, exc)
            continue

        for candle in option_candles:
            conn.execute(
                """INSERT OR REPLACE INTO option_bars
                   (underlying, timestamp, trading_date, expiry, strike, option_type,
                    bar_interval, open, high, low, close, settle, open_interest,
                    chg_in_oi, contracts, lot_size, import_id)
                   VALUES (?, ?, ?, ?, ?, ?, '1d', ?, ?, ?, ?, NULL, ?, NULL, ?, ?, NULL)""",
                [symbol, candle["date"], _candle_date(candle["date"]), instrument["expiry"],
                 instrument["strike"], instrument["instrument_type"], candle.get("open"),
                 candle.get("high"), candle.get("low"), candle.get("close"),
                 candle.get("oi"), candle.get("volume"), instrument.get("lot_size")],
            )
            option_rows += 1

    if failed_contracts:
        warnings.append(f"{len(failed_contracts)} contract(s) failed and were skipped.")

    return {
        "symbol": symbol,
        "equity_rows": equity_rows,
        "option_rows": option_rows,
        "contracts_requested": len(option_instruments),
        "contracts_failed": failed_contracts[:10],
        "date_start": str(start),
        "date_end": str(end),
        "warnings": warnings,
        "synced_at": now.isoformat(),
    }
