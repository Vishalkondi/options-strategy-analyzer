"""Configuration loaded from environment (OA_ prefix). No business logic here.

Kite credentials deliberately do NOT live here any more -- server/kite_client.py
owns them, because it also has to decide whether a value is real or still the
placeholder text from .env.example. Two modules reading the same secret from two
places is how the old code ended up with a login flow that worked and a data
sync that insisted the token was missing.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


def _resolve(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _csv_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    REPO_ROOT: Path = REPO_ROOT
    DB_PATH: Path = _resolve(os.getenv("OA_DB_PATH", "./data/market_data.duckdb"))
    RAW_DIR: Path = _resolve(os.getenv("OA_RAW_DIR", "./data/raw"))
    LIVE_DIR: Path = _resolve(os.getenv("OA_LIVE_DIR", "./data/live"))
    LIVE_POLL_SECONDS: float = float(os.getenv("OA_LIVE_POLL_SECONDS", "1"))
    PARQUET_DIR: Path = _resolve(os.getenv("OA_PARQUET_DIR", "./data/parquet"))
    STRATEGY_DIR: Path = _resolve(os.getenv("OA_STRATEGY_DIR", "./strategies"))
    HOST: str = os.getenv("OA_HOST", "127.0.0.1")
    PORT: int = int(os.getenv("OA_PORT", "8000"))
    CORS_ORIGINS: list[str] = _csv_list(os.getenv(
        "OA_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ))
    RELATIVE_TOLERANCE: float = float(os.getenv("OA_RELATIVE_TOLERANCE", "1e-6"))
    PNL_ABSOLUTE_TOLERANCE: float = float(os.getenv("OA_PNL_ABSOLUTE_TOLERANCE", "0.01"))
    NSE_HOLIDAY_FILE: Path = _resolve(os.getenv("OA_NSE_HOLIDAY_FILE", "./data/reference/nse_holidays.csv"))

    # Live dashboard watchlist (real quotes when Kite is authenticated).
    LIVE_MARKET_SYMBOLS: list[str] = _csv_list(os.getenv(
        "OA_LIVE_MARKET_SYMBOLS", "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK"
    ))
    LIVE_MARKET_INTERVAL: float = float(os.getenv("OA_LIVE_MARKET_INTERVAL", "2"))
    # Kite allows ~1 quote req/sec; never re-fetch faster than this.
    LIVE_MARKET_CACHE_SECONDS: float = float(os.getenv("OA_LIVE_MARKET_CACHE_SECONDS", "1.5"))
    # Kite historical API allows ~3 req/sec. 0.34s between calls stays under it.
    KITE_HISTORICAL_THROTTLE: float = float(os.getenv("OA_KITE_HISTORICAL_THROTTLE", "0.34"))
    # Cap on option contracts pulled per sync, so one call can't fire 400 requests.
    SYNC_MAX_CONTRACTS: int = int(os.getenv("OA_SYNC_MAX_CONTRACTS", "20"))
    # How many strikes either side of ATM to sync when no explicit strikes given.
    SYNC_STRIKE_WINDOW: int = int(os.getenv("OA_SYNC_STRIKE_WINDOW", "5"))

    # Live capture. Writes are buffered and flushed on a background thread, so
    # these control how much is held in memory before it reaches DuckDB.
    # Scheduled capture. Runs on the backend, independent of the frontend.
    SCHEDULER_ENABLED: bool = os.getenv("OA_SCHEDULER_ENABLED", "true").lower() != "false"
    SCHEDULER_INTERVAL_SECONDS: float = float(os.getenv("OA_SCHEDULER_INTERVAL_SECONDS", "1800"))
    SCHEDULER_RUN_ON_STARTUP: bool = os.getenv("OA_SCHEDULER_RUN_ON_STARTUP", "true").lower() != "false"
    SCHEDULER_MAX_RETRIES: int = int(os.getenv("OA_SCHEDULER_MAX_RETRIES", "3"))
    SCHEDULER_RETRY_BACKOFF: float = float(os.getenv("OA_SCHEDULER_RETRY_BACKOFF", "2.0"))
    SCHEDULER_SYMBOLS: list[str] = _csv_list(os.getenv("OA_SCHEDULER_SYMBOLS", ""))

    # Storage backend. DuckDB stays the default: it is what the analytical
    # backtest queries are fast on. Postgres is opt-in for concurrent access.
    DB_BACKEND: str = os.getenv("OA_DB_BACKEND", "duckdb").strip().lower()
    POSTGRES_DSN: str = os.getenv(
        "OA_POSTGRES_DSN", "postgresql://postgres@localhost:5432/osa"
    )
    POSTGRES_POOL_MAX: int = int(os.getenv("OA_POSTGRES_POOL_MAX", "10"))

    CAPTURE_ENABLED: bool = os.getenv("OA_CAPTURE_ENABLED", "true").lower() != "false"
    CAPTURE_BATCH_SIZE: int = int(os.getenv("OA_CAPTURE_BATCH_SIZE", "200"))
    CAPTURE_FLUSH_INTERVAL: float = float(os.getenv("OA_CAPTURE_FLUSH_INTERVAL", "2.0"))
    CAPTURE_MAX_BUFFER: int = int(os.getenv("OA_CAPTURE_MAX_BUFFER", "50000"))
    CAPTURE_AUTO_START: bool = os.getenv("OA_CAPTURE_AUTO_START", "true").lower() != "false"
    PNL_SNAPSHOT_INTERVAL: float = float(os.getenv("OA_PNL_SNAPSHOT_INTERVAL", "60"))
    TICK_RETENTION_DAYS: int = int(os.getenv("OA_TICK_RETENTION_DAYS", "0"))  # 0 = never purge

    X_API_BEARER_TOKEN: str = os.getenv("OA_X_API_BEARER_TOKEN", "")
    X_API_BASE_URL: str = os.getenv("OA_X_API_BASE_URL", "https://api.x.com")
    ENGINE_VERSION: str = "0.1.0-demo"
    APP_VERSION: str = "0.2.0"


settings = Settings()
