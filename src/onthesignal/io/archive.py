"""Day files of SDS archives: inventory of a folder, loading by channel and time window.

An SDS archive (SeisComP Data Structure) keeps one miniSEED file per channel and per day,
named ``NET.STA.LOC.CHA.TYPE.YEAR.DAY`` (``XX.LORA.HA.BHE.D.2026.264``), usually in
``<root>/YEAR/NET/STA/CHA.TYPE/``. The folder is searched for these names whatever its layout,
so that day files copied or uploaded into one folder are found as well. A day file may hold a
few seconds of the next day (its last record goes past midnight): as the SDS client of ObsPy,
the file of a neighbouring day is read too when the window comes within :data:`BORDER` of
midnight; the records outside the window are skipped.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obspy import UTCDateTime

from ..core.errors import FileFormatError, ParameterError
from ..core.signal import to_utc
from .mseed import SDS_NAME

#: Files examined at most when an archive is searched (a year of 50 channels is 18 250 files).
MAX_FILES = 200_000
#: Seconds around the window in which the file of a neighbouring day is read too.
BORDER = 60.0


@dataclass(frozen=True)
class DayFile:
    """One day file of an archive."""

    path: Path
    channel: str  # NET.STA.LOC.CHA
    sds_type: str  # D for data
    year: int
    doy: int
    size: int

    @property
    def day(self) -> UTCDateTime:
        """Start (00:00 UTC) of the day of the file."""
        return UTCDateTime(year=self.year, julday=self.doy)


@dataclass
class ArchiveChannel:
    """The day files of one channel, in date order."""

    channel: str
    files: list[DayFile] = field(default_factory=list)

    @property
    def first(self) -> UTCDateTime:
        return self.files[0].day

    @property
    def last(self) -> UTCDateTime:
        """End of the last day (00:00 UTC of the day after)."""
        return self.files[-1].day + 86400

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    def missing_days(self) -> list[UTCDateTime]:
        """Days without a file between the first and the last one."""
        have = {f.day.julday + 1000 * f.day.year for f in self.files}
        out, day = [], self.first
        while day < self.last:
            if day.julday + 1000 * day.year not in have:
                out.append(day)
            day += 86400
        return out

    def files_for(self, starttime: Any = None, endtime: Any = None) -> list[Path]:
        """Files holding the window ``[starttime, endtime]`` (the whole channel by default),
        with the file of a neighbouring day when the window comes near midnight."""
        start = to_utc(starttime) if starttime is not None else self.first
        end = to_utc(endtime) if endtime is not None else self.last
        if end <= start:
            raise ParameterError("The end of the window must come after its start")
        low, high = start - BORDER, end + BORDER
        return [f.path for f in self.files if f.day < high and f.day + 86400 > low]

    def row(self) -> dict[str, Any]:
        """Line of an inventory (console, web interface, AI tools)."""
        missing = self.missing_days()
        return {"channel": self.channel, "from": self.first.strftime("%Y-%m-%d"),
                "to": (self.last - 1).strftime("%Y-%m-%d"), "days": len(self.files),
                "missing_days": len(missing), "size_MB": round(self.size / 1e6, 1)}


def scan(folder: str | Path, max_files: int = MAX_FILES) -> dict[str, ArchiveChannel]:
    """Channels of the day files found in ``folder`` and its subfolders, by channel code.

    Hidden folders are skipped; a folder holding more than ``max_files`` files is refused
    (choose a deeper folder of the archive).
    """
    root = Path(folder)
    if not root.is_dir():
        raise FileFormatError(f"Not a folder: {root}")
    found: dict[str, ArchiveChannel] = {}
    seen = 0
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if not d.startswith("."))
        for name in names:
            seen += 1
            if seen > max_files:
                raise ParameterError(f"More than {max_files} files under {root}: choose a "
                                     "folder of the archive closer to the channels")
            if not SDS_NAME.match(name):
                continue
            net, sta, loc, cha, sds_type, year, doy = name.split(".")
            path = Path(directory) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            channel = f"{net}.{sta}.{loc}.{cha}"
            found.setdefault(channel, ArchiveChannel(channel)).files.append(
                DayFile(path, channel, sds_type, int(year), int(doy), size))
    for item in found.values():
        item.files.sort(key=lambda f: (f.year, f.doy))
    return dict(sorted(found.items()))


def select_channels(channels: dict[str, ArchiveChannel], pattern: str) -> list[ArchiveChannel]:
    """Channels whose code matches ``pattern`` (``XX.LORA.HA.BHE``, ``*.BH?``…)."""
    chosen = [c for code, c in channels.items() if fnmatch.fnmatchcase(code, pattern)]
    if not chosen:
        known = ", ".join(channels) or "none"
        raise ParameterError(f"No channel matches {pattern!r} (channels found: {known})")
    return chosen


__all__ = ["BORDER", "MAX_FILES", "ArchiveChannel", "DayFile", "scan", "select_channels"]
