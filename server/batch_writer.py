"""
Buffered batch writer for live market capture.

Why this exists
---------------
KiteTicker delivers ticks on its own thread and expects the callback to return
immediately. A DuckDB write inside that callback would block the socket, and a
write that raised would kill the tick handler and silently stop the strategy.

So nothing writes to the database from the callback. The callback appends to an
in-memory buffer and returns; a background thread drains that buffer in batches.

    KiteTicker thread  ->  buffer.append()        (microseconds, never raises)
    writer thread      ->  flush every N rows or T seconds

Guarantees this makes, and the reasoning behind each:

- The writer NEVER propagates an exception to the producer. A database failure
  degrades capture; it must not take the live feed down with it.
- Failures are recorded, counted and written to `system_events` -- not
  swallowed. "Do not silently hide errors" is the requirement, and a warning
  logged to stdout that nobody reads is close to silence.
- The buffer is bounded. If the writer stalls, the buffer drops the OLDEST rows
  and counts the drops, so a stuck disk causes measured data loss instead of
  unbounded memory growth and an OOM kill that ends the whole session.
- flush() writes what it has and keeps going on a per-batch failure, so one bad
  batch cannot block every batch behind it.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable

logger = logging.getLogger("batch_writer")


class BatchWriter:
    """Drains an in-memory buffer into the database on a background thread."""

    def __init__(
        self,
        name: str,
        flush_fn: Callable[[list[Any]], int],
        batch_size: int = 200,
        flush_interval: float = 2.0,
        max_buffer: int = 50_000,
        on_error: Callable[[str], None] | None = None,
    ):
        self.name = name
        self._flush_fn = flush_fn
        self.batch_size = max(1, int(batch_size))
        self.flush_interval = max(0.1, float(flush_interval))
        self.max_buffer = max(self.batch_size, int(max_buffer))
        self._on_error = on_error

        self._buffer: deque = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False

        # Counters, all reported by /api/live/capture-status.
        self.queued = 0
        self.written = 0
        self.dropped = 0
        self.failed = 0
        self.flushes = 0
        self.last_write_at: float | None = None
        self.last_error: str | None = None
        self.last_error_at: float | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name=f"batch-writer-{self.name}", daemon=True
        )
        self._thread.start()
        logger.info("Batch writer '%s' started (batch=%d, interval=%.1fs)",
                    self.name, self.batch_size, self.flush_interval)

    def stop(self, drain: bool = True, timeout: float = 5.0) -> None:
        """Stop the writer, flushing what is buffered so a clean shutdown
        does not throw away the last partial batch."""
        if not self._running:
            return
        self._running = False
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if drain:
            self.flush()
        logger.info("Batch writer '%s' stopped (written=%d, dropped=%d, failed=%d)",
                    self.name, self.written, self.dropped, self.failed)

    @property
    def running(self) -> bool:
        return self._running

    # -- producer side (called from the Kite callback thread) --------------

    def append(self, row: Any) -> None:
        """
        Buffer one row. Must be cheap and must never raise -- it runs inside
        the tick callback.
        """
        try:
            with self._lock:
                if len(self._buffer) >= self.max_buffer:
                    # Bounded buffer: shed the oldest row rather than grow without
                    # limit. Losing the oldest tick beats an OOM that ends capture.
                    self._buffer.popleft()
                    self.dropped += 1
                self._buffer.append(row)
                self.queued += 1
                should_wake = len(self._buffer) >= self.batch_size
            if should_wake:
                self._wake.set()
        except Exception as exc:  # noqa: BLE001 -- producer must never see an error
            self.last_error = f"buffer append failed: {exc}"
            logger.error(self.last_error)

    def append_many(self, rows: list[Any]) -> None:
        for row in rows:
            self.append(row)

    # -- consumer side -----------------------------------------------------

    def _take(self) -> list[Any]:
        with self._lock:
            take = min(len(self._buffer), self.batch_size)
            return [self._buffer.popleft() for _ in range(take)]

    def flush(self) -> int:
        """Write every buffered row now. Returns rows written."""
        total = 0
        while True:
            batch = self._take()
            if not batch:
                break
            total += self._write(batch)
        return total

    def _write(self, batch: list[Any]) -> int:
        try:
            written = self._flush_fn(batch)
            self.written += written
            self.flushes += 1
            self.last_write_at = time.time()
            return written
        except Exception as exc:  # noqa: BLE001
            # One failed batch is dropped and counted. Re-queueing it risks an
            # infinite retry loop on a permanently malformed row, which would
            # block every good batch behind it.
            self.failed += len(batch)
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.last_error_at = time.time()
            logger.error("Batch writer '%s' failed on %d rows: %s",
                         self.name, len(batch), exc)
            if self._on_error:
                try:
                    self._on_error(self.last_error)
                except Exception:  # noqa: BLE001
                    pass
            return 0

    def _run(self) -> None:
        while self._running:
            self._wake.wait(timeout=self.flush_interval)
            self._wake.clear()
            try:
                while True:
                    batch = self._take()
                    if not batch:
                        break
                    self._write(batch)
            except Exception as exc:  # noqa: BLE001 -- the loop must survive anything
                self.last_error = f"writer loop error: {exc}"
                logger.exception("Batch writer '%s' loop error", self.name)

    # -- reporting ---------------------------------------------------------

    def stats(self) -> dict:
        with self._lock:
            pending = len(self._buffer)
        return {
            "name": self.name,
            "running": self._running,
            "batch_size": self.batch_size,
            "flush_interval": self.flush_interval,
            "pending": pending,
            "queued": self.queued,
            "written": self.written,
            "dropped": self.dropped,
            "failed": self.failed,
            "flushes": self.flushes,
            "last_write_at": self.last_write_at,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
        }
