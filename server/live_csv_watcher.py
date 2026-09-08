"""Poll appended OHLCV CSV rows and pass them through live ingestion."""
from __future__ import annotations

import asyncio
import csv
import logging
import os
from pathlib import Path

from server import live_service
from server.config import settings

logger = logging.getLogger("live_csv_watcher")

_REQUIRED_COLUMNS = {
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
}


class LiveCsvWatcher:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._processed_rows: dict[Path, int] = {}
        self.invalid_rows = 0
        self.last_file: str | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return

        # Vercel's deployed filesystem is read-only.
        # The live CSV watcher requires a writable directory and a
        # persistent process, so it must not start in Vercel serverless.
        if os.getenv("VERCEL") == "1":
            logger.info(
                "Live CSV watcher disabled on Vercel serverless"
            )
            return

        settings.LIVE_DIR.mkdir(parents=True, exist_ok=True)

        self._task = asyncio.create_task(self._run())

        logger.info(
            "Live CSV watcher started: %s",
            settings.LIVE_DIR,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(
                self._task,
                return_exceptions=True,
            )

        self._task = None

    async def _run(self) -> None:
        while True:
            for path in sorted(settings.LIVE_DIR.glob("*.csv")):
                await self._process_file(path)

            await asyncio.sleep(settings.LIVE_POLL_SECONDS)

    async def _process_file(self, path: Path) -> None:
        try:
            rows = self._read_new_rows(path)

            for row in rows:
                try:
                    await live_service.ingest(
                        row,
                        source="csv",
                    )
                except Exception as exc:
                    self.invalid_rows += 1
                    self.last_error = f"{path.name}: {exc}"

                    logger.warning(
                        "Skipping invalid row in %s: %s",
                        path.name,
                        exc,
                    )

            if rows:
                self.last_file = path.name

                if not self.last_error:
                    self.last_error = None

        except (
            OSError,
            csv.Error,
            ValueError,
        ) as exc:
            self.last_error = f"{path.name}: {exc}"

            logger.warning(
                "Could not process %s: %s",
                path.name,
                exc,
            )

    def _read_new_rows(
        self,
        path: Path,
    ) -> list[dict[str, str | None]]:
        with path.open(
            newline="",
            encoding="utf-8-sig",
        ) as handle:
            reader = csv.DictReader(handle)

            columns = set(reader.fieldnames or ())

            missing = _REQUIRED_COLUMNS - columns

            if missing:
                raise ValueError(
                    f"missing columns: {', '.join(sorted(missing))}"
                )

            rows = list(reader)

        previous_count = self._processed_rows.get(
            path,
            0,
        )

        if len(rows) < previous_count:
            previous_count = 0

        self._processed_rows[path] = len(rows)

        return rows[previous_count:]


live_csv_watcher = LiveCsvWatcher()