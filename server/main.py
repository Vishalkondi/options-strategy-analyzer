
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from server.config import settings
from server.database import get_database
from server.engine import run_backtest
from server import costs as cost_model
from server import metrics as metrics_module
from server.live_market import live_market_service
from server.live_data_service import live_data_service
from server.ingest import ingest_path
from server.paper import close_position, list_positions, open_position
from server.strategy_debit_spread import StrategyParams
from server.xapi import fetch_symbol_sentiment
from server.zerodha import sync_market_data
from server import kite_client, token_store, ws_relay
from server.kite_client import (
    KiteAuthError,
    KiteConfigError,
    KiteRateLimitError,
    KiteUpstreamError,
)
from server.live_service import LiveRecord, live_service
from server.replay import replay_service
from server.capture import capture_service
from server.scheduler import capture_scheduler
from server.live_csv_watcher import live_csv_watcher

logger = logging.getLogger("api")


async def _pnl_snapshot_loop() -> None:
    """
    Periodic P&L snapshots, independent of the frontend.

    P&L history must not depend on a browser being open, so this runs on the
    backend whether or not anyone is watching. Failures are logged and the loop
    continues -- a bad snapshot must not stop future ones.
    """
    interval = settings.PNL_SNAPSHOT_INTERVAL
    while True:
        try:
            await asyncio.sleep(interval)
            has_positions = get_database().execute(
                "SELECT COUNT(*) FROM paper_trades"
            ).fetchone()[0]
            if has_positions:
                await asyncio.to_thread(capture_service.snapshot_pnl, "live")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("P&L snapshot failed: %s", exc)
            capture_service.log_event("capture", "ERROR", "pnl_snapshot_failed", str(exc))


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Starting the ticker here is best-effort: with no Kite token yet it logs a
    warning and returns, and the login callback starts it later. A missing
    token must never stop the backend from booting -- backtesting, imports and
    the whole UI work fine without one.
    """
    get_database()  # fail fast on a broken DB rather than on the first request
    capture_service.start_writers()
    capture_service.log_event("capture", "INFO", "backend_started",
                              f"version {settings.APP_VERSION}")
    live_data_service.start(asyncio.get_event_loop())
    live_csv_watcher.start()
    snapshot_task = asyncio.create_task(_pnl_snapshot_loop())
    # Runs for the life of the backend process. Nothing about it depends on a
    # browser being open.
    capture_scheduler.start()
    try:
        yield
    finally:
        await capture_scheduler.stop()
        snapshot_task.cancel()
        await asyncio.gather(snapshot_task, return_exceptions=True)
        await replay_service.stop()
        await live_csv_watcher.stop()
        capture_service.stop_all()
        # Drain buffers so a clean shutdown keeps the last partial batch.
        capture_service.stop_writers()
        capture_service.log_event("capture", "INFO", "backend_stopped")
        await live_market_service.stop()
        live_data_service.stop()


app = FastAPI(title="Options Strategy Analyzer", version=settings.APP_VERSION, lifespan=lifespan)

# NOTE: the old build wrapped every request in a threading.RLock middleware to
# protect DuckDB. That was a no-op (the middleware runs on the event-loop
# thread, and RLock is reentrant per thread) and it never covered the ticker
# thread, which is the one writing outside the request cycle. Thread safety now
# lives in server/database.py, where the connection actually is.

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Kite failures become meaningful HTTP codes instead of a 500 + stack trace.
# 400 = your .env is wrong, 401 = log in again, 429 = slow down, 502 = Zerodha.
# ---------------------------------------------------------------------------

def _kite_error(status: int, code: str, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": str(exc), "error": code})


@app.exception_handler(KiteConfigError)
async def _handle_kite_config_error(_: Request, exc: KiteConfigError):
    return _kite_error(400, "kite_not_configured", exc)


@app.exception_handler(KiteAuthError)
async def _handle_kite_auth_error(_: Request, exc: KiteAuthError):
    return _kite_error(401, "kite_reauth_required", exc)


@app.exception_handler(KiteRateLimitError)
async def _handle_kite_rate_limit(_: Request, exc: KiteRateLimitError):
    return _kite_error(429, "kite_rate_limited", exc)


@app.exception_handler(KiteUpstreamError)
async def _handle_kite_upstream_error(_: Request, exc: KiteUpstreamError):
    return _kite_error(502, "kite_upstream_error", exc)


class ImportRequest(BaseModel):
    """Request to import local historical/demo CSV data."""
    path: str


@app.post("/api/import")
def api_import(req: ImportRequest):
    """Import local CSV data. This endpoint never contacts Zerodha."""
    path = (req.path or "").strip()

    if not path:
        raise HTTPException(400, "Import path is required. Example: demo")

    requested_path = Path(path)
    if requested_path.is_absolute():
        raise HTTPException(400, "Import path must be relative to the raw data directory.")
    if ".." in requested_path.parts:
        raise HTTPException(400, "Invalid import path.")

    try:
        reports = ingest_path(get_database(), settings.RAW_DIR, path)
        return {
            "success": True,
            "path": path,
            "reports": [vars(report) for report in reports],
        }
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Dataset import failed: {exc}") from exc


class LiveSyncRequest(BaseModel):
    symbol: str
    date_start: str | None = None
    date_end: str | None = None
    expiry: str | None = None
    strikes: list[float] | None = None


@app.post("/api/live/sync")
def api_live_sync(req: LiveSyncRequest):
    """Synchronize real market data through Zerodha."""
    symbol = (req.symbol or "").strip().upper()

    if not symbol:
        raise HTTPException(400, "Symbol is required.")

    if symbol == "DEMOSTK":
        raise HTTPException(
            400,
            "DEMOSTK is a demo/local symbol and cannot be synchronized from Zerodha. "
            "Use /api/import with path 'demo'.",
        )

    try:
        return sync_market_data(
            get_database(),
            symbol=symbol,
            date_start=req.date_start,
            date_end=req.date_end,
            expiry=req.expiry,
            strikes=req.strikes,
        )
    except (KiteConfigError, KiteAuthError, KiteUpstreamError):
        # Handled by the typed exception handlers above -- re-raising keeps the
        # useful status code instead of flattening everything into a 400.
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Live sync failed for %s", symbol)
        raise HTTPException(502, f"Live sync failed for {symbol}: {exc}") from exc


@app.post("/api/live/record")
async def api_live_record(record: LiveRecord):
    try:
        result = await live_service.ingest(record, source="api")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"success": True, "record": result}


@app.get("/api/live/records")
def api_live_records(symbol: str | None = None, limit: int = 100):
    limit = max(1, min(limit, 1000))
    conn = get_database()
    if symbol:
        rows = conn.execute(
            "SELECT * FROM live_market_data WHERE symbol=? ORDER BY timestamp DESC, id DESC LIMIT ?",
            [symbol.strip().upper(), limit],
        ).fetchdf()
    else:
        rows = conn.execute(
            "SELECT * FROM live_market_data ORDER BY timestamp DESC, id DESC LIMIT ?", [limit]
        ).fetchdf()
    return {"records": json.loads(rows.to_json(orient="records", date_format="iso"))}


@app.get("/api/live/status")
def api_live_status():
    try:
        database_status = "connected"
        total = get_database().execute("SELECT COUNT(*) FROM live_market_data").fetchone()[0]
    except Exception as exc:
        database_status = f"error: {exc}"
        total = 0
    status = live_service.status()
    status.update({
        "connected": bool(status["websocket_clients"] or live_data_service.is_running()),
        "database": database_status,
        "total_records": total,
        "csv_watcher": {"running": live_csv_watcher.running, "directory": str(settings.LIVE_DIR),
                        "last_file": live_csv_watcher.last_file, "last_error": live_csv_watcher.last_error,
                        "invalid_rows": live_csv_watcher.invalid_rows},
        "kite": {"authenticated": token_store.token_status(get_database())["has_valid_token"],
                 "ticker_running": live_data_service.is_running()},
        "replay": replay_service.status(),
        "capture": capture_service.status(),
        "scheduler": capture_scheduler.status(),
    })
    return status


@app.websocket("/api/live/ws")
async def websocket_live_records(websocket: WebSocket):
    await live_service.connect(websocket)


# ---------------------------------------------------------------------------
# Live capture. The database is the source of truth: these endpoints read what
# was persisted, not in-memory state. All history endpoints are paginated --
# a tick table can hold millions of rows and must never be returned whole.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Scheduled capture. Every cycle is recorded in capture_cycles -- successes and
# failures alike -- so "did the 30-minute capture run?" is a database question,
# not a guess from log scrollback.
# ---------------------------------------------------------------------------

@app.get("/api/scheduler/status")
def api_scheduler_status():
    return capture_scheduler.status()


@app.get("/api/scheduler/cycles")
def api_scheduler_cycles(limit: int = 50):
    """Per-cycle audit: when it ran, how long it took, how many rows it wrote."""
    return {"cycles": capture_scheduler.history(limit=limit)}


@app.post("/api/scheduler/run-now")
async def api_scheduler_run_now():
    """Trigger a cycle immediately without waiting for the next slot."""
    return await capture_scheduler.run_cycle(trigger="manual")


class CaptureStartRequest(BaseModel):
    symbol: str
    source: str = "kite"


@app.post("/api/live/capture/start")
def api_capture_start(req: CaptureStartRequest):
    try:
        return capture_service.start(req.symbol, req.source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/live/capture/stop")
def api_capture_stop(req: CaptureStartRequest):
    try:
        return capture_service.stop(req.symbol)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/live/capture-status")
def api_capture_status():
    """Real capture state: sessions, counts, buffer depth, last DB write."""
    return capture_service.status()


@app.get("/api/live/ticks")
def api_live_ticks(symbol: str | None = None, limit: int = 100, offset: int = 0):
    limit = max(1, min(int(limit), 1000))   # hard ceiling; never return the table
    conn = get_database()
    where, args = [], []
    if symbol:
        where.append("symbol = ?")
        args.append(symbol.strip().upper())
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(f"SELECT COUNT(*) FROM live_ticks {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"""SELECT symbol, ts, ltp, last_quantity, volume_traded, average_price,
                   open_interest, buy_quantity, sell_quantity, bid_price, ask_price, source
            FROM live_ticks {clause} ORDER BY ts DESC LIMIT ? OFFSET ?""",
        [*args, limit, max(0, int(offset))],
    ).fetchall()
    columns = ["symbol", "ts", "ltp", "last_quantity", "volume_traded", "average_price",
               "open_interest", "buy_quantity", "sell_quantity", "bid_price", "ask_price", "source"]
    return {
        "total": total, "limit": limit, "offset": offset,
        "ticks": [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                   for k, v in zip(columns, row)} for row in rows],
    }


@app.get("/api/live/market-data")
def api_live_market_data(symbol: str | None = None, limit: int = 200, offset: int = 0):
    """Normalized 1-minute bars from live_market_data."""
    limit = max(1, min(int(limit), 2000))
    conn = get_database()
    where, args = [], []
    if symbol:
        where.append("symbol = ?")
        args.append(symbol.strip().upper())
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(f"SELECT COUNT(*) FROM live_market_data {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"""SELECT timestamp, symbol, open, high, low, close, volume,
                   open_interest, bar_interval, source
            FROM live_market_data {clause} ORDER BY timestamp DESC LIMIT ? OFFSET ?""",
        [*args, limit, max(0, int(offset))],
    ).fetchall()
    columns = ["timestamp", "symbol", "open", "high", "low", "close",
               "volume", "open_interest", "bar_interval", "source"]
    return {
        "total": total, "limit": limit, "offset": offset,
        "bars": [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                  for k, v in zip(columns, row)} for row in rows],
    }


@app.get("/api/live/positions")
def api_live_positions(status: str | None = None):
    """Open and closed positions from paper_trades, marked to the latest bar."""
    conn = get_database()
    clause, args = "", []
    if status:
        clause = "WHERE status = ?"
        args.append(status.upper())
    rows = conn.execute(
        f"""SELECT paper_trade_id, watch_symbol, strategy_id, side, entry_ts, entry_price,
                   exit_ts, exit_price, exit_reason, net_pnl, status
            FROM paper_trades {clause} ORDER BY entry_ts DESC LIMIT 500""",
        args,
    ).fetchall()

    positions = []
    for r in rows:
        latest = conn.execute(
            "SELECT close FROM live_market_data WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            [r[1]],
        ).fetchone()
        ltp = float(latest[0]) if latest else None
        unrealized = None
        if r[10] == "OPEN" and ltp is not None and r[5]:
            move = ltp - float(r[5])
            unrealized = round(move if r[3] == "bull" else -move, 2)
        positions.append({
            "paper_trade_id": r[0], "symbol": r[1], "strategy_id": r[2], "side": r[3],
            "entry_ts": r[4].isoformat() if r[4] else None, "entry_price": r[5],
            "exit_ts": r[6].isoformat() if r[6] else None, "exit_price": r[7],
            "exit_reason": r[8], "realized_pnl": r[9], "status": r[10],
            "ltp": ltp, "unrealized_pnl": unrealized,
        })
    return {"count": len(positions), "positions": positions}


@app.get("/api/live/pnl")
def api_live_pnl(limit: int = 100, strategy_id: str | None = None):
    """Stored P&L snapshots, newest first, plus a freshly computed current value."""
    limit = max(1, min(int(limit), 1000))
    conn = get_database()
    clause, args = "", []
    if strategy_id:
        clause = "WHERE strategy_id = ?"
        args.append(strategy_id)
    rows = conn.execute(
        f"""SELECT snapshot_ts, scope, strategy_id, symbol, realized_pnl,
                   unrealized_pnl, total_pnl, open_positions, closed_positions, return_pct
            FROM pnl_snapshots {clause} ORDER BY snapshot_ts DESC LIMIT ?""",
        [*args, limit],
    ).fetchall()
    columns = ["snapshot_ts", "scope", "strategy_id", "symbol", "realized_pnl",
               "unrealized_pnl", "total_pnl", "open_positions", "closed_positions", "return_pct"]
    return {
        "current": capture_service.snapshot_pnl("live", strategy_id=strategy_id),
        "snapshots": [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                       for k, v in zip(columns, row)} for row in rows],
    }


@app.get("/api/live/signals-log")
def api_signals_log(symbol: str | None = None, limit: int = 100, offset: int = 0):
    """Persisted strategy signals -- the audit trail of what fired and why."""
    limit = max(1, min(int(limit), 1000))
    conn = get_database()
    where, args = [], []
    if symbol:
        where.append("symbol = ?")
        args.append(symbol.strip().upper())
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(f"SELECT COUNT(*) FROM strategy_signals {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"""SELECT signal_id, symbol, strategy_id, action, side, price,
                   signal_ts, reason, metadata, paper_trade_id, source
            FROM strategy_signals {clause} ORDER BY signal_ts DESC LIMIT ? OFFSET ?""",
        [*args, limit, max(0, int(offset))],
    ).fetchall()
    columns = ["signal_id", "symbol", "strategy_id", "action", "side", "price",
               "signal_ts", "reason", "metadata", "paper_trade_id", "source"]
    return {
        "total": total, "limit": limit, "offset": offset,
        "signals": [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                     for k, v in zip(columns, row)} for row in rows],
    }


@app.get("/api/live/events")
def api_system_events(limit: int = 50, severity: str | None = None):
    """System event log: connection transitions, ingestion, write failures."""
    return {"events": capture_service.recent_events(limit=limit, severity=severity)}


class PurgeRequest(BaseModel):
    older_than_days: int


@app.post("/api/live/ticks/purge")
def api_purge_ticks(req: PurgeRequest):
    """
    Retention is manual and applies only to raw ticks. Nothing deletes data on
    a timer, and bars/signals/trades/P&L are never purged by this.
    """
    try:
        return capture_service.purge_ticks(req.older_than_days)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class XSentimentRequest(BaseModel):
    symbol: str
    max_results: int = 10


@app.get("/api/live/market")
def api_live_market(symbol: str | None = None):
    return live_market_service.snapshot(symbol=symbol)


@app.websocket("/api/ws/market")
async def websocket_live_market(websocket: WebSocket):
    await live_market_service.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        live_market_service.disconnect(websocket)


@app.websocket("/api/ws/symbol/{symbol}")
async def websocket_symbol_stream(websocket: WebSocket, symbol: str):
    """Subscribe to live updates (ticks + signals) for a specific symbol.
    This is the one channel signals.py broadcasts to -- the frontend never
    talks to Kite directly, only to this endpoint."""
    await ws_relay.connect(symbol.upper(), websocket)


# ---------------------------------------------------------------------------
# Zerodha Kite Connect: daily login flow. The API secret and access token
# never leave the backend -- these routes only ever return a login URL or a
# status flag to the frontend.
# ---------------------------------------------------------------------------

@app.get("/api/kite/diagnostics")
def api_kite_diagnostics():
    """
    One call that answers "why isn't live data working?" without ever
    returning a credential. Check this first when the UI shows no live prices.
    """
    problems = kite_client.configuration_problems()
    status = token_store.token_status(get_database())
    return {
        "ready": not problems and status["has_valid_token"],
        "problems": problems,
        "credentials": kite_client.credentials_status(),
        "token": status,
        "ticker": live_data_service.status(),
        "next_step": (
            problems[0] if problems
            else ("Open /api/kite/login-url and complete the Zerodha login."
                  if not status["has_valid_token"] else "Live data is ready.")
        ),
    }


@app.get("/api/kite/login-url")
def api_kite_login_url():
    return {"login_url": kite_client.login_url()}


class KiteCallbackRequest(BaseModel):
    request_token: str


def _complete_kite_login(request_token: str) -> dict:
    kite_client.exchange_request_token(request_token)
    started = live_data_service.start(asyncio.get_event_loop())
    return {
        "status": "authenticated",
        "ticker_started": started,
        "ticker_detail": live_data_service.last_error,
    }


@app.post("/api/kite/login-callback")
async def api_kite_login_callback(req: KiteCallbackRequest):
    return _complete_kite_login(req.request_token)


@app.get("/api/kite/login-callback")
async def api_kite_login_callback_redirect(request_token: str):
    """Zerodha redirects the browser straight here after login."""
    return _complete_kite_login(request_token)


@app.get("/api/kite/token-status")
def api_kite_token_status():
    return {**token_store.token_status(get_database()), "ticker_running": live_data_service.is_running()}


@app.get("/api/kite/profile")
def api_kite_profile():
    """Authenticated round-trip to Zerodha -- proves the token is genuinely live."""
    return kite_client.profile()


@app.post("/api/kite/logout")
def api_kite_logout():
    live_data_service.stop()
    kite_client.logout()
    return {"status": "logged_out"}


# ---------------------------------------------------------------------------
# Live monitoring: watch/unwatch a symbol+strategy pair against the real
# Kite tick stream. The strategy engine reused here is the exact same one
# api_create_run() below uses for backtests -- see server/signals.py.
# ---------------------------------------------------------------------------

class LiveWatchRequest(BaseModel):
    symbol: str
    strategy_file: str
    params: dict | None = None


@app.post("/api/live/watch")
def api_live_watch(req: LiveWatchRequest):
    spec_path = settings.STRATEGY_DIR / req.strategy_file
    if not spec_path.exists():
        raise HTTPException(404, f"Strategy file not found: {req.strategy_file}")
    spec = yaml.safe_load(spec_path.read_text())
    defaults = {k: v.get("default") for k, v in spec.get("parameters", {}).items()}
    resolved = {**defaults, **(req.params or {})}

    try:
        instrument_token = kite_client.resolve_instrument_token(req.symbol)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    # KiteConfigError / KiteAuthError / KiteUpstreamError fall through to the
    # typed handlers so the UI can tell "fix your .env" apart from "log in again".

    symbol = req.symbol.strip().upper()
    live_data_service.watch(instrument_token, symbol, spec_path.stem, spec.get("version", 1), resolved)

    if not live_data_service.is_running():
        # The row is persisted and will resubscribe once the ticker connects,
        # but say so plainly instead of reporting a watch that isn't ticking.
        started = live_data_service.start(asyncio.get_event_loop())
        if not started:
            logger.warning("Watch registered for %s but the ticker is not connected", symbol)

    conn = get_database()
    conn.execute(
        """INSERT INTO watchlist (symbol, strategy_id, strategy_version, params_json, instrument_token)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (symbol, strategy_id, strategy_version)
           DO UPDATE SET params_json = excluded.params_json, instrument_token = excluded.instrument_token""",
        [symbol, spec_path.stem, spec.get("version", 1), json.dumps(resolved), instrument_token],
    )
    return {"status": "watching", "symbol": symbol, "instrument_token": instrument_token,
            "strategy_id": spec_path.stem, "params": resolved,
            "ticker_running": live_data_service.is_running(),
            "ticker_detail": live_data_service.last_error}


class LiveUnwatchRequest(BaseModel):
    instrument_token: int


@app.post("/api/live/unwatch")
def api_live_unwatch(req: LiveUnwatchRequest):
    live_data_service.unwatch(req.instrument_token)
    conn = get_database()
    conn.execute("DELETE FROM watchlist WHERE instrument_token=?", [req.instrument_token])
    return {"status": "unwatched"}


@app.get("/api/live/watchlist")
def api_live_watchlist():
    return live_data_service.active_watches()


@app.get("/api/live/signals")
def api_live_signals(symbol: str | None = None, limit: int = 50):
    limit = max(1, min(limit, 1000))
    conn = get_database()
    if symbol:
        rows = conn.execute(
            "SELECT * FROM paper_trades WHERE watch_symbol=? ORDER BY entry_ts DESC LIMIT ?",
            [symbol.upper(), limit],
        ).fetchdf()
    else:
        rows = conn.execute(
            "SELECT * FROM paper_trades ORDER BY entry_ts DESC LIMIT ?", [limit]
        ).fetchdf()
    return json.loads(rows.to_json(orient="records", date_format="iso"))


# ---------------------------------------------------------------------------
# Market replay. Streams stored bars through the real live pipeline so the
# whole live path can be demonstrated and tested without a Kite subscription.
# Every record it emits is tagged source="replay-<run>" -- it is never
# presented as a live feed.
# ---------------------------------------------------------------------------

class ReplayStartRequest(BaseModel):
    symbol: str
    strategy_file: str = "directional_debit_spread.yaml"
    speed: float = 30.0     # bars per second
    bar_limit: int = 500


@app.post("/api/live/replay/start")
async def api_replay_start(req: ReplayStartRequest):
    try:
        return await replay_service.start(
            symbol=req.symbol, strategy_file=req.strategy_file,
            speed=req.speed, bar_limit=req.bar_limit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/live/replay/stop")
async def api_replay_stop():
    return await replay_service.stop()


@app.get("/api/live/replay/status")
def api_replay_status():
    return replay_service.status()


@app.post("/api/live/x/sentiment")
def api_x_sentiment(req: XSentimentRequest):
    try:
        return fetch_symbol_sentiment(req.symbol, max_results=req.max_results)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


class PaperOrderRequest(BaseModel):
    symbol: str
    expiry: str
    strike: float
    option_type: str
    quantity: int


@app.get("/api/paper/positions")
def api_paper_positions():
    return list_positions(get_database())


@app.post("/api/paper/positions")
def api_open_paper_position(req: PaperOrderRequest):
    try:
        return open_position(get_database(), **req.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/paper/positions/{position_id}/close")
def api_close_paper_position(position_id: str):
    try:
        return close_position(get_database(), position_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/imports")
def api_list_imports():
    conn = get_database()
    df = conn.execute("SELECT * FROM imports ORDER BY imported_at DESC").fetchdf()
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.get("/api/symbols")
def api_list_symbols():
    conn = get_database()
    rows = conn.execute(
        """SELECT DISTINCT symbol FROM equity_bars
           UNION SELECT DISTINCT underlying FROM option_bars ORDER BY 1"""
    ).fetchall()
    return [r[0] for r in rows]


@app.get("/api/stats")
def api_stats():
    conn = get_database()
    eq_row = conn.execute("SELECT COUNT(*) FROM equity_bars").fetchone() or (0,)
    opt_row = conn.execute("SELECT COUNT(*) FROM option_bars").fetchone() or (0,)
    stocks_row = conn.execute(
        "SELECT COUNT(DISTINCT symbol) FROM (SELECT symbol FROM equity_bars UNION SELECT underlying FROM option_bars)"
    ).fetchone() or (0,)
    imports_row = conn.execute("SELECT COUNT(*) FROM imports").fetchone() or (0,)
    return {
        "equity_rows": eq_row[0],
        "options_rows": opt_row[0],
        "stocks": stocks_row[0],
        "imports": imports_row[0],
    }


@app.get("/api/data-coverage")
def api_data_coverage(symbol: str):
    conn = get_database()
    eq = conn.execute(
        "SELECT COUNT(*), MIN(trading_date), MAX(trading_date) FROM equity_bars WHERE symbol=?", [symbol]
    ).fetchone()
    opt = conn.execute(
        "SELECT COUNT(*), MIN(trading_date), MAX(trading_date) FROM option_bars WHERE underlying=?", [symbol]
    ).fetchone()
    return {
        "symbol": symbol,
        "equity_rows": eq[0], "equity_start": str(eq[1]) if eq[1] else None, "equity_end": str(eq[2]) if eq[2] else None,
        "option_rows": opt[0], "option_start": str(opt[1]) if opt[1] else None, "option_end": str(opt[2]) if opt[2] else None,
    }


@app.get("/api/strategies")
def api_list_strategies():
    files = sorted(settings.STRATEGY_DIR.glob("*.yaml"))
    out = []
    for f in files:
        spec = yaml.safe_load(f.read_text())
        out.append({"file": f.name, "name": spec.get("name"), "version": spec.get("version"),
                    "parameters": spec.get("parameters", {})})
    return out


class CreateStrategyRequest(BaseModel):
    name: str
    description: str | None = None
    parent_file: str = "directional_debit_spread.yaml"
    parameters: dict[str, float]


@app.post("/api/strategies")
def api_create_strategy(req: CreateStrategyRequest):
    """Builds a new, distinct, versioned strategy YAML from the existing
    engine's parameter schema -- NOT a second engine. Saved files land in
    the same STRATEGY_DIR the runner and live-watch already read from, so
    a built strategy is immediately runnable via /api/runs and /api/live/watch,
    exactly like any hand-written strategy file."""
    parent_path = settings.STRATEGY_DIR / req.parent_file
    if not parent_path.exists():
        raise HTTPException(404, f"Base strategy file not found: {req.parent_file}")
    parent_spec = yaml.safe_load(parent_path.read_text())

    name = req.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "strategy"
    existing_versions = [
        int(m.group(1)) for f in settings.STRATEGY_DIR.glob(f"{slug}_v*.yaml")
        if (m := re.fullmatch(rf"{re.escape(slug)}_v(\d+)\.yaml", f.name))
    ]
    next_version = max(existing_versions, default=0) + 1

    new_params = json.loads(json.dumps(parent_spec.get("parameters", {})))  # deep copy
    for key, value in req.parameters.items():
        if key not in new_params:
            raise HTTPException(400, f"Unknown parameter {key!r} for base strategy {req.parent_file!r}")
        # Preserve the parent's default type (int vs float) -- StrategyParams
        # dataclass fields aren't runtime-cast, so an int field (e.g.
        # sma_fast) fed a float (Pydantic coerces JSON numbers to float)
        # breaks list slicing in indicators.py. Cast back to match.
        original_default = parent_spec["parameters"][key].get("default")
        typed_value = int(value) if isinstance(original_default, int) else value
        new_params[key] = {**new_params[key], "default": typed_value}

    spec = {
        "name": name,
        "version": next_version,
        "description": req.description or f"Custom parameter build derived from {parent_spec.get('name')}",
        "parameters": new_params,
    }
    file_name = f"{slug}_v{next_version}.yaml"
    file_path = settings.STRATEGY_DIR / file_name
    config_yaml = yaml.safe_dump(spec, sort_keys=False)
    file_path.write_text(config_yaml)

    conn = get_database()
    config_hash = hashlib.sha256(config_yaml.encode()).hexdigest()[:16]
    conn.execute(
        """INSERT INTO strategies (strategy_id, version, parent_version, name, description,
           config_yaml, config_hash, param_schema)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [slug, next_version, parent_spec.get("version"), spec["name"], spec["description"],
         config_yaml, config_hash, json.dumps(new_params)],
    )
    return {"file": file_name, **spec}


class RunRequest(BaseModel):
    strategy_file: str
    symbol: str
    date_start: str | None = None
    date_end: str | None = None
    params: dict | None = None
    cost_profile: str | None = None   # "none" (default), "discount_broker", "full_service"


@app.post("/api/runs")
def api_create_run(req: RunRequest):
    conn = get_database()
    spec_path = settings.STRATEGY_DIR / req.strategy_file
    if not spec_path.exists():
        raise HTTPException(404, f"Strategy file not found: {req.strategy_file}")
    spec = yaml.safe_load(spec_path.read_text())

    defaults = {k: v.get("default") for k, v in spec.get("parameters", {}).items()}
    resolved = {**defaults, **(req.params or {})}
    params = StrategyParams(**{k: v for k, v in resolved.items() if k in StrategyParams.__dataclass_fields__})

    try:
        run_id = run_backtest(
            conn, strategy_id=spec_path.stem, strategy_version=spec.get("version", 1),
            symbol=req.symbol, params=params, date_start=req.date_start, date_end=req.date_end,
            cost_profile=req.cost_profile,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    row = conn.execute("SELECT * FROM runs WHERE run_id=?", [run_id]).fetchdf()
    return json.loads(row.to_json(orient="records", date_format="iso"))[0]


# ---------------------------------------------------------------------------
# Analytics: metrics, equity curve, CSV export, parameter sweep.
# All derived from stored trades, so any historical run can be re-analysed
# without re-running the backtest.
# ---------------------------------------------------------------------------

@app.get("/api/cost-profiles")
def api_cost_profiles():
    """Available transaction-cost profiles, with each rate spelled out."""
    return [cost_model.describe(p) for p in cost_model.PROFILES.values()]


@app.get("/api/runs/{run_id}/metrics")
def api_run_metrics(run_id: str, starting_equity: float = 0.0):
    conn = get_database()
    if conn.execute("SELECT 1 FROM runs WHERE run_id = ?", [run_id]).fetchone() is None:
        raise HTTPException(404, f"Run {run_id} not found")
    trades = metrics_module.load_trades(conn, run_id)
    return {"run_id": run_id, **metrics_module.compute(trades, starting_equity)}


@app.get("/api/runs/{run_id}/equity")
def api_run_equity(run_id: str, starting_equity: float = 0.0):
    conn = get_database()
    if conn.execute("SELECT 1 FROM runs WHERE run_id = ?", [run_id]).fetchone() is None:
        raise HTTPException(404, f"Run {run_id} not found")
    trades = metrics_module.load_trades(conn, run_id)
    return {"run_id": run_id, "points": metrics_module.equity_curve(trades, starting_equity)}


@app.get("/api/runs/{run_id}/export.csv")
def api_run_export_csv(run_id: str):
    """Trades as CSV. Streamed as a download so it opens straight in Excel."""
    conn = get_database()
    if conn.execute("SELECT 1 FROM runs WHERE run_id = ?", [run_id]).fetchone() is None:
        raise HTTPException(404, f"Run {run_id} not found")

    trades = metrics_module.load_trades(conn, run_id)
    buffer = io.StringIO()
    columns = ["trade_id", "symbol", "strategy_side", "entry_date", "exit_date",
               "lot_size", "lots", "gross_pnl", "costs", "net_pnl", "exit_reason"]
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for trade in trades:
        writer.writerow({k: trade.get(k) for k in columns})

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="run_{run_id[:8]}_trades.csv"'},
    )


class SweepRequest(BaseModel):
    strategy_file: str
    symbol: str
    parameter: str                 # which parameter to vary
    values: list[float]            # values to try
    date_start: str | None = None
    date_end: str | None = None
    params: dict | None = None     # fixed values for everything else
    cost_profile: str | None = None


@app.post("/api/runs/sweep")
def api_run_sweep(req: SweepRequest):
    """
    Run the same backtest across a range of one parameter.

    This is how you find out whether a result is a real effect or one lucky
    setting. A strategy that only works at ADX threshold 20 and collapses at
    19 and 21 is curve-fitted, and a sweep makes that visible immediately.
    """
    if not req.values:
        raise HTTPException(400, "values cannot be empty")
    if len(req.values) > 25:
        raise HTTPException(400, "Sweep limited to 25 values per request.")

    conn = get_database()
    spec_path = settings.STRATEGY_DIR / req.strategy_file
    if not spec_path.exists():
        raise HTTPException(404, f"Strategy file not found: {req.strategy_file}")
    spec = yaml.safe_load(spec_path.read_text())
    defaults = {k: v.get("default") for k, v in spec.get("parameters", {}).items()}

    if req.parameter not in defaults:
        raise HTTPException(
            400,
            f"Unknown parameter {req.parameter!r}. Available: {', '.join(sorted(defaults))}",
        )

    results = []
    for value in req.values:
        merged = {**defaults, **(req.params or {}), req.parameter: value}
        try:
            params = StrategyParams(
                **{k: v for k, v in merged.items() if k in StrategyParams.__dataclass_fields__}
            )
            run_id = run_backtest(
                conn, strategy_id=spec_path.stem, strategy_version=spec.get("version", 1),
                symbol=req.symbol, params=params,
                date_start=req.date_start, date_end=req.date_end,
                cost_profile=req.cost_profile,
            )
        except (TypeError, ValueError) as exc:
            results.append({"value": value, "error": str(exc)})
            continue

        trades = metrics_module.load_trades(conn, run_id)
        computed = metrics_module.compute(trades)
        results.append({
            "value": value,
            "run_id": run_id,
            "num_trades": computed.get("num_trades", 0),
            "total_net_pnl": computed.get("total_net_pnl", 0.0),
            "win_rate": computed.get("win_rate"),
            "profit_factor": computed.get("profit_factor"),
            "max_drawdown": computed.get("max_drawdown"),
            "sharpe": computed.get("sharpe"),
        })

    scored = [r for r in results if "error" not in r and r["num_trades"] > 0]
    best = max(scored, key=lambda r: r["total_net_pnl"]) if scored else None

    return {
        "parameter": req.parameter,
        "symbol": req.symbol.strip().upper(),
        "results": results,
        "best_by_net_pnl": best,
        "caveat": (
            "The best value here is the best on this sample, which is not the same "
            "as the best value. Check that neighbouring values behave similarly — a "
            "lone spike is curve fitting, not an edge."
        ),
    }


@app.get("/api/runs")
def api_list_runs():
    conn = get_database()
    df = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchdf()
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.get("/api/runs/{run_id}/trades")
def api_run_trades(run_id: str):
    conn = get_database()
    trades = conn.execute("SELECT * FROM trades WHERE run_id=? ORDER BY entry_date", [run_id]).fetchdf()
    trades_json = json.loads(trades.to_json(orient="records", date_format="iso"))
    for t in trades_json:
        legs = conn.execute("SELECT * FROM trade_legs WHERE trade_id=?", [t["trade_id"]]).fetchdf()
        t["legs"] = json.loads(legs.to_json(orient="records", date_format="iso"))
    return trades_json


@app.get("/api/trades")
def api_trades(
    run_id: str | None = None,
    symbol: str | None = None,
    exit_reason: str | None = None,
    outcome: str | None = None,  # 'win' | 'loss'
    limit: int = 50,
    offset: int = 0,
):
    conn = get_database()
    where = []
    args: list = []
    if run_id:
        where.append("run_id = ?")
        args.append(run_id)
    if symbol:
        where.append("symbol = ?")
        args.append(symbol)
    if exit_reason:
        where.append("exit_reason = ?")
        args.append(exit_reason)
    if outcome == "win":
        where.append("net_pnl > 0")
    elif outcome == "loss":
        where.append("net_pnl <= 0")
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(f"SELECT COUNT(*) FROM trades {clause}", args).fetchone()[0]
    df = conn.execute(
        f"SELECT * FROM trades {clause} ORDER BY entry_date DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchdf()
    trades_json = json.loads(df.to_json(orient="records", date_format="iso"))
    for t in trades_json:
        legs = conn.execute("SELECT * FROM trade_legs WHERE trade_id=?", [t["trade_id"]]).fetchdf()
        t["legs"] = json.loads(legs.to_json(orient="records", date_format="iso"))
    return {"total": total, "trades": trades_json}


@app.get("/api/runs/compare")
def api_compare_runs(run_ids: str):
    """run_ids: comma-separated list of run_id values."""
    conn = get_database()
    ids = [r for r in run_ids.split(",") if r]
    if len(ids) < 2:
        raise HTTPException(400, "Provide at least 2 run_ids to compare")

    placeholders = ",".join(["?"] * len(ids))
    runs_df = conn.execute(f"SELECT * FROM runs WHERE run_id IN ({placeholders})", ids).fetchdf()
    runs = json.loads(runs_df.to_json(orient="records", date_format="iso"))

    result = []
    for r in runs:
        run_id = r["run_id"]
        trades = conn.execute(
            "SELECT symbol, entry_date, exit_date, net_pnl FROM trades WHERE run_id=? ORDER BY entry_date",
            [run_id],
        ).fetchall()
        by_stock: dict[str, float] = {}
        cumulative = []
        running = 0.0
        holding_days = []
        for sym, entry, exit_, pnl in trades:
            by_stock[sym] = by_stock.get(sym, 0.0) + (pnl or 0)
            running += pnl or 0
            cumulative.append({"date": str(exit_), "cumulative_pnl": running})
            if entry and exit_:
                holding_days.append((exit_ - entry).days)
        avg_holding = sum(holding_days) / len(holding_days) if holding_days else None
        result.append({
            **r,
            "pnl_by_stock": by_stock,
            "cumulative_pnl": cumulative,
            "avg_holding_days": avg_holding,
        })
    return result


@app.get("/api/health")
def health():
    """
    A real health check: it touches the database. The old version returned
    {"status": "ok"} unconditionally, so the UI showed a healthy backend even
    when every data endpoint was failing.
    """
    try:
        get_database().execute("SELECT 1").fetchone()
        database = "connected"
        status = "ok"
    except Exception as exc:  # noqa: BLE001
        database = f"error: {exc}"
        status = "degraded"
    return {
        "status": status,
        "version": settings.APP_VERSION,
        "database": database,
        "kite_authenticated": token_store.token_status(get_database())["has_valid_token"]
        if database == "connected" else False,
        "ticker_running": live_data_service.is_running(),
    }
