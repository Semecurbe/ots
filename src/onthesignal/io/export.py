"""Export of signals to miniSEED, text and CSV."""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np

from ..core.errors import FileFormatError, OnTheSignalWarning
from ..core.signal import Signal

_SEED_LENGTHS = {"network": 2, "station": 5, "location": 2, "channel": 3}


def save_signal(signal: Signal, path: str | Path, fmt: str | None = None) -> Path:
    """Write ``signal`` to ``path``.

    The format follows the extension (``.mseed`` / ``.ms``, ``.txt``, ``.csv``) unless ``fmt``
    is given. miniSEED stores counts (STEIM2 for integer counts, FLOAT64 otherwise); SEED codes
    longer than allowed are truncated with a warning. Text formats write a commented header
    followed by two columns: time in seconds from the start, value in counts.
    """
    path = Path(path)
    kind = (fmt or path.suffix.lstrip(".")).lower()
    if kind in ("mseed", "ms", "miniseed"):
        tr = signal.to_trace()
        for attr, length in _SEED_LENGTHS.items():
            value = getattr(tr.stats, attr)
            if len(value) > length:
                warnings.warn(
                    f"{attr} code {value!r} truncated to {value[:length]!r} (SEED limit)",
                    OnTheSignalWarning, stacklevel=2,
                )
                setattr(tr.stats, attr, value[:length])
        encoding = "STEIM2" if tr.data.dtype == np.int32 else "FLOAT64"
        try:
            tr.write(str(path), format="MSEED", encoding=encoding)
        except Exception as exc:
            raise FileFormatError(f"Cannot write {path}: {exc}") from exc
        return path
    if kind in ("txt", "csv"):
        sep = "," if kind == "csv" else "\t"
        header = "\n".join(
            [
                f"id: {signal.id}",
                f"starttime: {signal.starttime}",
                f"sampling_rate: {signal.sampling_rate}",
                f"unit: {signal.unit}",
                f"sensitivity: {signal.sensitivity}",
                "columns: time_s, value_counts",
            ]
        )
        table = np.column_stack([signal.times(), signal.data])
        np.savetxt(path, table, delimiter=sep, header=header, comments="# ", fmt="%.10g")
        return path
    raise FileFormatError(f"Unsupported export format: {kind!r} (use .mseed, .txt or .csv)")
