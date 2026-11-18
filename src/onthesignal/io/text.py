"""Multi-column text files (one column per channel, optional time column)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from obspy import UTCDateTime

from ..core.errors import FileFormatError, ParameterError
from ..core.signal import Signal, file_sha256, to_utc

_DELIMITERS = {"tab": "\t", "space": None, "whitespace": None}


def _read_lines(path: Path, encoding: str) -> list[str]:
    try:
        return path.read_text(encoding=encoding).splitlines()
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1").splitlines()


def _detect_delimiter(line: str, decimal: str) -> str | None:
    if "\t" in line:
        return "\t"
    if ";" in line:
        return ";"
    if "," in line and decimal != ",":
        return ","
    return None  # any whitespace


def _split(line: str, delimiter: str | None) -> list[str]:
    cells = line.split(delimiter) if delimiter is not None else line.split()
    return [c.strip() for c in cells if c.strip() != "" or delimiter is not None]


def _to_float(cell: str, decimal: str) -> float:
    if decimal == ",":
        cell = cell.replace(",", ".")
    return float(cell)


def _per_channel(value: Any, n: int, name: str) -> list:
    if value is None or isinstance(value, (str, int, float)):
        return [value] * n
    values = list(value)
    if len(values) != n:
        raise ParameterError(f"{name} must have {n} values (one per channel), got {len(values)}")
    return values


def read_text(
    path: str | Path,
    n_channels: int | None = None,
    time_col: int | None = None,
    fs: float | None = None,
    delimiter: str | None = None,
    decimal: str = ".",
    skiprows: int | None = None,
    comment: str = "#",
    time_format: str = "relative",
    starttime: Any = None,
    names: Sequence[str] | None = None,
    title: Any = None,
    units: Any = None,
    sensitivities: Any = None,
    full_scale: float | None = None,
    time_tolerance: float = 0.01,
    resample: bool = False,
    encoding: str = "utf-8",
) -> list[Signal]:
    """Read a multi-column text file, one signal per data column.

    Parameters
    ----------
    path : str or Path
        File to read.
    n_channels : int
        Number of data columns. Mandatory: the column count is checked against it.
    time_col : int, optional
        Index of the time column (``None``: no time column, ``fs`` is then mandatory).
    fs : float, optional
        Sampling rate in Hz; derived from the time column when there is one.
    delimiter : str, optional
        Column separator; detected automatically (tab, ``;``, ``,`` or whitespace).
    decimal : {".", ","}
        Decimal separator.
    skiprows : int, optional
        Header lines to skip; by default leading non-numeric lines are skipped.
    comment : str
        Lines starting with this string are ignored.
    time_format : {"relative", "epoch", "iso"}
        Time column contents: seconds (relative to ``starttime``), epoch seconds or ISO dates.
    starttime : optional
        Time origin when the time column is relative or absent (default 1970-01-01).
    names : sequence of str, optional
        Per-channel codes: full ``NET.STA.LOC.CHA`` ids or channel codes.
    title : str or sequence of str, optional
        Signal title, for all channels or one per channel (default: the file name without
        its extension).
    units, sensitivities : str/float or sequence, optional
        Unit and sensitivity, for all channels or one per channel.
    time_tolerance : float
        Maximum relative deviation of the time step from its median (default 1 %).
    resample : bool
        Interpolate an irregular time column onto a regular grid instead of failing.
    """
    path = Path(path)
    if not path.is_file():
        raise FileFormatError(f"File not found: {path}")
    if n_channels is None or int(n_channels) < 1:
        raise ParameterError("n_channels (number of data columns) is required for text files")
    n_channels = int(n_channels)
    if decimal not in (".", ","):
        raise ParameterError("decimal must be '.' or ','")
    if time_format not in ("relative", "epoch", "iso"):
        raise ParameterError("time_format must be 'relative', 'epoch' or 'iso'")
    if delimiter is not None:
        delimiter = _DELIMITERS.get(delimiter, delimiter)

    lines = [ln.strip() for ln in _read_lines(path, encoding)]
    lines = [ln for ln in lines if ln and not (comment and ln.startswith(comment))]
    if skiprows:
        lines = lines[int(skiprows):]
    if not lines:
        raise FileFormatError(f"{path.name} contains no data")

    n_expected = n_channels + (1 if time_col is not None else 0)
    data_cols = [i for i in range(n_expected) if i != time_col]
    rows: list[list[float]] = []
    times_text: list[str] = []
    started = False
    for number, line in enumerate(lines, start=1):
        delim = delimiter if delimiter is not None else _detect_delimiter(line, decimal)
        cells = _split(line, delim)
        try:
            for i, cell in enumerate(cells):
                if not (time_col is not None and i == time_col and time_format == "iso"):
                    _to_float(cell, decimal)
        except ValueError:
            if not started and skiprows is None:
                continue  # header line
            raise FileFormatError(
                f"{path.name}, data line {number}: cannot read {line!r}"
            ) from None
        started = True
        if len(cells) != n_expected:
            raise FileFormatError(
                f"{path.name}: {len(cells)} column(s) found, {n_expected} expected "
                f"({n_channels} channel(s)" + (" + 1 time column)" if time_col is not None else ")")
            )
        rows.append([_to_float(cells[i], decimal) for i in data_cols])
        if time_col is not None:
            times_text.append(cells[time_col])
    if not rows:
        raise FileFormatError(f"{path.name} contains no numeric data")
    table = np.asarray(rows, dtype=np.float64)

    origin = to_utc(starttime) if starttime is not None else UTCDateTime(0)
    note = ""
    if time_col is not None:
        if time_format == "iso":
            t = np.array([UTCDateTime(x).timestamp for x in times_text])
        else:
            t = np.array([_to_float(x, decimal) for x in times_text])
        if t.size < 2:
            raise FileFormatError("At least two samples are needed to derive the sampling rate")
        steps = np.diff(t)
        step = float(np.median(steps))
        if step <= 0:
            raise FileFormatError("The time column is not increasing")
        deviation = float(np.max(np.abs(steps - step)) / step)
        fs_file = 1.0 / step
        if fs is not None and abs(fs - fs_file) > 0.01 * fs_file:
            raise ParameterError(f"fs={fs} Hz contradicts the time column ({fs_file:.6g} Hz)")
        fs = fs_file
        t0 = origin + t[0] if time_format == "relative" else UTCDateTime(t[0])
        if deviation > time_tolerance:
            if not resample:
                raise FileFormatError(
                    f"Irregular time column: the step deviates by {deviation:.1%} from its median "
                    f"(tolerance {time_tolerance:.0%}). Use resample=True to interpolate onto a "
                    "regular grid."
                )
            grid = t[0] + np.arange(int(np.floor((t[-1] - t[0]) / step)) + 1) * step
            table = np.column_stack([np.interp(grid, t, table[:, j]) for j in range(n_channels)])
            note = f"irregular time column resampled at {fs:.6g} Hz (linear interpolation)"
    else:
        if fs is None:
            raise ParameterError("fs (sampling rate) is required when the file has no time column")
        t0 = origin

    station = re.sub(r"[^A-Za-z0-9]", "", path.stem).upper() or "TXT"
    names_list = (
        _per_channel(names, n_channels, "names") if names is not None else [None] * n_channels
    )
    titles = _per_channel(title, n_channels, "title")
    units_list = _per_channel(units, n_channels, "units")
    sens_list = _per_channel(sensitivities, n_channels, "sensitivities")
    sha = file_sha256(path)
    signals = []
    for j in range(n_channels):
        net, sta, loc, cha = "XX", station, "", f"C{j + 1:02d}"
        if names_list[j]:
            parts = str(names_list[j]).split(".")
            if len(parts) == 4:
                net, sta, loc, cha = parts
            else:
                cha = str(names_list[j])
        history = [f"loaded from {path.name} (column {data_cols[j]})"]
        if note:
            history.append(note)
        sig = Signal(
            table[:, j], fs, starttime=t0, network=net, station=sta, location=loc, channel=cha,
            title=titles[j] if titles[j] is not None else path.stem,
            source=str(path), sha256=sha, history=history, full_scale=full_scale,
        )
        if units_list[j] is not None:
            sig.unit = units_list[j]
        if sens_list[j] is not None:
            sig.sensitivity = float(sens_list[j])
        signals.append(sig)
    return signals
