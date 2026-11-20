"""Renderer-independent figure description (web specification, rule R11).

A :class:`FigureSpec` says *what* a figure shows — panels, axes, series, markers, shaded
bands, calculation conditions — and which results are displayed under it, without saying
*how* to draw it. The web interface renders it with µPlot; the curve data stay in the
:class:`~onthesignal.core.result.Result` and are sent separately, decimated.

Colors are given as palette tokens resolved by the renderer for the active theme:
``series:0`` … ``series:7`` (categorical slots of :mod:`onthesignal.plot.style`), ``ink``,
``ink2``, ``muted``, ``axis`` and ``removed`` (red of the removed mains lines).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.result import jsonable


@dataclass
class Axis:
    """Axis of a panel. ``reciprocal=True`` shows ``1/x`` (period axis of ``lnm``).

    The curves are drawn at ``(x - offset) * factor``: for instance matplotlib dates (days)
    become seconds from ``time_origin`` with ``offset`` the date of the origin and
    ``factor = 86400``. ``min`` and ``max`` are given after this transformation.
    """

    label: str = ""
    unit: str = ""
    scale: str = "linear"
    min: float | None = None
    max: float | None = None
    reciprocal: bool = False
    #: ISO UTC instant: the axis is in seconds from it (time series).
    time_origin: str = ""
    offset: float = 0.0
    factor: float = 1.0


@dataclass
class Series:
    """One curve of a panel, ``curve`` being a key of ``Result.curves``."""

    curve: str
    label: str = ""
    role: str = "data"  # data, smoothed, model, fit, samples, reference
    color: str = "series:0"
    width: float = 1.5
    dash: list[float] | None = None
    alpha: float = 1.0
    #: Markers only, no line (samples of a sine fit).
    points: bool = False
    #: Shade the area between the curve and zero where the curve is negative.
    fill_negative: bool = False
    fill_label: str = ""


@dataclass
class Marker:
    """Vertical line (``y`` is None) or point marker."""

    x: float
    y: float | None = None
    label: str = ""
    #: removed_mains, harmonic, spur, fundamental, event
    kind: str = "event"
    color: str = ""


@dataclass
class Band:
    """Shaded interval of the abscissa: study band, gap, selection."""

    x0: float
    x1: float
    label: str = ""
    kind: str = "band"


@dataclass
class HLine:
    y: float
    label: str = ""
    color: str = "axis"
    dash: list[float] | None = None


@dataclass
class Heatmap:
    """Color map drawn in the plotting area of a panel (spectrogram, web specification §5.4).

    ``Result.extra[key]`` holds the grid: ``t`` (abscissa of the columns, before the
    transformation of the panel's x axis), ``f`` (ordinate of the rows) and ``z`` (rows ×
    columns). ``x0``, ``x1``, ``y0``, ``y1`` are the outer edges of the image in axis units.
    Colors run along the sequential ramp of :mod:`onthesignal.plot.style` from ``vmin`` to
    ``vmax``; ``label`` is the unit of the color bar (``dB re 1 V²/Hz``).
    """

    key: str = "image"
    label: str = ""
    vmin: float | None = None
    vmax: float | None = None
    x0: float | None = None
    x1: float | None = None
    y0: float | None = None
    y1: float | None = None


@dataclass
class Panel:
    id: str
    x: Axis
    y: Axis
    series: list[Series] = field(default_factory=list)
    height: float = 1.0
    markers: list[Marker] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    hlines: list[HLine] = field(default_factory=list)
    #: Calculation conditions written above the panel.
    conditions: list[str] = field(default_factory=list)
    legend: bool = True
    #: Panels with the same non-empty key share their abscissa: zoom and cursor follow.
    sync: str = ""
    heatmap: Heatmap | None = None


@dataclass
class ResultsSpec:
    """Results panel shown under the figure (web specification §7.5).

    ``headline`` lists the key figures; ``groups`` the detail, as ``(title, keys)``;
    ``tables`` the keys of ``Result.tables`` to show. Values present in the result but
    listed nowhere are added to a last group, so that nothing is hidden.
    """

    headline: list[str] = field(default_factory=list)
    groups: list[tuple[str, list[str]]] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)


@dataclass
class FigureSpec:
    title: str
    panels: list[Panel] = field(default_factory=list)
    results: ResultsSpec = field(default_factory=ResultsSpec)
    #: Render the matplotlib figure as an image instead (no interactive layout yet).
    static: bool = False
    note: str = ""

    def curve_keys(self) -> list[str]:
        """Curves used by the figure."""
        keys: list[str] = []
        for panel in self.panels:
            for s in panel.series:
                if s.curve not in keys:
                    keys.append(s.curve)
        return keys

    def to_dict(self) -> dict[str, Any]:
        return jsonable(asdict(self))


__all__ = ["Axis", "Band", "FigureSpec", "HLine", "Heatmap", "Marker", "Panel", "ResultsSpec",
           "Series"]
