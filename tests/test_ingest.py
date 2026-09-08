"""Unit tests: ingestion mechanics on small synthetic CSVs."""
import csv
from pathlib import Path

import pytest

from server.database import reset_database_for_tests
from server.ingest import ingest_equity_file, ingest_options_file, ingest_path


EQUITY_HEADER = ["SYMBOL", "SERIES", "DATE", "PREV_CLOSE", "OPEN", "HIGH", "LOW",
                 "LAST", "CLOSE", "VWAP", "VOLUME", "TURNOVER", "TOTAL_TRADES",
                 "DELIVERABLE_QTY", "DELIVERABLE_PCT"]


def _write_equity_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EQUITY_HEADER)
        w.writeheader()
        w.writerows(rows)


def test_equity_ingest_accepts_clean_rows(tmp_path):
    conn = reset_database_for_tests()
    rows = [
        dict(SYMBOL="TESTCO", SERIES="EQ", DATE="03-AUG-2026", PREV_CLOSE=100, OPEN=101,
             HIGH=105, LOW=99, LAST=103, CLOSE=103, VWAP=102, VOLUME=1000, TURNOVER=102000,
             TOTAL_TRADES=50, DELIVERABLE_QTY=400, DELIVERABLE_PCT=40.0),
    ]
    f = tmp_path / "TESTCO_equity.csv"
    _write_equity_csv(f, rows)
    report = ingest_equity_file(conn, f)
    assert report.rows_read == 1
    assert report.rows_accepted == 1
    assert report.rows_rejected == 0


def test_equity_ingest_rejects_ohlc_out_of_range(tmp_path):
    conn = reset_database_for_tests()
    rows = [
        dict(SYMBOL="TESTCO", SERIES="EQ", DATE="03-AUG-2026", PREV_CLOSE=100, OPEN=101,
             HIGH=95, LOW=99, LAST=103, CLOSE=103, VWAP=102, VOLUME=1000, TURNOVER=102000,
             TOTAL_TRADES=50, DELIVERABLE_QTY=400, DELIVERABLE_PCT=40.0),
    ]
    f = tmp_path / "TESTCO_equity.csv"
    _write_equity_csv(f, rows)
    report = ingest_equity_file(conn, f)
    assert report.rows_accepted == 0
    assert report.rows_rejected == 1


def test_equity_ingest_rejects_missing_close(tmp_path):
    conn = reset_database_for_tests()
    rows = [
        dict(SYMBOL="TESTCO", SERIES="EQ", DATE="03-AUG-2026", PREV_CLOSE=100, OPEN=101,
             HIGH=105, LOW=99, LAST="", CLOSE="", VWAP=102, VOLUME=1000, TURNOVER=102000,
             TOTAL_TRADES=50, DELIVERABLE_QTY=400, DELIVERABLE_PCT=40.0),
    ]
    f = tmp_path / "TESTCO_equity.csv"
    _write_equity_csv(f, rows)
    report = ingest_equity_file(conn, f)
    assert report.rows_rejected == 1
    assert report.missing_values >= 1


def test_reimporting_identical_file_is_noop(tmp_path):
    conn = reset_database_for_tests()
    rows = [
        dict(SYMBOL="TESTCO", SERIES="EQ", DATE="03-AUG-2026", PREV_CLOSE=100, OPEN=101,
             HIGH=105, LOW=99, LAST=103, CLOSE=103, VWAP=102, VOLUME=1000, TURNOVER=102000,
             TOTAL_TRADES=50, DELIVERABLE_QTY=400, DELIVERABLE_PCT=40.0),
    ]
    f = tmp_path / "TESTCO_equity.csv"
    _write_equity_csv(f, rows)
    r1 = ingest_equity_file(conn, f)
    r2 = ingest_equity_file(conn, f)
    assert r1.skipped_duplicate_file is False
    assert r2.skipped_duplicate_file is True
    count = conn.execute("SELECT COUNT(*) FROM equity_bars WHERE symbol='TESTCO'").fetchone()[0]
    assert count == 1  # not duplicated


def test_bad_filename_is_rejected_not_guessed(tmp_path):
    conn = reset_database_for_tests()
    f = tmp_path / "weird_filename.csv"
    f.write_text("a,b\n1,2\n")
    reports = ingest_path(conn, tmp_path, ".")
    assert len(reports) == 1
    assert reports[0].kind == "unknown"
    assert reports[0].errors


def test_import_path_cannot_escape_raw_directory(tmp_path):
    conn = reset_database_for_tests()
    outside = tmp_path.parent / "outside_equity.csv"
    outside.write_text("SYMBOL,DATE,OPEN,HIGH,LOW,CLOSE\nTESTCO,03-AUG-2026,1,2,0.5,1.5\n")

    with pytest.raises(ValueError, match="inside the configured raw data directory"):
        ingest_path(conn, tmp_path, "../outside_equity.csv")
