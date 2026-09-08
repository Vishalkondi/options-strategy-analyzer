"""
Live capture: makes the database the source of truth for everything the
running application sees and does.

What was missing before
-----------------------
The live path built 1-minute bars in memory, fed them to the strategy, and
discarded them. Only `paper_trades` rows survived a restart. Signals were
broadcast to a websocket and lost. `live_ticks` existed in the schema but was
never written to. P&L existed only as numbers the frontend recomputed.

So: signals were produced but not recorded, ticks were seen but not kept, and
closing the browser lost everything that had not become a trade.

What this module does
---------------------
Sits between the existing LiveDataService and DuckDB. It does not open a second
Kite connection, does not re-implement bar building, and does not create a
parallel trade system. It persists what the existing pipeline already produces:

    KiteTicker -> LiveDataService -> capture.on_tick()        -> live_ticks
                                  -> capture.on_bar()         -> live_market_data
                       signals.py -> capture.record_signal()  -> strategy_signals
                                     capture.snapshot_pnl()   -> pnl_snapshots
                                     capture.log_event()      -> system_events

Writes go through BatchWriter, so nothing touches the database on the Kite
callback thread.

Capture runs independently of the frontend. Closing React changes nothing;
the ticker, the strategy and these writers keep running.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import date, datetime

from server.batch_writer import BatchWriter
from server.config import settings
from server.database import get_database

logger = logging.getLogger("capture")

VALID_SOURCES = {"kite", "replay", "csv", "manual"}


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now()


class CaptureService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, str] = {}      # symbol -> session_id
        self._session_source: dict[str, str] = {}
        self._tick_counts: dict[str, int] = {}
        self._last_tick_at: datetime | None = None
        self._last_tick_symbol: str | None = None
        self.enabled = True

        self._tick_writer = BatchWriter(
            name="live_ticks",
            flush_fn=self._flush_ticks,
            batch_size=settings.CAPTURE_BATCH_SIZE,
            flush_interval=settings.CAPTURE_FLUSH_INTERVAL,
            max_buffer=settings.CAPTURE_MAX_BUFFER,
            on_error=lambda msg: self.log_event("database", "ERROR", "tick_write_failed", msg),
        )
        self._bar_writer = BatchWriter(
            name="live_market_data",
            flush_fn=self._flush_bars,
            batch_size=max(1, settings.CAPTURE_BATCH_SIZE // 10),
            flush_interval=settings.CAPTURE_FLUSH_INTERVAL,
            max_buffer=settings.CAPTURE_MAX_BUFFER,
            on_error=lambda msg: self.log_event("database", "ERROR", "bar_write_failed", msg),
        )

    # -- lifecycle ---------------------------------------------------------

    def start_writers(self) -> None:
        self._tick_writer.start()
        self._bar_writer.start()

    def stop_writers(self) -> None:
        """Drains buffers, so a clean shutdown keeps the last partial batch."""
        self._tick_writer.stop(drain=True)
        self._bar_writer.stop(drain=True)

    def start(self, symbol: str, source: str = "kite", conn=None) -> dict:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if source not in VALID_SOURCES:
            raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}")

        conn = conn or get_database()
        with self._lock:
            if symbol in self._sessions:
                raise ValueError(f"Capture already running for {symbol}. Stop it first.")
            session_id = str(uuid.uuid4())
            self._sessions[symbol] = session_id
            self._session_source[symbol] = source
            self._tick_counts[session_id] = 0

        conn.execute(
            """INSERT INTO capture_sessions
               (session_id, symbol, source, bar_interval, started_at, bars_captured, status)
               VALUES (?, ?, ?, '1m', ?, 0, 'RUNNING')""",
            [session_id, symbol, source, datetime.now()],
        )
        self.start_writers()
        self.log_event("capture", "INFO", "capture_started",
                       f"{symbol} via {source}", {"session_id": session_id})
        return self.session_status(session_id, conn=conn)

    def stop(self, symbol: str, conn=None) -> dict:
        symbol = (symbol or "").strip().upper()
        with self._lock:
            session_id = self._sessions.pop(symbol, None)
            self._session_source.pop(symbol, None)
        if session_id is None:
            raise ValueError(f"No capture running for {symbol}.")

        # Flush before reporting counts, so the numbers reflect what is on disk.
        self._tick_writer.flush()
        self._bar_writer.flush()

        conn = conn or get_database()
        stored = conn.execute(
            "SELECT COUNT(*) FROM live_market_data WHERE session_id = ?", [session_id]
        ).fetchone()[0]
        conn.execute(
            """UPDATE capture_sessions
               SET stopped_at = ?, status = 'STOPPED', bars_captured = ?
               WHERE session_id = ?""",
            [datetime.now(), stored, session_id],
        )
        self.log_event("capture", "INFO", "capture_stopped", symbol,
                       {"session_id": session_id, "bars": stored})
        return self.session_status(session_id, conn=conn)

    def stop_all(self, conn=None) -> list[dict]:
        out = []
        for symbol in list(self._sessions):
            try:
                out.append(self.stop(symbol, conn=conn))
            except ValueError:
                continue
        return out

    def is_capturing(self, symbol: str) -> bool:
        return (symbol or "").strip().upper() in self._sessions

    def session_for(self, symbol: str) -> str | None:
        return self._sessions.get((symbol or "").strip().upper())

    # -- ingest (called from the Kite callback thread; must not block) -----

    def on_tick(self, symbol: str, tick: dict, source: str = "kite") -> None:
        """
        Buffer one raw tick. Returns in microseconds and never raises -- the
        Kite callback must not be delayed or killed by capture.
        """
        if not self.enabled:
            return
        symbol = (symbol or "").strip().upper()
        session_id = self._sessions.get(symbol)
        if session_id is None:
            return

        try:
            depth = tick.get("depth") or {}
            bid_price = ask_price = None
            if isinstance(depth, dict):
                buy, sell = depth.get("buy") or [], depth.get("sell") or []
                if buy and isinstance(buy[0], dict):
                    bid_price = buy[0].get("price")
                if sell and isinstance(sell[0], dict):
                    ask_price = sell[0].get("price")

            ohlc = tick.get("ohlc") or {}
            ts = _as_datetime(tick.get("exchange_timestamp") or tick.get("last_trade_time"))

            self._last_tick_at = datetime.now()
            self._last_tick_symbol = symbol
            with self._lock:
                self._tick_counts[session_id] = self._tick_counts.get(session_id, 0) + 1

            self._tick_writer.append((
                symbol, ts,
                float(tick.get("last_price") or 0.0),
                tick.get("volume_traded"),
                tick.get("instrument_token"),
                tick.get("last_quantity"),
                tick.get("volume_traded"),
                tick.get("average_price"),
                ohlc.get("open"), ohlc.get("high"), ohlc.get("low"), ohlc.get("close"),
                tick.get("oi"), tick.get("oi_day_high"), tick.get("oi_day_low"),
                tick.get("total_buy_quantity"), tick.get("total_sell_quantity"),
                bid_price, ask_price,
                json.dumps(depth, default=str) if depth else None,
                source, session_id, datetime.now(),
            ))
        except Exception as exc:  # noqa: BLE001 -- never propagate into the callback
            logger.error("on_tick failed for %s: %s", symbol, exc)

    def on_bar(self, symbol: str, bar: dict, source: str = "kite",
               instrument_token: int | None = None, open_interest: int | None = None) -> None:
        """Buffer one finished normalized bar for live_market_data."""
        if not self.enabled:
            return
        symbol = (symbol or "").strip().upper()
        session_id = self._sessions.get(symbol)
        if session_id is None:
            return
        try:
            ts = _as_datetime(bar.get("ts"))
            open_, close = float(bar["open"]), float(bar["close"])
            high = max(float(bar.get("high", open_)), open_, close)
            low = min(float(bar.get("low", open_)), open_, close)
            # unique_key is what makes re-recording the same minute a no-op,
            # so reconnects and restarts cannot duplicate bars.
            unique_key = f"{symbol}|{ts.isoformat()}|{source}"
            self._bar_writer.append((
                ts, symbol, open_, high, low, close,
                int(bar.get("volume") or 0), source, unique_key,
                open_interest, instrument_token, "1m", session_id,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.error("on_bar failed for %s: %s", symbol, exc)

    # -- flush functions (writer thread only) ------------------------------

    def _flush_ticks(self, batch: list[tuple]) -> int:
        conn = get_database()
        conn.executemany(
            """INSERT OR IGNORE INTO live_ticks
               (symbol, ts, ltp, volume, instrument_token, last_quantity, volume_traded,
                average_price, day_open, day_high, day_low, day_close, open_interest,
                oi_day_high, oi_day_low, buy_quantity, sell_quantity, bid_price,
                ask_price, market_depth, source, session_id, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        return len(batch)

    def _flush_bars(self, batch: list[tuple]) -> int:
        conn = get_database()
        written = 0
        for row in batch:
            next_id = conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM live_market_data"
            ).fetchone()[0]
            conn.execute(
                """INSERT OR IGNORE INTO live_market_data
                   (id, timestamp, symbol, open, high, low, close, volume, source,
                    unique_key, open_interest, instrument_token, bar_interval, session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (next_id, *row),
            )
            written += 1
        return written

    # -- signals, P&L, events ---------------------------------------------

    def record_signal(self, symbol: str, strategy_id: str, action: str, *,
                      strategy_version: int | None = None, run_id: str | None = None,
                      paper_trade_id: str | None = None, side: str | None = None,
                      price: float | None = None, signal_ts=None, reason: str | None = None,
                      metadata: dict | None = None, source: str = "live", conn=None) -> str:
        """
        Persist a strategy signal. Written synchronously, not buffered:
        signals are low-volume and losing one to a crashed buffer would break
        the audit trail that explains why a trade exists.
        """
        signal_id = str(uuid.uuid4())
        try:
            conn = conn or get_database()
            conn.execute(
                """INSERT INTO strategy_signals
                   (signal_id, symbol, strategy_id, strategy_version, run_id, paper_trade_id,
                    action, side, price, signal_ts, reason, metadata, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [signal_id, (symbol or "").strip().upper(), strategy_id, strategy_version,
                 run_id, paper_trade_id, action, side, price,
                 _as_datetime(signal_ts), reason,
                 json.dumps(metadata, default=str) if metadata else None, source],
            )
        except Exception as exc:  # noqa: BLE001 -- must not break signal evaluation
            logger.error("Failed to persist signal for %s: %s", symbol, exc)
            self.log_event("strategy", "ERROR", "signal_persist_failed", str(exc))
        return signal_id

    def snapshot_pnl(self, scope: str = "live", strategy_id: str | None = None,
                     run_id: str | None = None, symbol: str | None = None,
                     capital: float | None = None, conn=None) -> dict:
        """
        Write a point-in-time P&L row so history can be reconstructed without
        recomputing from trades and without depending on frontend state.

        Realized P&L comes from closed paper trades. Unrealized is marked
        against the latest captured price for the symbol -- and note the
        existing limitation: live P&L tracks the underlying's move, not the
        real spread premium.
        """
        conn = conn or get_database()
        where, args = ["status = 'CLOSED'"], []
        if strategy_id:
            where.append("strategy_id = ?")
            args.append(strategy_id)
        if symbol:
            where.append("watch_symbol = ?")
            args.append(symbol.strip().upper())
        clause = " AND ".join(where)

        realized = conn.execute(
            f"SELECT COALESCE(SUM(net_pnl), 0), COUNT(*) FROM paper_trades WHERE {clause}", args
        ).fetchone()

        open_clause = clause.replace("status = 'CLOSED'", "status = 'OPEN'")
        open_rows = conn.execute(
            f"""SELECT watch_symbol, side, entry_price
                FROM paper_trades WHERE {open_clause}""", args
        ).fetchall()

        unrealized = 0.0
        for watch_symbol, side, entry_price in open_rows:
            latest = conn.execute(
                "SELECT close FROM live_market_data WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
                [watch_symbol],
            ).fetchone()
            if latest and entry_price:
                move = float(latest[0]) - float(entry_price)
                unrealized += move if side == "bull" else -move

        realized_pnl = float(realized[0] or 0.0)
        total = realized_pnl + unrealized
        return_pct = (total / capital * 100) if capital else None

        snapshot_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO pnl_snapshots
               (snapshot_id, snapshot_ts, scope, strategy_id, run_id, symbol,
                realized_pnl, unrealized_pnl, total_pnl, open_positions,
                closed_positions, capital, return_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [snapshot_id, datetime.now(), scope, strategy_id, run_id, symbol,
             round(realized_pnl, 2), round(unrealized, 2), round(total, 2),
             len(open_rows), realized[1], capital, return_pct],
        )
        return {
            "snapshot_id": snapshot_id,
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total_pnl": round(total, 2),
            "open_positions": len(open_rows),
            "closed_positions": realized[1],
            "capital": capital,
            "return_pct": return_pct,
        }

    def log_event(self, category: str, severity: str, event: str,
                  detail: str | None = None, metadata: dict | None = None,
                  conn=None) -> None:
        """Operational audit trail. Errors belong in the database, not only stdout."""
        try:
            conn = conn or get_database()
            conn.execute(
                """INSERT INTO system_events
                   (event_id, event_ts, category, severity, event, detail, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [str(uuid.uuid4()), datetime.now(), category, severity, event,
                 (detail or "")[:2000],
                 json.dumps(metadata, default=str) if metadata else None],
            )
        except Exception as exc:  # noqa: BLE001 -- logging must never break the caller
            logger.error("Failed to write system event %s/%s: %s", category, event, exc)

    # -- reporting ---------------------------------------------------------

    def session_status(self, session_id: str, conn=None) -> dict:
        conn = conn or get_database()
        row = conn.execute(
            """SELECT session_id, symbol, source, bar_interval, started_at,
                      stopped_at, bars_captured, status
               FROM capture_sessions WHERE session_id = ?""",
            [session_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown capture session {session_id}")

        ticks = conn.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM live_ticks WHERE session_id = ?",
            [session_id],
        ).fetchone()
        bars = conn.execute(
            "SELECT COUNT(*) FROM live_market_data WHERE session_id = ?", [session_id]
        ).fetchone()[0]

        return {
            "session_id": row[0], "symbol": row[1], "source": row[2],
            "bar_interval": row[3],
            "started_at": _iso(row[4]), "stopped_at": _iso(row[5]),
            "status": row[7],
            "ticks_stored": ticks[0],
            "first_tick": _iso(ticks[1]), "last_tick": _iso(ticks[2]),
            "bars_stored": bars,
            "ticks_received": self._tick_counts.get(session_id, 0),
        }

    def status(self, conn=None) -> dict:
        """Everything the Live Monitor needs to show real capture state."""
        conn = conn or get_database()
        active = []
        for symbol, session_id in list(self._sessions.items()):
            try:
                active.append(self.session_status(session_id, conn=conn))
            except Exception:  # noqa: BLE001
                continue

        totals = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol), MAX(ts) FROM live_ticks"
        ).fetchone()
        bar_totals = conn.execute(
            "SELECT COUNT(*), MAX(timestamp) FROM live_market_data"
        ).fetchone()

        tick_stats = self._tick_writer.stats()
        bar_stats = self._bar_writer.stats()
        last_write = max(
            [t for t in (tick_stats["last_write_at"], bar_stats["last_write_at"]) if t],
            default=None,
        )

        return {
            "enabled": self.enabled,
            "capturing": bool(active),
            "active_sessions": active,
            "last_tick_at": _iso(self._last_tick_at),
            "last_tick_symbol": self._last_tick_symbol,
            "last_db_write_at": datetime.fromtimestamp(last_write).isoformat() if last_write else None,
            "totals": {
                "ticks": totals[0],
                "symbols": totals[1],
                "latest_tick_ts": _iso(totals[2]),
                "bars": bar_totals[0],
                "latest_bar_ts": _iso(bar_totals[1]),
            },
            "writers": {"ticks": tick_stats, "bars": bar_stats},
        }

    def recent_events(self, limit: int = 50, severity: str | None = None, conn=None) -> list[dict]:
        conn = conn or get_database()
        query = """SELECT event_ts, category, severity, event, detail
                   FROM system_events"""
        args: list = []
        if severity:
            query += " WHERE severity = ?"
            args.append(severity.upper())
        query += " ORDER BY event_ts DESC LIMIT ?"
        args.append(min(int(limit), 500))
        return [{
            "event_ts": _iso(r[0]), "category": r[1], "severity": r[2],
            "event": r[3], "detail": r[4],
        } for r in conn.execute(query, args).fetchall()]

    # -- retention ---------------------------------------------------------

    def purge_ticks(self, older_than_days: int, conn=None) -> dict:
        """
        Delete raw ticks older than N days.

        Only `live_ticks` is ever purged. Bars, signals, trades, positions and
        P&L snapshots are small and are the record you actually need later --
        raw ticks are the only table that grows fast enough to require it.
        Explicit call only; nothing deletes data on a timer.
        """
        if older_than_days < 1:
            raise ValueError("older_than_days must be at least 1")
        conn = conn or get_database()
        before = conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0]
        conn.execute(
            f"DELETE FROM live_ticks WHERE ts < (current_timestamp - INTERVAL {int(older_than_days)} DAY)"
        )
        after = conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0]
        deleted = before - after
        self.log_event("capture", "INFO", "ticks_purged",
                       f"Deleted {deleted} ticks older than {older_than_days} days")
        return {"deleted": deleted, "remaining": after, "older_than_days": older_than_days}


capture_service = CaptureService()
