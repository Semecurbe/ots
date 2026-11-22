"""miniSEED reading with an explicit gap policy (gaps are never filled silently)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from obspy import Stream, Trace, UTCDateTime, read

from ..core.errors import FileFormatError, ParameterError
from ..core.signal import Signal, file_sha256, to_utc

GAP_POLICIES = ("longest", "fill", "split", "error")
#: Day file of an SDS archive: ``NET.STA.LOC.CHA.TYPE.YEAR.DAY`` (``XX.LORA.HA.BHE.D.2026.264``).
SDS_NAME = re.compile(r"^[^.]*\.[^.]+\.[^.]*\.[^.]+\.[A-Z]\.\d{4}\.\d{3}$")


def file_title(path: Path) -> str:
    """Default title of a loaded file: its name without extension, or its whole name for a
    day file of an SDS archive, whose last part is the day of the year."""
    return path.name if SDS_NAME.match(path.name) else path.stem


def _gap_list(stream: Stream) -> list[dict]:
    """Gaps (positive) and overlaps (negative) of a single-channel stream."""
    out = []
    for gap in stream.get_gaps():
        t1, t2, duration = gap[4], gap[5], float(gap[6])
        kind = "gap" if duration > 0 else "overlap"
        out.append({"type": kind, "start": str(t1), "end": str(t2), "duration": abs(duration)})
    return out


def read_obspy(
    path: str | Path,
    fmt: str | None = None,
    select: str | None = None,
    starttime: Any = None,
    endtime: Any = None,
    gaps: str = "longest",
    **attrs: Any,
) -> list[Signal]:
    """Read a miniSEED file (or any format ObsPy can read) into signals, one per channel.

    Parameters
    ----------
    path : str or Path
        File to read.
    fmt : str, optional
        ObsPy format name (``MSEED`` by default for miniSEED files, auto-detected otherwise).
    select : str, optional
        NSLC pattern, e.g. ``"*.*.*.HH?"``.
    starttime, endtime : optional
        Read only this time window.
    gaps : {"longest", "fill", "split", "error"}
        Gap policy: keep the longest continuous segment (default), fill gaps by linear
        interpolation, return one signal per continuous segment, or refuse the file. Gaps are
        always recorded in ``Signal.gaps``.
    **attrs
        Signal attributes applied to every signal (``title``, ``unit``, ``sensitivity``,
        ``full_scale``, ``metadata``). The title defaults to the file name without its
        extension.
    """
    if gaps not in GAP_POLICIES:
        raise ParameterError(f"gaps must be one of {', '.join(GAP_POLICIES)}")
    path = Path(path)
    if not path.is_file():
        raise FileFormatError(f"File not found: {path}")
    kwargs: dict[str, Any] = {}
    if starttime is not None:
        kwargs["starttime"] = to_utc(starttime)
    if endtime is not None:
        kwargs["endtime"] = to_utc(endtime)
    try:
        stream = read(str(path), format=fmt, **kwargs) if fmt else read(str(path), **kwargs)
    except Exception as exc:
        raise FileFormatError(f"Cannot read {path.name}: {exc}") from exc
    if select:
        stream = stream.select(id=select)
    if len(stream) == 0:
        matching = f" matching {select!r}" if select else ""
        raise FileFormatError(f"No data in {path.name}{matching}")

    return _stream_signals(stream, gaps, attrs, lambda tr: file_title(path), str(path),
                           file_sha256(path), f"loaded from {path.name}")


def _stream_signals(stream: Stream, gaps: str, attrs: dict[str, Any],
                    title: Callable[[Trace], str], source: str, sha: str,
                    history: str) -> list[Signal]:
    """One signal per channel of ``stream``, its records merged under the gap policy;
    ``title(trace)`` gives the title of each (continuous) trace."""
    signals: list[Signal] = []
    for trace_id in sorted({tr.id for tr in stream}):
        sub = stream.select(id=trace_id)
        sub.sort(["starttime"])
        gap_info = _gap_list(sub)
        real_gaps = [g for g in gap_info if g["type"] == "gap"]
        try:
            merged = sub.copy().merge(method=1, fill_value=None)
        except Exception as exc:
            raise FileFormatError(f"Cannot merge the records of {trace_id}: {exc}") from exc
        if real_gaps and gaps == "error":
            listing = "; ".join(f"{g['start']} ({g['duration']:.3f} s)" for g in real_gaps)
            raise FileFormatError(f"{trace_id} has {len(real_gaps)} gap(s): {listing}")
        if real_gaps and gaps == "fill":
            traces = sub.copy().merge(method=1, fill_value="interpolate").traces
            action = "filled by linear interpolation"
        elif real_gaps:
            traces = merged.split().traces
            if gaps == "longest":
                traces = [max(traces, key=lambda tr: tr.stats.npts)]
                action = "longest continuous segment kept"
            else:
                action = "split into continuous segments"
        else:
            traces = merged.traces
            action = ""
        for g in gap_info:
            g["action"] = action if g["type"] == "gap" else "overlap merged"
        for tr in traces:
            sig = Signal.from_trace(
                tr,
                title=title(tr),
                source=source,
                sha256=sha,
                gaps=[dict(g) for g in gap_info],
                history=[history],
            )
            _apply_attrs(sig, attrs)
            signals.append(sig)
    return signals


def span_title(paths: Sequence[Path]) -> str:
    """Title of several day files of one channel: ``XX.LORA.HA.BHE.D.2026.252-264``
    (``…2025.360-2026.005`` across a year); the name of the first file followed by the number
    of files otherwise."""
    names = sorted(p.name for p in paths)
    if len(names) == 1:
        return file_title(Path(names[0]))
    parts = [n.split(".") for n in names]
    if all(SDS_NAME.match(n) for n in names) and len({".".join(p[:5]) for p in parts}) == 1:
        first, last = parts[0], parts[-1]
        end = last[6] if first[5] == last[5] else f"{last[5]}.{last[6]}"
        return f"{'.'.join(first[:7])}-{end}"
    return f"{Path(names[0]).stem} (+{len(names) - 1} files)"


def _covering(files: Sequence[Path], start: UTCDateTime, end: UTCDateTime) -> list[Path]:
    """Day files whose day meets ``[start, end]`` (all the files when they are not day
    files of an archive)."""
    out = []
    for path in files:
        if not SDS_NAME.match(path.name):
            return list(files)
        year, doy = path.name.split(".")[5:7]
        day = UTCDateTime(year=int(year), julday=int(doy))
        if day <= end and day + 86400 > start:
            out.append(path)
    return out or list(files)


def read_files(
    paths: Sequence[str | Path],
    fmt: str | None = None,
    select: str | None = None,
    starttime: Any = None,
    endtime: Any = None,
    gaps: str = "longest",
    **attrs: Any,
) -> list[Signal]:
    """Read several miniSEED files (day files of an archive…) into one signal per channel.

    The records of all the files are merged per channel under the ``gaps`` policy, as for one
    file (:func:`read_obspy`): a missing day is a gap. ``starttime`` and ``endtime`` limit the
    records read. The title of a signal spans its files (:func:`span_title`); its SHA-256 is
    the digest of the names and digests of the files read, in order.
    """
    if gaps not in GAP_POLICIES:
        raise ParameterError(f"gaps must be one of {', '.join(GAP_POLICIES)}")
    files = sorted({Path(p) for p in paths})
    if not files:
        raise FileFormatError("No file to read")
    for path in files:
        if not path.is_file():
            raise FileFormatError(f"File not found: {path}")
    kwargs: dict[str, Any] = {}
    if starttime is not None:
        kwargs["starttime"] = to_utc(starttime)
    if endtime is not None:
        kwargs["endtime"] = to_utc(endtime)
    stream = Stream()
    used: list[Path] = []
    for path in files:
        try:
            part = read(str(path), format=fmt, **kwargs) if fmt else read(str(path), **kwargs)
        except Exception as exc:
            raise FileFormatError(f"Cannot read {path.name}: {exc}") from exc
        if select:
            part = part.select(id=select)
        if len(part):
            stream += part
            used.append(path)
    if len(stream) == 0:
        matching = f" matching {select!r}" if select else ""
        raise FileFormatError(f"No data{matching} in the {len(files)} files for this window")
    digest = hashlib.sha256()
    for path in used:
        digest.update(f"{path.name} {file_sha256(path)}\n".encode())
    by_channel = {tr.id: [p for p in used if p.name.startswith(tr.id + ".")] for tr in stream}
    folder = used[0].parent if len({p.parent for p in used}) == 1 else Path(".")
    source = (f"{len(used)} files in {folder}: {used[0].name} … {used[-1].name}"
              if len(used) > 1 else str(used[0]))
    def title(tr: Trace) -> str:  # the days of each continuous segment
        return span_title(_covering(by_channel.get(tr.id) or used, tr.stats.starttime,
                                    tr.stats.endtime))

    return _stream_signals(stream, gaps, attrs, title, source, digest.hexdigest(),
                           f"loaded from {len(used)} files ({used[0].name} … {used[-1].name})")


def _apply_attrs(sig: Signal, attrs: dict[str, Any]) -> None:
    for key, value in attrs.items():
        if value is None:
            continue
        if key == "metadata":
            sig.metadata.update(value)
        elif key in ("title", "unit", "sensitivity", "full_scale"):
            setattr(sig, key, value)
        else:
            raise ParameterError(f"Unknown option for miniSEED files: {key}")
