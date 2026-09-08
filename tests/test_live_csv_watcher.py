from pathlib import Path

import pytest

from server.live_csv_watcher import LiveCsvWatcher


def test_csv_watcher_reads_only_appended_rows(tmp_path: Path):
    path = tmp_path / "RELIANCE.csv"
    path.write_text(
        "timestamp,symbol,open,high,low,close,volume\n"
        "2026-09-03T09:15:01,RELIANCE,1420,1421,1419,1420.5,1200\n",
        encoding="utf-8",
    )
    watcher = LiveCsvWatcher()

    assert len(watcher._read_new_rows(path)) == 1
    assert watcher._read_new_rows(path) == []

    with path.open("a", encoding="utf-8") as handle:
        handle.write("2026-09-03T09:16:01,RELIANCE,1421,1422,1420,1421.5,900\n")
    assert len(watcher._read_new_rows(path)) == 1


def test_csv_watcher_rejects_missing_columns(tmp_path: Path):
    path = tmp_path / "RELIANCE.csv"
    path.write_text("timestamp,symbol,close\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing columns"):
        LiveCsvWatcher()._read_new_rows(path)
