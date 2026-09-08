#!/usr/bin/env python3
"""
Copy an existing DuckDB database into PostgreSQL.

    python migrate_to_postgres.py --dsn postgresql://user:pass@localhost:5432/osa

Reads every table from data/market_data.duckdb and inserts it into a
PostgreSQL database with the same schema. Idempotent: rows that already exist
are skipped, so re-running after a partial failure is safe.

Nothing is deleted from DuckDB. If the migration goes wrong, unset
OA_DB_BACKEND and you are back on the original file, untouched.
"""
from __future__ import annotations

import argparse
import sys

TABLES = [
    "imports", "equity_bars", "option_bars", "strategies", "runs", "trades",
    "trade_legs", "kite_sessions", "watchlist", "live_ticks", "live_market_data",
    "paper_trades", "paper_positions", "paper_orders", "capture_sessions",
    "strategy_signals", "pnl_snapshots", "system_events",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--duckdb", default="data/market_data.duckdb")
    parser.add_argument("--batch", type=int, default=1000)
    args = parser.parse_args()

    import duckdb
    from server.database import _SCHEMA_UPGRADES
    from server.config import settings
    from server.postgres_backend import PostgresConnection, apply_schema

    src = duckdb.connect(args.duckdb, read_only=True)
    dst = PostgresConnection(args.dsn)

    print(f"Applying schema to {args.dsn.split('@')[-1]} ...")
    apply_schema(dst, (settings.REPO_ROOT / "server" / "schema.sql").read_text(),
                 _SCHEMA_UPGRADES)

    total = 0
    for table in TABLES:
        try:
            columns = [r[1] for r in src.execute(f"PRAGMA table_info('{table}')").fetchall()]
            if not columns:
                continue
            rows = src.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
        except Exception as exc:  # noqa: BLE001
            print(f"  {table:20} skipped ({exc})")
            continue

        if not rows:
            print(f"  {table:20} 0 rows")
            continue

        placeholders = ", ".join(["?"] * len(columns))
        sql = (f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) "
               f"VALUES ({placeholders})")
        moved = 0
        for i in range(0, len(rows), args.batch):
            chunk = rows[i:i + args.batch]
            try:
                dst.executemany(sql, chunk)
                moved += len(chunk)
            except Exception as exc:  # noqa: BLE001
                print(f"  {table:20} batch failed at row {i}: {str(exc)[:90]}")
        print(f"  {table:20} {moved} rows")
        total += moved

    print(f"\nMigrated {total} rows.")
    print("Now start the backend with:")
    print("  set OA_DB_BACKEND=postgres")
    print(f"  set OA_POSTGRES_DSN={args.dsn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
