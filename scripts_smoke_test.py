"""Run once to prove the whole pipeline works: import -> engine -> trades.
Usage: .venv/bin/python scripts_smoke_test.py
"""
from __future__ import annotations
import json
from pathlib import Path

import yaml

from server.config import settings
from server.database import get_database
from server.engine import run_backtest
from server.ingest import ingest_path
from server.strategy_debit_spread import StrategyParams

conn = get_database()

print("=== 1. Import demo CSVs ===")
reports = ingest_path(conn, settings.RAW_DIR, "demo")
for r in reports:
    print(f"  {Path(r.file_path).name}: read={r.rows_read} accepted={r.rows_accepted} "
          f"rejected={r.rows_rejected} dup_file={r.skipped_duplicate_file} "
          f"range=[{r.date_start} .. {r.date_end}]")
    if r.errors:
        print(f"    errors: {r.errors[:3]}{'...' if len(r.errors) > 3 else ''}")

print("\n=== 2. Re-import same files (should be idempotent no-ops) ===")
reports2 = ingest_path(conn, settings.RAW_DIR, "demo")
for r in reports2:
    print(f"  {Path(r.file_path).name}: skipped_duplicate_file={r.skipped_duplicate_file}")

print("\n=== 3. Data coverage check ===")
eq_count = conn.execute("SELECT COUNT(*) FROM equity_bars WHERE symbol='DEMOSTK'").fetchone()[0]
opt_count = conn.execute("SELECT COUNT(*) FROM option_bars WHERE underlying='DEMOSTK'").fetchone()[0]
print(f"  equity_bars: {eq_count} rows, option_bars: {opt_count} rows")

print("\n=== 4. Run backtest (directional debit spread, reference strategy) ===")
spec_path = settings.STRATEGY_DIR / "directional_debit_spread.yaml"
spec = yaml.safe_load(spec_path.read_text())
defaults = {k: v.get("default") for k, v in spec["parameters"].items()}
params = StrategyParams(**{k: v for k, v in defaults.items() if k in StrategyParams.__dataclass_fields__})

run_id = run_backtest(conn, strategy_id="directional_debit_spread", strategy_version=1,
                       symbol="DEMOSTK", params=params)

run_row = conn.execute("SELECT * FROM runs WHERE run_id=?", [run_id]).fetchdf()
print(run_row.to_string(index=False))

print("\n=== 5. Trades from this run ===")
trades = conn.execute(
    "SELECT trade_id, strategy_side, entry_date, exit_date, net_pnl, exit_reason FROM trades WHERE run_id=?",
    [run_id],
).fetchdf()
if trades.empty:
    print("  No trades generated (expected on 15-day demo data — ADX needs ~2*period bars to warm up; "
          "see note below).")
else:
    print(trades.to_string(index=False))

print("\n=== 6. Reproducibility check: re-run same params, compare within tolerance ===")
run_id_2 = run_backtest(conn, strategy_id="directional_debit_spread", strategy_version=1,
                         symbol="DEMOSTK", params=params)
r1 = conn.execute("SELECT total_net_pnl, num_trades FROM runs WHERE run_id=?", [run_id]).fetchone()
r2 = conn.execute("SELECT total_net_pnl, num_trades FROM runs WHERE run_id=?", [run_id_2]).fetchone()
print(f"  run1: net_pnl={r1[0]} trades={r1[1]}")
print(f"  run2: net_pnl={r2[0]} trades={r2[1]}")
tol = settings.PNL_ABSOLUTE_TOLERANCE
match = (r1[1] == r2[1]) and (abs((r1[0] or 0) - (r2[0] or 0)) <= tol)
print(f"  reproducible within tolerance ({tol}): {match}")

print("\nDone. DB file:", settings.DB_PATH)
