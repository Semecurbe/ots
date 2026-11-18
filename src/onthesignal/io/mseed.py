"""miniSEED reading with an explicit gap policy (gaps are never filled silently)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from obspy import Stream, read

from ..core.errors import FileFormatError, ParameterError
from ..core.signal import Signal, file_sha256, to_utc

GAP_POLICIES = ("longest", "fill", "split", "error")


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

    sha = file_sha256(path)
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
                title=path.stem,
                source=str(path),
                sha256=sha,
                gaps=[dict(g) for g in gap_info],
                history=[f"loaded from {path.name}"],
            )
            _apply_attrs(sig, attrs)
            signals.append(sig)
    return signals


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
