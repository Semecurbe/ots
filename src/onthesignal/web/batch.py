"""Batch processing in the web interface (web specification §8.5).

A :class:`BatchRun` runs :func:`onthesignal.scripts.batch` in a job thread. It follows the
batch file by file and keeps the rows obtained so far, which the ``Batch`` tab of every
browser tab reads. A failing file or signal is recorded in the ``error`` column and does not
stop the batch; ``Stop`` ends it before the next file.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.units import fmt_num
from ..scripts import batch, batch_columns, batch_summary, write_table

_ids = itertools.count(1)


@dataclass
class BatchSettings:
    """Choices of the batch form."""

    #: Registered analysis (``noise``) or script name.
    target: str
    #: Files or glob patterns, relative to the project.
    patterns: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    #: Options of the file reader (``unit``, ``sensitivity``, ``n_channels``…).
    read_options: dict[str, Any] = field(default_factory=dict)
    #: Output table (``.csv`` or ``.json``) written at the end, if given.
    out: str | None = None


class BatchRun:
    """One batch: settings, progress and rows."""

    def __init__(self, settings: BatchSettings, files: list[Path]) -> None:
        self.id = next(_ids)
        self.settings = settings
        self.files = files
        self.total = len(files)
        self.done = 0
        self.current = ""
        self.rows: list[dict] = []
        self.state = "running"  # running, done, stopped, failed
        self.error = ""
        self.out: Path | None = None
        self.started = time.time()
        self.ended: float | None = None
        self.version = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def title(self) -> str:
        return f"Batch {self.settings.target}"

    def _progress(self, done: int, total: int, path: Path | None, rows: list[dict]) -> None:
        with self._lock:
            self.done, self.total = done, total
            self.current = path.name if path is not None else ""
            self.rows = list(rows)
            self.version += 1

    def run(self, job: Any = None) -> list[dict]:
        """Job thread: process every file, then write the output table if asked."""
        s = self.settings
        try:
            rows = batch(s.target, [str(p) for p in self.files], read_options=s.read_options,
                         on_progress=self._progress, should_stop=self._stop.is_set, **s.params)
            if s.out:
                self.out = write_table(rows, s.out)
            self.state = "stopped" if self._stop.is_set() else "done"
            return rows
        except Exception as exc:
            self.state, self.error = "failed", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.ended = time.time()
            self.version += 1

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def failures(self) -> int:
        return sum(1 for r in self.rows if r.get("error"))

    def table(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Columns and rows for display: numbers with the console formatting, units in the
        header, file names without their folder."""
        with self._lock:
            rows = list(self.rows)
        units: dict[str, str] = {}
        for row in rows:
            units.update(row.get("units", {}))
        columns = [c for c in batch_columns(rows)
                   if c not in ("warnings", "error") or any(r.get(c) for r in rows)]
        header = [{"name": c, "label": f"{c} ({units[c]})" if c in units else c, "field": c,
                   "align": "left" if c in ("file", "signal", "warnings", "error") else "right",
                   "sortable": True} for c in columns]
        lines = []
        for i, row in enumerate(rows):
            line: dict[str, str] = {"_row": str(i)}
            for c in columns:
                value = row.get(c, "")
                if c == "file":
                    value = Path(str(value)).name
                elif isinstance(value, bool):
                    value = "yes" if value else "no"
                elif isinstance(value, (int, float)):
                    value = fmt_num(value)
                elif isinstance(value, list):
                    value = ", ".join(fmt_num(v) if isinstance(v, (int, float)) else str(v)
                                      for v in value)
                line[c] = "" if value is None else str(value)
            lines.append(line)
        return header, lines

    def summary(self) -> Any:
        """Result of kind ``batch`` for a global report."""
        s = self.settings
        with self._lock:
            rows = list(self.rows)
        return batch_summary(rows, s.target, s.patterns, s.params)


__all__ = ["BatchRun", "BatchSettings"]
