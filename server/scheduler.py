"""
Scheduled capture: run a real market-data capture every 30 minutes for as long
as the backend is running.

    backend starts -> scheduler starts -> capture -> write records
                   -> wait 30 min -> capture -> write records -> repeat

Design decisions, and why
-------------------------
1. **Real data only.** A cycle fetches live quotes from Zerodha through the
   existing kite_client. If Kite is not configured or not authenticated, the
   cycle is recorded as FAILED with the reason. It does NOT fall back to
   simulated or demo prices. A scheduler that quietly writes fabricated rows
   every 30 minutes would poison the database with data indistinguishable from
   real captures, and you would not find out until you traded on it.

2. **Every cycle is recorded, including failures.** A missing row and a failed
   row look identical from the outside, so a failed cycle writes a row with its
   error rather than writing nothing.

3. **Retry inside the cycle, not by rescheduling.** Transient network faults get
   a few attempts with exponential backoff. If they all fail, the cycle is
   marked FAILED and the schedule continues to the next slot -- a bad half-hour
   never delays the next one.

4. **Fixed schedule, not drift.** The next run is computed from the cycle's
   scheduled time, not from when the previous one finished, so a slow cycle
   does not push the whole schedule later and later.

5. **Independent of the frontend.** This is an asyncio task owned by the app
   lifespan. Closing or refreshing React has no effect on it.

6. **Deduplication is the database's job.** Bars carry a unique_key and ticks a
   (symbol, ts) key, so re-capturing the same minute inserts nothing. Historical
   captures are never overwritten -- every cycle appends.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, time as dtime, timedelta, timezone

from server import kite_client
from server.capture import capture_service
from server.config import settings
from server.database import get_database

logger = logging.getLogger("scheduler")

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)


def market_is_open(now: datetime | None = None) -> bool:
    """NSE equity hours, Monday to Friday. Holidays are not accounted for."""
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    if now_ist.weekday() >= 5:
        return False
    return MARKET_OPEN <= now_ist.time() <= MARKET_CLOSE


class CaptureScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._cycle_number = 0
        self.last_cycle: dict | None = None
        self.next_run_at: datetime | None = None
        self._lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> bool:
        if not settings.SCHEDULER_ENABLED:
            logger.info("Capture scheduler disabled (OA_SCHEDULER_ENABLED=false)")
            return False
        if self.running:
            return True
        self._running = True
        self._cycle_number = self._last_cycle_number()
        self._task = asyncio.create_task(self._loop())
        logger.info("Capture scheduler started (every %.0f minutes)",
                    settings.SCHEDULER_INTERVAL_SECONDS / 60)
        capture_service.log_event(
            "scheduler", "INFO", "scheduler_started",
            f"interval {settings.SCHEDULER_INTERVAL_SECONDS / 60:.0f} minutes")
        return True

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        capture_service.log_event("scheduler", "INFO", "scheduler_stopped")

    def _last_cycle_number(self) -> int:
        try:
            row = get_database().execute(
                "SELECT COALESCE(MAX(cycle_number), 0) FROM capture_cycles"
            ).fetchone()
            return int(row[0] or 0)
        except Exception:  # noqa: BLE001
            return 0

    # -- the loop ----------------------------------------------------------

    async def _loop(self) -> None:
        interval = settings.SCHEDULER_INTERVAL_SECONDS

        if settings.SCHEDULER_RUN_ON_STARTUP:
            # Proves at boot that capture works, instead of leaving you to
            # wonder for 30 minutes whether the scheduler is alive.
            try:
                await self.run_cycle(trigger="startup")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Startup capture failed: %s", exc)

        scheduled = datetime.now() + timedelta(seconds=interval)
        while self._running:
            self.next_run_at = scheduled
            delay = max(0.0, (scheduled - datetime.now()).total_seconds())
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise

            if not self._running:
                break

            try:
                await self.run_cycle(trigger="scheduler", scheduled_at=scheduled)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                # The loop must outlive any single cycle. One bad cycle must
                # never end the scheduler for the rest of the process's life.
                logger.exception("Capture cycle raised: %s", exc)

            # Advance from the scheduled time so a slow cycle does not push the
            # whole schedule later. Skip forward if we fell more than a slot behind.
            scheduled += timedelta(seconds=interval)
            now = datetime.now()
            while scheduled <= now:
                scheduled += timedelta(seconds=interval)

    # -- one cycle ---------------------------------------------------------

    async def run_cycle(self, trigger: str = "manual",
                        scheduled_at: datetime | None = None) -> dict:
        """
        Run one capture cycle. Always writes a capture_cycles row, whether it
        succeeded or failed.
        """
        async with self._lock:   # never two cycles at once
            return await asyncio.to_thread(self._run_cycle_sync, trigger, scheduled_at)

    def _symbols(self, conn) -> list[str]:
        """Watchlist symbols first, then the configured dashboard list."""
        symbols: list[str] = []
        try:
            rows = conn.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()
            symbols = [r[0] for r in rows if r[0]]
        except Exception:  # noqa: BLE001
            pass
        for symbol in settings.SCHEDULER_SYMBOLS or settings.LIVE_MARKET_SYMBOLS:
            if symbol.upper() not in symbols:
                symbols.append(symbol.upper())
        return symbols

    def _run_cycle_sync(self, trigger: str, scheduled_at: datetime | None) -> dict:
        conn = get_database()
        cycle_id = str(uuid.uuid4())
        self._cycle_number += 1
        cycle_number = self._cycle_number
        started_at = datetime.now()
        scheduled_at = scheduled_at or started_at
        is_open = market_is_open()

        symbols = self._symbols(conn)

        # Row goes in immediately with status RUNNING, so a cycle that crashes
        # the process still leaves evidence that it was attempted.
        conn.execute(
            """INSERT INTO capture_cycles
               (cycle_id, cycle_number, scheduled_at, started_at, status, trigger,
                symbols_requested, market_open)
               VALUES (?, ?, ?, ?, 'RUNNING', ?, ?, ?)""",
            [cycle_id, cycle_number, scheduled_at, started_at, trigger,
             len(symbols), is_open],
        )

        counts = {"ticks": 0, "bars": 0, "options": 0, "signals": 0, "pnl": 0}
        detail: dict = {"symbols": {}}
        captured = 0
        error: str | None = None
        attempts = 0

        try:
            quotes, attempts = self._fetch_with_retry(symbols)
            before = self._row_counts(conn)

            for symbol in symbols:
                payload = quotes.get(f"NSE:{symbol}")
                if not payload:
                    detail["symbols"][symbol] = "no quote returned"
                    continue
                try:
                    self._persist_quote(symbol, payload, cycle_id)
                    captured += 1
                    detail["symbols"][symbol] = {
                        "last_price": payload.get("last_price"),
                        "volume": payload.get("volume"),
                        "oi": payload.get("oi"),
                    }
                except Exception as exc:  # noqa: BLE001 -- one symbol must not kill the cycle
                    detail["symbols"][symbol] = f"persist failed: {exc}"
                    logger.warning("Persist failed for %s: %s", symbol, exc)

            # Flush the buffered writers so this cycle's counts reflect disk.
            capture_service._tick_writer.flush()
            capture_service._bar_writer.flush()

            # P&L snapshot: applicable whenever positions exist.
            try:
                if conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]:
                    capture_service.snapshot_pnl("live")
                    counts["pnl"] = 1
            except Exception as exc:  # noqa: BLE001
                detail["pnl_error"] = str(exc)

            after = self._row_counts(conn)
            counts["ticks"] = after["ticks"] - before["ticks"]
            counts["bars"] = after["bars"] - before["bars"]
            counts["options"] = after["options"] - before["options"]
            counts["signals"] = after["signals"] - before["signals"]

            status = "SUCCESS" if captured == len(symbols) and symbols else (
                "PARTIAL" if captured else "FAILED")
            if not symbols:
                status = "FAILED"
                error = "No symbols configured to capture."
            elif captured == 0 and error is None:
                error = "No quotes returned for any symbol."

        except (kite_client.KiteConfigError, kite_client.KiteAuthError) as exc:
            # The expected failure when credentials are missing or expired.
            # Recorded as a failed cycle -- never substituted with fake data.
            status = "FAILED"
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            status = "FAILED"
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("Capture cycle %d failed", cycle_number)

        finished_at = datetime.now()
        total = sum(counts.values())
        conn.execute(
            """UPDATE capture_cycles
               SET finished_at = ?, duration_ms = ?, status = ?, attempts = ?,
                   symbols_captured = ?, ticks_inserted = ?, bars_inserted = ?,
                   option_rows_inserted = ?, signals_inserted = ?,
                   pnl_snapshots_inserted = ?, total_records = ?, error = ?, detail = ?
               WHERE cycle_id = ?""",
            [finished_at, int((finished_at - started_at).total_seconds() * 1000),
             status, max(attempts, 1), captured, counts["ticks"], counts["bars"],
             counts["options"], counts["signals"], counts["pnl"], total,
             error, json.dumps(detail, default=str)[:4000], cycle_id],
        )

        capture_service.log_event(
            "scheduler",
            "INFO" if status == "SUCCESS" else ("WARNING" if status == "PARTIAL" else "ERROR"),
            f"cycle_{status.lower()}",
            f"cycle #{cycle_number}: {total} records from {captured}/{len(symbols)} symbols"
            + (f" -- {error}" if error else ""),
            {"cycle_id": cycle_id, "counts": counts},
        )

        result = {
            "cycle_id": cycle_id, "cycle_number": cycle_number, "status": status,
            "trigger": trigger, "market_open": is_open,
            "scheduled_at": scheduled_at.isoformat(),
            "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
            "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
            "attempts": max(attempts, 1),
            "symbols_requested": len(symbols), "symbols_captured": captured,
            "records": counts, "total_records": total, "error": error,
        }
        self.last_cycle = result
        logger.info("Capture cycle #%d %s: %d records (%d/%d symbols)%s",
                    cycle_number, status, total, captured, len(symbols),
                    f" -- {error}" if error else "")
        return result

    def _fetch_with_retry(self, symbols: list[str]) -> tuple[dict, int]:
        """
        Fetch quotes, retrying transient upstream faults with backoff.

        Config and auth errors are NOT retried: a missing API key will still be
        missing in four seconds, and retrying just delays the honest failure.
        """
        import time as _time
        if not symbols:
            return {}, 1

        last_exc: Exception | None = None
        for attempt in range(1, settings.SCHEDULER_MAX_RETRIES + 1):
            try:
                return kite_client.quote([f"NSE:{s}" for s in symbols]), attempt
            except (kite_client.KiteConfigError, kite_client.KiteAuthError):
                raise
            except Exception as exc:  # noqa: BLE001 -- network / upstream, worth retrying
                last_exc = exc
                if attempt < settings.SCHEDULER_MAX_RETRIES:
                    backoff = settings.SCHEDULER_RETRY_BACKOFF * (2 ** (attempt - 1))
                    logger.warning("Quote fetch attempt %d failed (%s); retrying in %.1fs",
                                   attempt, exc, backoff)
                    _time.sleep(backoff)
        raise last_exc if last_exc else RuntimeError("quote fetch failed")

    def _persist_quote(self, symbol: str, payload: dict, cycle_id: str) -> None:
        """Turn one Kite quote into a tick row and a bar row, via capture."""
        if not capture_service.is_capturing(symbol):
            capture_service.start(symbol, source="kite")

        ohlc = payload.get("ohlc") or {}
        depth = payload.get("depth") or {}
        ts = payload.get("last_trade_time") or payload.get("timestamp") or datetime.now()
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                ts = datetime.now()

        capture_service.on_tick(symbol, {
            "instrument_token": payload.get("instrument_token"),
            "last_price": payload.get("last_price"),
            "last_quantity": payload.get("last_quantity"),
            "volume_traded": payload.get("volume"),
            "average_price": payload.get("average_price"),
            "exchange_timestamp": ts,
            "ohlc": ohlc,
            "oi": payload.get("oi"),
            "oi_day_high": payload.get("oi_day_high"),
            "oi_day_low": payload.get("oi_day_low"),
            "total_buy_quantity": payload.get("buy_quantity"),
            "total_sell_quantity": payload.get("sell_quantity"),
            "depth": depth,
        }, source="kite")

        price = float(payload.get("last_price") or 0.0)
        if price:
            # A quote is a point in time; the bar it produces is that minute's
            # snapshot. unique_key makes a repeat within the same minute a no-op.
            capture_service.on_bar(symbol, {
                "ts": ts.replace(second=0, microsecond=0),
                "open": float(ohlc.get("open") or price),
                "high": float(ohlc.get("high") or price),
                "low": float(ohlc.get("low") or price),
                "close": price,
                "volume": int(payload.get("volume") or 0),
            }, source="kite",
                instrument_token=payload.get("instrument_token"),
                open_interest=payload.get("oi"))

    @staticmethod
    def _row_counts(conn) -> dict:
        def count(table: str) -> int:
            try:
                return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:  # noqa: BLE001
                return 0
        return {
            "ticks": count("live_ticks"),
            "bars": count("live_market_data"),
            "options": count("option_bars"),
            "signals": count("strategy_signals"),
        }

    # -- reporting ---------------------------------------------------------

    def status(self, conn=None) -> dict:
        conn = conn or get_database()
        row = conn.execute(
            """SELECT cycle_id, cycle_number, started_at, finished_at, status,
                      total_records, symbols_captured, symbols_requested, error
               FROM capture_cycles ORDER BY started_at DESC LIMIT 1"""
        ).fetchone()

        totals = conn.execute(
            """SELECT COUNT(*),
                      SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END),
                      COALESCE(SUM(total_records), 0)
               FROM capture_cycles"""
        ).fetchone()

        return {
            "running": self.running,
            "enabled": settings.SCHEDULER_ENABLED,
            "interval_minutes": settings.SCHEDULER_INTERVAL_SECONDS / 60,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "market_open": market_is_open(),
            "cycles_total": totals[0],
            "cycles_succeeded": int(totals[1] or 0),
            "cycles_failed": int(totals[2] or 0),
            "records_captured_total": int(totals[3] or 0),
            "last_cycle": {
                "cycle_id": row[0], "cycle_number": row[1],
                "started_at": row[2].isoformat() if row[2] else None,
                "finished_at": row[3].isoformat() if row[3] else None,
                "status": row[4], "total_records": row[5],
                "symbols_captured": row[6], "symbols_requested": row[7],
                "error": row[8],
            } if row else None,
        }

    def history(self, limit: int = 50, conn=None) -> list[dict]:
        conn = conn or get_database()
        rows = conn.execute(
            """SELECT cycle_id, cycle_number, scheduled_at, started_at, finished_at,
                      duration_ms, status, trigger, attempts, symbols_requested,
                      symbols_captured, ticks_inserted, bars_inserted,
                      option_rows_inserted, signals_inserted, pnl_snapshots_inserted,
                      total_records, market_open, error
               FROM capture_cycles ORDER BY started_at DESC LIMIT ?""",
            [min(int(limit), 500)],
        ).fetchall()
        columns = ["cycle_id", "cycle_number", "scheduled_at", "started_at", "finished_at",
                   "duration_ms", "status", "trigger", "attempts", "symbols_requested",
                   "symbols_captured", "ticks_inserted", "bars_inserted",
                   "option_rows_inserted", "signals_inserted", "pnl_snapshots_inserted",
                   "total_records", "market_open", "error"]
        return [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                 for k, v in zip(columns, row)} for row in rows]


capture_scheduler = CaptureScheduler()
