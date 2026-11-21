"""File input/output.

:func:`read` returns plain :class:`~onthesignal.Signal` objects; the public
:func:`onthesignal.load` additionally registers them in the current session.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from ..core.signal import Signal
from .export import save_signal
from .mseed import GAP_POLICIES, SDS_NAME, read_obspy
from .text import read_text

MSEED_EXTENSIONS = {".mseed", ".miniseed", ".ms", ".seed"}
TEXT_EXTENSIONS = {".txt", ".csv", ".dat", ".tsv", ".asc"}
#: Signal files by their extension; other names are recognized by their content.
SIGNAL_EXTENSIONS = MSEED_EXTENSIONS | {".msd", ".sac"}
#: Extensions of files that are never signals (not opened to test their content).
OTHER_EXTENSIONS = TEXT_EXTENSIONS | {
    ".py", ".md", ".qmd", ".toml", ".json", ".yml", ".yaml", ".cfg", ".ini", ".sh", ".j2",
    ".log", ".xml", ".sql", ".html", ".htm", ".css", ".js", ".ipynb", ".png", ".jpg", ".jpeg",
    ".svg", ".gif", ".pdf", ".zip", ".gz", ".tar", ".xz", ".docx", ".xlsx", ".pptx"}


@functools.lru_cache(maxsize=4096)
def _miniseed_content(path: str, mtime: float, size: int) -> bool:
    from obspy.io.mseed.core import _is_mseed

    return bool(_is_mseed(path))


def is_miniseed(path: str | Path) -> bool:
    """True when the file is miniSEED, whatever its name, from its first bytes.

    The day files of an SDS archive (``XX.LORA.HA.BHE.D.2026.264``) have no ``.mseed``
    extension: their content tells what they are.
    """
    try:
        stat = Path(path).stat()
        return _miniseed_content(str(path), stat.st_mtime, stat.st_size)
    except Exception:  # missing or unreadable file, header that ObsPy cannot parse
        return False


def is_signal_file(path: str | Path) -> bool:
    """A file to load as a signal rather than to edit: miniSEED or SAC by its extension, or
    miniSEED by its content (SDS archives). Text data files (``.txt``, ``.csv``) are not:
    they are also edited."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in SIGNAL_EXTENSIONS:
        return True
    if suffix in OTHER_EXTENSIONS:
        return False
    return is_miniseed(path)


def detect_format(path: str | Path) -> str:
    """``mseed``, ``txt`` or ``obspy`` (any other format, auto-detected by ObsPy).

    A file without a miniSEED extension is miniSEED when its content is (SDS archives).
    """
    suffix = Path(path).suffix.lower()
    if suffix in MSEED_EXTENSIONS:
        return "mseed"
    if suffix in TEXT_EXTENSIONS:
        return "txt"
    if suffix not in OTHER_EXTENSIONS and is_miniseed(path):
        return "mseed"
    return "obspy"


def read(path: str | Path, fmt: str | None = None, **options: Any) -> list[Signal]:
    """Read a file into a list of signals (format from the extension unless ``fmt`` is given)."""
    kind = (fmt or detect_format(path)).lower()
    if kind in ("txt", "text", "csv"):
        return read_text(path, **options)
    if kind in ("mseed", "miniseed"):
        return read_obspy(path, fmt="MSEED", **options)
    return read_obspy(path, **options)


__all__ = ["GAP_POLICIES", "SDS_NAME", "detect_format", "is_miniseed", "is_signal_file", "read",
           "read_obspy", "read_text", "save_signal"]
