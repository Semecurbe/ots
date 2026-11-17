"""File input/output.

:func:`read` returns plain :class:`~onthesignal.Signal` objects; the public
:func:`onthesignal.load` additionally registers them in the current session.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.signal import Signal
from .export import save_signal
from .mseed import GAP_POLICIES, read_obspy
from .text import read_text

MSEED_EXTENSIONS = {".mseed", ".miniseed", ".ms", ".seed"}
TEXT_EXTENSIONS = {".txt", ".csv", ".dat", ".tsv", ".asc"}


def detect_format(path: str | Path) -> str:
    """``mseed``, ``txt`` or ``obspy`` (any other format, auto-detected by ObsPy)."""
    suffix = Path(path).suffix.lower()
    if suffix in MSEED_EXTENSIONS:
        return "mseed"
    if suffix in TEXT_EXTENSIONS:
        return "txt"
    return "obspy"


def read(path: str | Path, fmt: str | None = None, **options: Any) -> list[Signal]:
    """Read a file into a list of signals (format from the extension unless ``fmt`` is given)."""
    kind = (fmt or detect_format(path)).lower()
    if kind in ("txt", "text", "csv"):
        return read_text(path, **options)
    if kind in ("mseed", "miniseed"):
        return read_obspy(path, fmt="MSEED", **options)
    return read_obspy(path, **options)


__all__ = ["GAP_POLICIES", "detect_format", "read", "read_obspy", "read_text", "save_signal"]
