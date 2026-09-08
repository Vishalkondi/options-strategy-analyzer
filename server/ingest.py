"""
CSV ingestion for NSE-bhavcopy-style equity and options files.

Supported demo fixture format:
    DEMOSTK_equity.csv
    DEMOSTK_options.csv

The parser is designed for the local/demo CSV ingestion flow.

IMPORTANT:
    This module does NOT connect to Zerodha/Kite.
    It only reads CSV files from the configured raw data directory
    and stores the data in DuckDB.

Column mapping implemented here matches the DEMO fixture format
(DEMOSTK_equity.csv / DEMOSTK_options.csv), which mirrors the standard
NSE bhavcopy layout.

THIS MAPPING IS NOT YET VALIDATED AGAINST REAL NSE FILES
(GAP_ANALYSIS B3/B4). If real files use different column names,
this parser must be updated to match them exactly rather than guessed.

Ingestion is idempotent:
    - SHA-256 of each imported file is stored in the imports table.
    - Importing the exact same file again becomes a no-op.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

@dataclass
class QualityReport:
    """
    Result of importing one CSV file.
    """

    file_path: str
    symbol: str
    kind: str

    rows_read: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0

    duplicates: int = 0
    glued_rows_fixed: int = 0

    missing_values: int = 0
    invalid_values: int = 0

    date_start: str | None = None
    date_end: str | None = None
    trading_day_count: int = 0

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    skipped_duplicate_file: bool = False
    import_id: int | None = None


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _sha256_of_file(path: Path) -> str:
    """
    Calculate SHA-256 hash for a file.

    The hash is used to prevent importing the exact same file twice.
    """

    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)

    return h.hexdigest()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: str) -> str:
    """
    Parse supported date formats and return ISO format.

    Supported:
        DD-MMM-YYYY
        DD-MM-YYYY
        YYYY-MM-DD

    Example:
        03-AUG-2026
        -> 2026-08-03
    """

    if raw is None:
        raise ValueError("Date value is missing")

    raw = str(raw).strip()

    if not raw:
        raise ValueError("Date value is empty")

    for fmt in (
        "%d-%b-%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(f"Unrecognized date format: {raw!r}")


def _parse_number(raw: str | None) -> float | None:
    """
    Convert a CSV numeric value into float.

    Empty values and common missing-value markers return None.
    """

    if raw is None:
        return None

    raw = str(raw).strip().replace(",", "")

    if raw in (
        "",
        "-",
        "NA",
        "N/A",
        "NULL",
        "NONE",
    ):
        return None

    return float(raw)


def _parse_int(raw: str | None) -> int | None:
    """
    Convert a CSV integer value into int.

    Empty values and common missing-value markers return None.
    """

    if raw is None:
        return None

    raw = str(raw).strip().replace(",", "")

    if raw in (
        "",
        "-",
        "NA",
        "N/A",
        "NULL",
        "NONE",
    ):
        return None

    # Some CSV files may contain values such as 100.0.
    return int(float(raw))


# ---------------------------------------------------------------------------
# Filename detection
# ---------------------------------------------------------------------------

def _infer_symbol_kind(filename: str) -> tuple[str, str]:
    """
    Determine symbol and data type from filename.

    Supported:

        DEMOSTK_equity.csv
        DEMOSTK_options.csv

    Returns:

        ("DEMOSTK", "equity")
        ("DEMOSTK", "options")
    """

    stem = Path(filename).stem

    upper_stem = stem.upper()

    if upper_stem.endswith("_EQUITY"):
        symbol = stem[: -len("_equity")]
        return symbol, "equity"

    if upper_stem.endswith("_OPTIONS"):
        symbol = stem[: -len("_options")]
        return symbol, "options"

    raise ValueError(
        "Filename must end with "
        "_equity.csv or _options.csv, "
        f"got {filename!r}"
    )


# ---------------------------------------------------------------------------
# Import ID
# ---------------------------------------------------------------------------

def _next_import_id(conn: duckdb.DuckDBPyConnection) -> int:
    """
    Generate the next import ID.
    """

    row = conn.execute(
        """
        SELECT COALESCE(MAX(import_id), 0) + 1
        FROM imports
        """
    ).fetchone()

    return int(row[0])


# ---------------------------------------------------------------------------
# Duplicate file check
# ---------------------------------------------------------------------------

def _existing_import_id(
    conn: duckdb.DuckDBPyConnection,
    file_hash: str,
) -> int | None:
    """
    Return existing import_id for a file hash.

    Returns None when the file has not been imported.
    """

    row = conn.execute(
        """
        SELECT import_id
        FROM imports
        WHERE file_hash = ?
        """,
        [file_hash],
    ).fetchone()

    if row is None:
        return None

    return int(row[0])


# ---------------------------------------------------------------------------
# Equity ingestion
# ---------------------------------------------------------------------------

def ingest_equity_file(
    conn: duckdb.DuckDBPyConnection,
    path: Path,
) -> QualityReport:
    """
    Import one equity CSV file into equity_bars.
    """

    path = Path(path)

    symbol, kind = _infer_symbol_kind(path.name)

    if kind != "equity":
        raise ValueError(
            f"Expected an equity file, got {path.name!r}"
        )

    report = QualityReport(
        file_path=str(path),
        symbol=symbol,
        kind=kind,
    )

    # -----------------------------------------------------------------------
    # Duplicate file check
    # -----------------------------------------------------------------------

    file_hash = _sha256_of_file(path)

    existing_import_id = _existing_import_id(
        conn,
        file_hash,
    )

    if existing_import_id is not None:
        report.skipped_duplicate_file = True
        report.import_id = existing_import_id

        report.warnings.append(
            "File already imported (identical SHA-256) — no-op."
        )

        return report

    # -----------------------------------------------------------------------
    # Read CSV
    # -----------------------------------------------------------------------

    dates: list[str] = []
    rows_to_insert: list[tuple] = []

    with open(
        path,
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError(
                f"CSV file has no header: {path.name}"
            )

        required_columns = {
            "DATE",
            "SYMBOL",
            "OPEN",
            "HIGH",
            "LOW",
            "CLOSE",
        }

        missing_columns = required_columns - set(reader.fieldnames)

        if missing_columns:
            raise ValueError(
                f"{path.name}: missing required columns: "
                f"{sorted(missing_columns)}"
            )

        # -------------------------------------------------------------------
        # Process rows
        # -------------------------------------------------------------------

        for raw_row in reader:

            report.rows_read += 1

            try:
                # -----------------------------------------------------------
                # Required fields
                # -----------------------------------------------------------

                trading_date = _parse_date(
                    raw_row["DATE"]
                )

                row_symbol = (
                    raw_row["SYMBOL"]
                    .strip()
                    .upper()
                )

                if not row_symbol:
                    raise ValueError(
                        "SYMBOL is empty"
                    )

                # -----------------------------------------------------------
                # OHLC
                # -----------------------------------------------------------

                open_p = _parse_number(
                    raw_row["OPEN"]
                )

                high_p = _parse_number(
                    raw_row["HIGH"]
                )

                low_p = _parse_number(
                    raw_row["LOW"]
                )

                close_p = _parse_number(
                    raw_row["CLOSE"]
                )

                # -----------------------------------------------------------
                # Optional values
                # -----------------------------------------------------------

                prev_close = _parse_number(
                    raw_row.get("PREV_CLOSE")
                )

                vwap = _parse_number(
                    raw_row.get("VWAP")
                )

                volume = _parse_int(
                    raw_row.get("VOLUME")
                )

                turnover = _parse_number(
                    raw_row.get("TURNOVER")
                )

                total_trades = _parse_int(
                    raw_row.get("TOTAL_TRADES")
                )

                deliverable_qty = _parse_int(
                    raw_row.get("DELIVERABLE_QTY")
                )

                deliverable_pct = _parse_number(
                    raw_row.get("DELIVERABLE_PCT")
                )

                # -----------------------------------------------------------
                # Required OHLC validation
                # -----------------------------------------------------------

                missing = [
                    key
                    for key, value in {
                        "OPEN": open_p,
                        "HIGH": high_p,
                        "LOW": low_p,
                        "CLOSE": close_p,
                    }.items()
                    if value is None
                ]

                if missing:
                    report.missing_values += len(missing)
                    report.rows_rejected += 1

                    report.errors.append(
                        f"{trading_date}: missing {missing}"
                    )

                    continue

                # -----------------------------------------------------------
                # OHLC range validation
                # -----------------------------------------------------------

                if not (
                    low_p <= open_p <= high_p
                    and low_p <= close_p <= high_p
                ):
                    report.invalid_values += 1
                    report.rows_rejected += 1

                    report.errors.append(
                        f"{trading_date}: "
                        f"OHLC out of range "
                        f"(low={low_p} high={high_p})"
                    )

                    continue

            except Exception as exc:
                report.rows_rejected += 1

                report.errors.append(
                    f"row {report.rows_read}: {exc}"
                )

                continue

            # ----------------------------------------------------------------
            # Prepare database row
            # ----------------------------------------------------------------

            dates.append(trading_date)

            rows_to_insert.append(
                (
                    row_symbol,
                    trading_date,
                    f"{trading_date} 00:00:00",
                    "1d",
                    open_p,
                    high_p,
                    low_p,
                    close_p,
                    prev_close,
                    vwap,
                    volume,
                    turnover,
                    total_trades,
                    deliverable_qty,
                    deliverable_pct,
                )
            )

            report.rows_accepted += 1

    # -----------------------------------------------------------------------
    # Calculate report information
    # -----------------------------------------------------------------------

    if rows_to_insert:

        report.date_start = min(dates)
        report.date_end = max(dates)

        unique_dates = set(dates)

        report.trading_day_count = len(
            unique_dates
        )

        if len(unique_dates) != len(dates):

            report.duplicates = (
                len(dates)
                - len(unique_dates)
            )

            report.warnings.append(
                f"{report.duplicates} duplicate "
                "trading_date rows within file"
            )

    # -----------------------------------------------------------------------
    # Create import record
    # -----------------------------------------------------------------------

    import_id = _next_import_id(conn)

    report.import_id = import_id

    conn.execute(
        """
        INSERT INTO imports (
            import_id,
            file_path,
            file_hash,
            symbol,
            kind,
            rows_read,
            rows_accepted,
            rows_rejected,
            duplicates,
            glued_rows_fixed,
            missing_values,
            invalid_values,
            date_start,
            date_end,
            trading_day_count,
            warnings,
            errors
        )
        VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?
        )
        """,
        [
            import_id,
            str(path),
            file_hash,
            symbol,
            kind,
            report.rows_read,
            report.rows_accepted,
            report.rows_rejected,
            report.duplicates,
            report.glued_rows_fixed,
            report.missing_values,
            report.invalid_values,
            report.date_start,
            report.date_end,
            report.trading_day_count,
            json.dumps(report.warnings),
            json.dumps(report.errors),
        ],
    )

    # -----------------------------------------------------------------------
    # Insert equity bars
    # -----------------------------------------------------------------------

    for row in rows_to_insert:

        conn.execute(
            """
            INSERT OR REPLACE INTO equity_bars (
                symbol,
                trading_date,
                timestamp,
                bar_interval,
                open,
                high,
                low,
                close,
                prev_close,
                vwap,
                volume,
                turnover,
                total_trades,
                deliverable_qty,
                deliverable_pct,
                import_id
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            [
                *row,
                import_id,
            ],
        )

    return report


# ---------------------------------------------------------------------------
# Options ingestion
# ---------------------------------------------------------------------------

def ingest_options_file(
    conn: duckdb.DuckDBPyConnection,
    path: Path,
) -> QualityReport:
    """
    Import one options CSV file into option_bars.
    """

    path = Path(path)

    symbol, kind = _infer_symbol_kind(path.name)

    if kind != "options":
        raise ValueError(
            f"Expected an options file, got {path.name!r}"
        )

    report = QualityReport(
        file_path=str(path),
        symbol=symbol,
        kind=kind,
    )

    # -----------------------------------------------------------------------
    # Duplicate file check
    # -----------------------------------------------------------------------

    file_hash = _sha256_of_file(path)

    existing_import_id = _existing_import_id(
        conn,
        file_hash,
    )

    if existing_import_id is not None:
        report.skipped_duplicate_file = True
        report.import_id = existing_import_id

        report.warnings.append(
            "File already imported (identical SHA-256) — no-op."
        )

        return report

    # -----------------------------------------------------------------------
    # Read CSV
    # -----------------------------------------------------------------------

    dates: list[str] = []
    rows_to_insert: list[tuple] = []

    with open(
        path,
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError(
                f"CSV file has no header: {path.name}"
            )

        required_columns = {
            "TIMESTAMP",
            "EXPIRY_DT",
            "SYMBOL",
            "STRIKE_PR",
            "OPTION_TYP",
        }

        missing_columns = required_columns - set(
            reader.fieldnames
        )

        if missing_columns:
            raise ValueError(
                f"{path.name}: missing required columns: "
                f"{sorted(missing_columns)}"
            )

        # -------------------------------------------------------------------
        # Process rows
        # -------------------------------------------------------------------

        for raw_row in reader:

            report.rows_read += 1

            try:
                # -----------------------------------------------------------
                # Required fields
                # -----------------------------------------------------------

                trading_date = _parse_date(
                    raw_row["TIMESTAMP"]
                )

                expiry = _parse_date(
                    raw_row["EXPIRY_DT"]
                )

                underlying = (
                    raw_row["SYMBOL"]
                    .strip()
                    .upper()
                )

                if not underlying:
                    raise ValueError(
                        "SYMBOL is empty"
                    )

                strike = _parse_number(
                    raw_row["STRIKE_PR"]
                )

                option_type = (
                    raw_row["OPTION_TYP"]
                    .strip()
                    .upper()
                )

                # -----------------------------------------------------------
                # Optional market data
                # -----------------------------------------------------------

                open_p = _parse_number(
                    raw_row.get("OPEN")
                )

                high_p = _parse_number(
                    raw_row.get("HIGH")
                )

                low_p = _parse_number(
                    raw_row.get("LOW")
                )

                close_p = _parse_number(
                    raw_row.get("CLOSE")
                )

                settle_p = _parse_number(
                    raw_row.get("SETTLE_PR")
                )

                open_interest = _parse_int(
                    raw_row.get("OPEN_INT")
                )

                chg_in_oi = _parse_int(
                    raw_row.get("CHG_IN_OI")
                )

                contracts = _parse_int(
                    raw_row.get("CONTRACTS")
                )

                # -----------------------------------------------------------
                # Option type validation
                # -----------------------------------------------------------

                if option_type not in (
                    "CE",
                    "PE",
                ):
                    report.invalid_values += 1
                    report.rows_rejected += 1

                    report.errors.append(
                        f"{trading_date} "
                        f"strike={strike}: "
                        f"bad OPTION_TYP "
                        f"{option_type!r}"
                    )

                    continue

                # -----------------------------------------------------------
                # Required option values
                # -----------------------------------------------------------

                if close_p is None or strike is None:

                    report.missing_values += 1
                    report.rows_rejected += 1

                    report.errors.append(
                        f"{trading_date} "
                        f"strike={strike}: "
                        "missing CLOSE or STRIKE_PR"
                    )

                    continue

            except Exception as exc:

                report.rows_rejected += 1

                report.errors.append(
                    f"row {report.rows_read}: {exc}"
                )

                continue

            # ----------------------------------------------------------------
            # Prepare database row
            # ----------------------------------------------------------------

            dates.append(trading_date)

            rows_to_insert.append(
                (
                    underlying,
                    f"{trading_date} 00:00:00",
                    trading_date,
                    expiry,
                    strike,
                    option_type,
                    "1d",
                    open_p,
                    high_p,
                    low_p,
                    close_p,
                    settle_p,
                    open_interest,
                    chg_in_oi,
                    contracts,
                    None,
                )
            )

            report.rows_accepted += 1

    # -----------------------------------------------------------------------
    # Calculate report information
    # -----------------------------------------------------------------------

    if rows_to_insert:

        report.date_start = min(dates)
        report.date_end = max(dates)

        report.trading_day_count = len(
            set(dates)
        )

    # -----------------------------------------------------------------------
    # Create import record
    # -----------------------------------------------------------------------

    import_id = _next_import_id(conn)

    report.import_id = import_id

    conn.execute(
        """
        INSERT INTO imports (
            import_id,
            file_path,
            file_hash,
            symbol,
            kind,
            rows_read,
            rows_accepted,
            rows_rejected,
            duplicates,
            glued_rows_fixed,
            missing_values,
            invalid_values,
            date_start,
            date_end,
            trading_day_count,
            warnings,
            errors
        )
        VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?
        )
        """,
        [
            import_id,
            str(path),
            file_hash,
            symbol,
            kind,
            report.rows_read,
            report.rows_accepted,
            report.rows_rejected,
            report.duplicates,
            report.glued_rows_fixed,
            report.missing_values,
            report.invalid_values,
            report.date_start,
            report.date_end,
            report.trading_day_count,
            json.dumps(report.warnings),
            json.dumps(report.errors),
        ],
    )

    # -----------------------------------------------------------------------
    # Insert option bars
    # -----------------------------------------------------------------------

    for row in rows_to_insert:

        conn.execute(
            """
            INSERT OR REPLACE INTO option_bars (
                underlying,
                timestamp,
                trading_date,
                expiry,
                strike,
                option_type,
                bar_interval,
                open,
                high,
                low,
                close,
                settle,
                open_interest,
                chg_in_oi,
                contracts,
                lot_size,
                import_id
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?
            )
            """,
            [
                *row,
                import_id,
            ],
        )

    return report


# ---------------------------------------------------------------------------
# Main ingestion entry point
# ---------------------------------------------------------------------------

def ingest_path(
    conn: duckdb.DuckDBPyConnection,
    raw_dir: Path,
    rel_path: str,
) -> list[QualityReport]:
    """
    Import CSV files from a path inside the configured raw data directory.

    Examples:

        ingest_path(conn, raw_dir, "demo")

        ingest_path(conn, raw_dir, "demo/DEMOSTK_equity.csv")

        ingest_path(conn, raw_dir, "demo/DEMOSTK_options.csv")

    If rel_path points to a directory:
        every *.csv file inside that directory is considered.

    If rel_path points to a file:
        only that file is imported.

    IMPORTANT:
        This function NEVER calls Zerodha.
        This function NEVER resolves NSE instrument tokens.
        It is strictly local CSV ingestion.
    """

    if not rel_path:
        raise ValueError(
            "Import path cannot be empty"
        )

    raw_dir = Path(raw_dir)

    # -----------------------------------------------------------------------
    # Resolve paths safely
    # -----------------------------------------------------------------------

    root = raw_dir.resolve()

    target = (
        root / rel_path
    ).resolve()

    # Prevent path traversal outside RAW_DIR.
    if target != root and root not in target.parents:
        raise ValueError(
            "Import path must stay inside "
            "the configured raw data directory"
        )

    # -----------------------------------------------------------------------
    # Determine files
    # -----------------------------------------------------------------------

    if target.is_dir():

        files = sorted(
            target.glob("*.csv")
        )

    elif target.is_file():

        files = [target]

    else:

        raise FileNotFoundError(
            "No such file or directory under raw dir: "
            f"{target}"
        )

    # -----------------------------------------------------------------------
    # Import files
    # -----------------------------------------------------------------------

    reports: list[QualityReport] = []

    for file_path in files:

        filename_upper = file_path.name.upper()

        # ---------------------------------------------------------------
        # Equity
        # ---------------------------------------------------------------

        if filename_upper.endswith(
            "_EQUITY.CSV"
        ):

            reports.append(
                ingest_equity_file(
                    conn,
                    file_path,
                )
            )

        # ---------------------------------------------------------------
        # Options
        # ---------------------------------------------------------------

        elif filename_upper.endswith(
            "_OPTIONS.CSV"
        ):

            reports.append(
                ingest_options_file(
                    conn,
                    file_path,
                )
            )

        # ---------------------------------------------------------------
        # Unknown CSV
        # ---------------------------------------------------------------

        else:

            reports.append(
                QualityReport(
                    file_path=str(file_path),
                    symbol="?",
                    kind="unknown",
                    errors=[
                        "Filename does not match "
                        "<SYMBOL>_equity.csv / "
                        "<SYMBOL>_options.csv: "
                        f"{file_path.name}"
                    ],
                )
            )

    return reports