"""Data sent to the µPlot charts: decimated, aligned, JSON-safe (web specification R16).

µPlot draws all the series of a panel on one shared abscissa. The curves of a result often
have different abscissas (raw PSD, octave-smoothed PSD, NLNM model): they are decimated
separately, then aligned on the union of their abscissas, missing values being ``None``.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from obspy import UTCDateTime

from ..core.result import Result
from ..core.signal import Signal
from ..core.units import COUNTS, pretty_unit
from ..plot.layouts import comparison_curve
from ..plot.spec import Axis, Band, FigureSpec, HLine, Panel, ResultsSpec, Series
from ..plot.style import (
    AXIS,
    DARK,
    GRID,
    INK,
    INK2,
    MUTED,
    NEUTRAL_WASH,
    REMOVED,
    SEQUENTIAL_STOPS,
    SERIES,
    SURFACE,
)
from ..processing.display import decimate_xy, envelope_indices, window_stats

#: Bins per curve when the width of the chart is not known yet.
DEFAULT_BINS = 1200
#: Largest heatmap grid sent to the browser (columns, rows); spectrograms have at most
#: 400 time slices and 2000 frequency bins, merged by maximum beyond this size.
HEATMAP_MAX = (400, 800)
#: Quantization of the heatmap levels (65535 marks an empty cell).
LEVELS = 65534

LIGHT = {"series": SERIES, "surface": SURFACE, "ink": INK, "ink2": INK2, "muted": MUTED,
         "grid": GRID, "axis": AXIS, "wash": NEUTRAL_WASH, "removed": REMOVED}


def palette() -> dict[str, Any]:
    """Color tokens of the charts for both themes; the chart uses the one of the page."""
    return {"light": dict(LIGHT), "dark": dict(DARK)}


def _json_list(values: np.ndarray) -> list[float | None]:
    return [None if not math.isfinite(v) else float(v) for v in np.asarray(values, float)]


def align(curves: list[tuple[np.ndarray, np.ndarray]]) -> dict[str, Any]:
    """Union of the abscissas and the ordinates of every curve on it (``None`` elsewhere)."""
    xs = [np.asarray(x, float) for x, _ in curves]
    if not xs:
        return {"x": [], "series": []}
    union = np.unique(np.concatenate(xs)) if len(xs) > 1 else xs[0]
    series = []
    for x, y in curves:
        values = np.full(union.size, np.nan)
        if x.size:
            values[np.searchsorted(union, x)] = np.asarray(y, float)
        series.append(_json_list(values))
    return {"x": _json_list(union), "series": series}


def _transform_x(x: np.ndarray, y: np.ndarray, axis: Axis) -> tuple[np.ndarray, np.ndarray]:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if axis.offset or axis.factor != 1.0:
        x = (x - axis.offset) * axis.factor
    if axis.reciprocal:
        keep = x > 0
        x, y = 1.0 / x[keep], y[keep]
        order = np.argsort(x)
        x, y = x[order], y[order]
    elif x.size > 1 and np.any(np.diff(x) < 0):
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
    return x, y


def _curve(source: Result | Sequence[Result], key: str) -> Any:
    """Curve of a result, or ``"<index>/<curve>"`` of a comparison of results."""
    if isinstance(source, Result):
        return source.curves[key]
    return comparison_curve(source, key)


def _regrid(values: np.ndarray, centers: np.ndarray, edges: np.ndarray, log: bool
            ) -> np.ndarray:
    """Values of the cells ``edges`` along the first axis of ``values``.

    Several source cells in one target cell are merged by their maximum, so that a narrow
    spectral line stays visible; a target cell without a source cell takes the nearest one
    (logarithmic axes stretch the low frequencies).
    """
    n = edges.size - 1
    target = np.clip(np.searchsorted(edges, centers, side="right") - 1, 0, n - 1)
    out = np.full((n, *values.shape[1:]), np.nan)
    np.fmax.at(out, target, values)
    empty = np.flatnonzero(np.all(np.isnan(out.reshape(n, -1)), axis=1))
    if empty.size and centers.size:
        mid = np.sqrt(edges[:-1] * edges[1:]) if log else (edges[:-1] + edges[1:]) / 2
        right = np.clip(np.searchsorted(centers, mid[empty]), 0, centers.size - 1)
        left = np.clip(right - 1, 0, centers.size - 1)
        if log:
            closer = np.abs(np.log(mid[empty] / centers[left])) <= np.abs(
                np.log(centers[right] / mid[empty]))
        else:
            closer = np.abs(mid[empty] - centers[left]) <= np.abs(centers[right] - mid[empty])
        out[empty] = values[np.where(closer, left, right)]
    return out


def heatmap_payload(result: Result, panel: Panel) -> dict[str, Any]:
    """Grid of a heatmap panel, quantized to 16 bits (spectrogram, §5.4).

    ``values`` is the base64 text of ``rows × cols`` little-endian unsigned 16-bit integers,
    row 0 being the lowest ordinate: ``level = zmin + q / 65534 · (zmax − zmin)``, 65535 for an
    empty cell. The browser colors the cells and reads the level under the cursor.
    """
    heatmap = panel.heatmap
    assert heatmap is not None
    image = result.extra[heatmap.key]
    t = (np.asarray(image["t"], float) - panel.x.offset) * panel.x.factor
    f = np.asarray(image["f"], float)
    z = np.asarray(image["z"], float)
    log = panel.y.scale == "log"
    if log:
        keep = f > 0
        f, z = f[keep], z[keep]
    x0 = float(heatmap.x0 if heatmap.x0 is not None else t[0])
    x1 = float(heatmap.x1 if heatmap.x1 is not None else t[-1])
    y0 = float(heatmap.y0 if heatmap.y0 is not None else f[0])
    y1 = float(heatmap.y1 if heatmap.y1 is not None else f[-1])
    cols = max(1, min(t.size, HEATMAP_MAX[0]))
    rows = max(1, min(f.size, HEATMAP_MAX[1]))
    if log and f.size > 1 and y0 > 0:
        # Rows of equal width in log10(f): enough of them for the top row to be no wider
        # than a frequency bin, within the size limit.
        step = float(np.median(np.diff(f)))
        need = math.ceil(math.log(y1 / y0) / math.log1p(step / y1))
        rows = int(min(max(need, f.size), HEATMAP_MAX[1]))
    grid = _regrid(z.T, t, np.linspace(x0, x1, cols + 1), False).T if z.size else z
    if log:
        edges = np.geomspace(y0, y1, rows + 1)
    else:
        edges = np.linspace(y0, y1, rows + 1)
    grid = _regrid(grid, f, edges, log) if z.size else np.full((rows, cols), np.nan)
    finite = grid[np.isfinite(grid)]
    zmin = float(finite.min()) if finite.size else 0.0
    zmax = float(finite.max()) if finite.size else 1.0
    span = zmax - zmin if zmax > zmin else 1.0
    q = np.full(grid.shape, LEVELS + 1, dtype="<u2")
    ok = np.isfinite(grid)
    q[ok] = np.round((grid[ok] - zmin) / span * LEVELS).astype("<u2")
    return {"cols": int(grid.shape[1]), "rows": int(grid.shape[0]), "log": log,
            "x0": x0, "x1": x1, "y0": y0, "y1": y1, "zmin": zmin, "zmax": zmax,
            "vmin": heatmap.vmin if heatmap.vmin is not None else zmin,
            "vmax": heatmap.vmax if heatmap.vmax is not None else zmax,
            "label": heatmap.label, "colors": list(SEQUENTIAL_STOPS),
            "values": base64.b64encode(q.tobytes()).decode("ascii")}


def panel_data(result: Result | Sequence[Result], panel: Panel, bins: int = DEFAULT_BINS
               ) -> dict[str, Any]:
    """Aligned, decimated data of one panel of a result figure (or of a comparison)."""
    if panel.heatmap is not None:
        source = result if isinstance(result, Result) else result[0]
        heat = heatmap_payload(source, panel)
        data = align([decimate_xy(*_transform_x(_curve(result, s.curve).x,
                                                _curve(result, s.curve).y, panel.x),
                                  bins, panel.x.scale) for s in panel.series])
        data["heatmap"] = heat
        return data
    curves = []
    for s in panel.series:
        c = _curve(result, s.curve)
        x, y = _transform_x(c.x, c.y, panel.x)
        curves.append(decimate_xy(x, y, bins, panel.x.scale))
    return align(curves)


def figure_payload(result: Result | Sequence[Result], spec: FigureSpec,
                   bins: int = DEFAULT_BINS) -> dict[str, Any]:
    """Figure description and data of every panel, ready for the chart component.

    ``result`` is a list of results for a comparison figure
    (:func:`onthesignal.plot.layouts.comparison_spec`).
    """
    return {"figure": spec.to_dict(),
            "data": {p.id: panel_data(result, p, bins) for p in spec.panels}}


# ---------------------------------------------------------------------------------- signals
def _unit(signal: Signal, units: str) -> str:
    if units == "counts" or signal.unit == COUNTS:
        return "counts"
    return pretty_unit(signal.unit)


def time_origin(signals: list[Signal]) -> UTCDateTime:
    return min(s.starttime for s in signals)


#: Fraction of half the full scale from which its levels are drawn on a time plot.
NEAR_FULL_SCALE = 0.5


def full_scale_lines(sig: Signal, units: str) -> list[HLine]:
    """Levels ±full scale/2 when the signal comes near them (web specification §5.2)."""
    half = float(sig.full_scale or 2.0**24) / 2.0
    factor = 1.0 if _unit(sig, units) == "counts" else abs(sig.sensitivity)
    peak = float(np.max(np.abs(sig.data))) if sig.npts else 0.0
    if peak < NEAR_FULL_SCALE * half:
        return []
    return [HLine(sign * half * factor, "± full scale / 2" if sign > 0 else "", "removed",
                  [6, 4], extend=True) for sign in (1, -1)]


def signal_figure(signals: list[Signal], units: str = "physical", stacked: bool = True,
                  title: str = "", colors: Mapping[str, str] | None = None) -> FigureSpec:
    """Time plot of one or several signals (§5.2): stacked panels or one overlay panel.

    ``colors`` maps signal names to color tokens (the color follows the signal, §7.6);
    by default the signals take the categorical slots in order.
    """
    origin = time_origin(signals)
    colors = colors or {}
    note = ""
    iso = origin.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def axis_x() -> Axis:
        return Axis("Time", "s", time_origin=iso)

    def gaps(sig: Signal) -> list[Band]:
        out = []
        for g in sig.gaps:
            if g.get("type") == "gap":
                out.append(Band(float(UTCDateTime(g["start"]) - origin),
                                float(UTCDateTime(g["end"]) - origin), "gap", "gap"))
        return out

    names = [s.name or s.id for s in signals]

    def color(i: int, name: str) -> str:
        return colors.get(name, f"series:{i % 8}")

    if stacked or len(signals) == 1:
        panels = [Panel(name, axis_x(), Axis(s.label if len(signals) > 1 else "Amplitude",
                                              _unit(s, units)),
                        [Series(name, s.label, width=0.8, color=color(i, name))],
                        bands=gaps(s), sync="t", legend=len(signals) > 1,
                        hlines=full_scale_lines(s, units))
                  for i, (name, s) in enumerate(zip(names, signals, strict=True))]
    else:
        shown = [_unit(s, units) for s in signals]
        mixed = len(set(shown)) > 1
        unit = "" if mixed else shown[0]
        levels: dict[float, HLine] = {}
        for s in signals:  # one pair of lines per full scale reached
            for line in full_scale_lines(s, units):
                levels.setdefault(round(line.y, 12), line)
        panels = [Panel("overlay", axis_x(), Axis("Amplitude", unit),
                        [Series(n, f"{s.label} ({u})" if mixed else s.label, width=0.8,
                                color=color(i, n))
                         for i, (n, s, u) in enumerate(zip(names, signals, shown, strict=True))],
                        bands=[b for s in signals for b in gaps(s)], sync="t",
                        hlines=[] if mixed else list(levels.values()))]
        if mixed:
            note = (f"The overlaid signals have different units ({', '.join(sorted(set(shown)))})"
                    ": compare them in counts, or stack them.")
    if not title:
        title = signals[0].label if len(signals) == 1 else " · ".join(names)
    return FigureSpec(title, panels, results=ResultsSpec(), note=note)


def _window_indices(sig: Signal, origin: UTCDateTime, t0: float | None, t1: float | None
                    ) -> tuple[int, int]:
    """Sample range of the window ``[t0, t1]`` (seconds from ``origin``)."""
    offset = float(sig.starttime - origin)
    n = sig.npts
    i0 = 0 if t0 is None else int(math.floor((t0 - offset) * sig.sampling_rate))
    i1 = n if t1 is None else int(math.ceil((t1 - offset) * sig.sampling_rate)) + 1
    return max(0, min(n, i0)), max(0, min(n, i1))


def signal_values(sig: Signal, units: str) -> np.ndarray:
    return sig.to_physical() if _unit(sig, units) != "counts" else np.asarray(sig.data, float)


def signal_series(sig: Signal, origin: UTCDateTime, units: str, t0: float | None = None,
                  t1: float | None = None, bins: int = DEFAULT_BINS, margin: float = 0.0
                  ) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """Envelope of a signal on a window, with the statistics of that window.

    ``margin`` extends the data sent on each side of the window by that fraction of its width,
    at the same resolution, so that the plot can be moved without waiting for the server; the
    statistics remain those of the window ``[t0, t1]``.
    """
    i0, i1 = _window_indices(sig, origin, t0, t1)
    every = signal_values(sig, units)
    values = every[i0:i1]
    j0, j1 = i0, i1
    if margin > 0 and t0 is not None and t1 is not None and t1 > t0:
        extra = margin * (t1 - t0)
        j0, j1 = _window_indices(sig, origin, t0 - extra, t1 + extra)
    shown = every[j0:j1]
    n_bins = bins if (j0, j1) == (i0, i1) else \
        int(math.ceil(bins * (j1 - j0) / max(i1 - i0, 1)))
    idx = envelope_indices(shown.size, shown, n_bins)
    times = float(sig.starttime - origin) + (j0 + idx) / sig.sampling_rate
    stats = window_stats(values)
    stats["start"] = float(sig.starttime - origin) + i0 / sig.sampling_rate
    stats["end"] = float(sig.starttime - origin) + max(i1 - 1, i0) / sig.sampling_rate
    return times, shown[idx], stats


def signal_payload(signals: list[Signal], spec: FigureSpec, units: str = "physical",
                   t0: float | None = None, t1: float | None = None,
                   bins: int = DEFAULT_BINS, margin: float = 0.0
                   ) -> tuple[dict[str, Any], dict[str, dict]]:
    """Panel data of a time plot and the statistics of the window, per signal.

    ``margin``: data also sent on each side of the window (fraction of its width), see
    :func:`signal_series`.
    """
    origin = time_origin(signals)
    by_name = {s.name or s.id: s for s in signals}
    data, stats = {}, {}
    for panel in spec.panels:
        curves = []
        for series in panel.series:
            t, v, st = signal_series(by_name[series.curve], origin, units, t0, t1, bins, margin)
            curves.append((t, v))
            stats[series.curve] = st
        data[panel.id] = align(curves)
    return data, stats


def arrays_figure(title: str, x: np.ndarray | None, ys: Sequence[np.ndarray],
                  labels: Sequence[str] | None = None, x_label: str = "x",
                  y_label: str = "y", bins: int = DEFAULT_BINS
                  ) -> tuple[FigureSpec, dict[str, Any]]:
    """Chart of numpy arrays of the terminal: ``plot(y)``, ``plot(x, y1, y2…)`` (§10.3)."""
    curves = [np.asarray(y, float).ravel() for y in ys]
    if not curves:
        from ..core.errors import ParameterError

        raise ParameterError("plot() needs at least one array")
    xs = np.arange(curves[0].size, dtype=float) if x is None else np.asarray(x, float).ravel()
    for y in curves:
        if y.size != xs.size:
            from ..core.errors import ParameterError

            raise ParameterError(f"plot(): x has {xs.size} values, y has {y.size}")
    names = list(labels or [])
    names += [f"y{i + 1}" if len(curves) > 1 else y_label for i in range(len(names), len(curves))]
    order = np.argsort(xs, kind="stable")
    xs = xs[order]
    spec = FigureSpec(title or "plot", [Panel("plot", Axis(x_label), Axis(y_label if len(
        curves) == 1 else ""), [Series(f"y{i}", names[i], width=1.2, color=f"series:{i % 8}")
                                for i in range(len(curves))], legend=len(curves) > 1)])
    data = align([decimate_xy(xs, y[order], bins) for y in curves])
    return spec, {"plot": data}


def array_figure(name: str, values: np.ndarray) -> tuple[FigureSpec, dict[str, Any]]:
    """Plot of a one-dimensional numpy array of the terminal (``Variables`` group)."""
    y = np.asarray(values, float).ravel()
    idx = envelope_indices(y.size, y, DEFAULT_BINS)
    spec = FigureSpec(name, [Panel("array", Axis("Index"), Axis(name),
                                   [Series("array", name, width=0.8)], legend=False)])
    return spec, {"array": align([(idx.astype(float), y[idx])])}


__all__ = ["align", "array_figure", "arrays_figure", "figure_payload", "full_scale_lines",
           "heatmap_payload", "palette", "panel_data", "signal_figure", "signal_payload",
           "signal_series"]
