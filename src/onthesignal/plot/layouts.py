"""Figure layouts of every analysis for the web interface (web specification R11, §7.4, §7.5).

Each function turns a :class:`~onthesignal.core.result.Result` into one or several
:class:`~onthesignal.plot.spec.FigureSpec`: what the matplotlib figure of :mod:`onthesignal.plot`
shows (same curves, markers, study band, removed mains lines, calculation conditions), and
the results displayed under the figure. Nothing is computed here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

import numpy as np

from ..core.errors import ParameterError
from .sine import _conditions
from .spec import Axis, Band, FigureSpec, Heatmap, HLine, Marker, Panel, ResultsSpec, Series

Layout = Callable[[Any], "FigureSpec | list[tuple[str, FigureSpec]]"]
_LAYOUTS: dict[str, Layout] = {}


def layout(*kinds: str) -> Callable[[Layout], Layout]:
    """Register the layout of result kinds."""

    def decorator(func: Layout) -> Layout:
        for kind in kinds:
            _LAYOUTS[kind] = func
        return func

    return decorator


def has_layout(kind: str) -> bool:
    return kind in _LAYOUTS


def figure_specs(result: Any) -> list[tuple[str, FigureSpec]]:
    """Figures of a result with their tab titles (several for ``dynamic``)."""
    func = _LAYOUTS.get(result.kind)
    out = func(result) if func is not None else generic(result)
    if isinstance(out, FigureSpec):
        return [("Figure", out)]
    return out


def figure_spec(result: Any) -> FigureSpec:
    """Main figure of a result."""
    return figure_specs(result)[0][1]


# ---------------------------------------------------------------------------------- helpers
def _axis(curve: Any, which: str, **kw: Any) -> Axis:
    if which == "x":
        return Axis(curve.x_label, curve.x_unit, curve.xscale, **kw)
    return Axis(curve.y_label, curve.y_unit, curve.yscale, **kw)


def _study_band(result: Any, x_min: float | None = None) -> list[Band]:
    band = result.extra.get("band")
    if not band:
        return []
    low = max(float(band[0]), x_min) if x_min is not None else float(band[0])
    return [Band(low, float(band[1]), "study band", ref="band")]


def _mains(result: Any, verb: str = "removed") -> list[Marker]:
    lines = result.extra.get("mains_lines") or []
    mains = result.params.get("mains_freq", 50.0)
    return [Marker(float(f), label=f"{mains:g} Hz and harmonics ({verb})" if i == 0 else "",
                   kind="removed_mains", ref="mains") for i, f in enumerate(lines)]


def result_curve(result: Any, key: str) -> Any:
    """Curve ``key`` of a result: one of ``Result.curves``, or a trace of ``Result.extra``.

    A trace is a curve sampled at a constant step and kept out of the serialized result
    (the band-limited noise of ``noise``): ``{"y", "dt", "label", "unit"}``.
    """
    curve = result.curves.get(key)
    if curve is not None:
        return curve
    trace = result.extra.get(key)
    if not isinstance(trace, dict) or "y" not in trace or "dt" not in trace:
        raise KeyError(key)
    from ..core.result import Curve

    y = np.asarray(trace["y"])
    return Curve(float(trace.get("t0", 0.0)) + np.arange(y.size) * float(trace["dt"]), y,
                 label=str(trace.get("label", key)), x_label="Time", x_unit="s",
                 y_label=str(trace.get("label", "")), y_unit=str(trace.get("unit", "")))


#: Rows of the study band linked to the shaded band and to the removed mains lines.
BAND_LINKS = {"band": "band", "enbw": "band", "mains_removed": "mains"}


def _first_positive(x: np.ndarray) -> float:
    positive = np.asarray(x)[np.asarray(x) > 0]
    return float(positive[0]) if positive.size else 1e-3


# ---------------------------------------------------------------------------------- noise
NOISE_HEADLINE = ["rms", "pp", "dr", "enob"]
NOISE_GROUPS: list[tuple[str, list[str]]] = [
    ("Noise", ["mean", "rms", "pp", "pp_gauss", "dr", "enob", "full_scale"]),
    ("Study band", ["band", "enbw", "mains_removed"]),
    ("Record", ["duration", "npts"]),
]


NOISE_LINKS = {**BAND_LINKS, "rms": "rms", "pp": "pp"}


@layout("noise")
def noise_layout(result: Any) -> FigureSpec:
    """Band-limited noise with its ±RMS levels and its extremes, above the results (§7.4)."""
    from ..core.units import COUNTS, pretty_unit

    panels = []
    trace = result.extra.get("trace")
    if trace is not None and len(trace.get("y", ())):
        unit = str(trace.get("unit", COUNTS))
        physical = unit != COUNTS
        rms = result.values.get("rms_phys" if physical else "rms")
        hlines = [] if rms is None else [
            HLine(sign * float(rms.value), "± RMS" if sign > 0 else "", "ink2", [6, 4],
                  ref="rms") for sign in (1, -1)]
        y = np.asarray(trace["y"])
        dt = float(trace["dt"])
        markers = [Marker(float(i) * dt, float(y[i]), label, "extreme", ref="pp")
                   for label, i in (("maximum", int(np.argmax(y))),
                                    ("minimum", int(np.argmin(y))))]
        panels.append(Panel("trace", Axis("Time", "s", time_origin=str(trace.get("origin", ""))),
                            Axis("Noise", unit if not physical else pretty_unit(unit)),
                            [Series("trace", str(trace.get("label", "noise")), width=0.8)],
                            hlines=hlines, markers=markers, legend=False))
    return FigureSpec(result.title, panels,
                      results=ResultsSpec(NOISE_HEADLINE, NOISE_GROUPS, links=NOISE_LINKS))


def _spectral_panel(result: Any, key: str, label: str) -> Panel:
    c = result.curves[key]
    return Panel(key, _axis(c, "x"), _axis(c, "y"),
                 [Series(key, label, width=0.8 if key == "spectrum" else 1.5)],
                 bands=_study_band(result), markers=_mains(result))


@layout("noise_fft")
def noise_fft_layout(result: Any) -> FigureSpec:
    return FigureSpec(result.title, [_spectral_panel(result, "spectrum", "spectrum")],
                      results=ResultsSpec(NOISE_HEADLINE,
                                          [*NOISE_GROUPS, ("Spectrum", ["window", "df"])],
                                          links=BAND_LINKS))


@layout("noise_dsp")
def noise_dsp_layout(result: Any) -> FigureSpec:
    panels = [_spectral_panel(result, "psd", "PSD")]
    cumulative = result.curves.get("cumulative_rms")
    if cumulative is not None:
        panels[0].height, panels[0].sync = 2.0, "f"
        panels.append(Panel("cumulative_rms", _axis(cumulative, "x"), _axis(cumulative, "y"),
                            [Series("cumulative_rms", "cumulative RMS")],
                            bands=_study_band(result), sync="f"))
    groups = [("Noise", ["mean", "rms", "rms_psd", "pp", "pp_gauss", "dr", "enob",
                         "full_scale"]),
              *NOISE_GROUPS[1:], ("Welch", ["nperseg", "n_averages", "df"])]
    return FigureSpec(result.title, panels,
                      results=ResultsSpec(["rms", "rms_psd", "dr", "enob"], groups,
                                          links=BAND_LINKS))


@layout("lnm")
def lnm_layout(result: Any) -> FigureSpec:
    period = result.extra.get("x", "freq") == "period"
    psd = result.curves["psd"]
    # Abscissa limited to the PSD, as in the matplotlib figure (the model spans 1e-5–10 Hz).
    f = np.asarray(psd.x, float)
    f = f[f > 0]
    lo, hi = (float(f[0]), float(f[-1])) if f.size else (None, None)
    if period:
        x = Axis("Period", "s", "log", 1 / hi if hi else None, 1 / lo if lo else None,
                 reciprocal=True)
    else:
        x = Axis("Frequency", "Hz", "log", lo, hi)
    series = [
        Series("psd", "PSD (raw)", width=0.6, alpha=0.35),
        Series("psd_smooth", result.curves["psd_smooth"].label, role="smoothed"),
        Series("nlnm", "NLNM", role="model", color="ink2", width=1.2),
    ]
    if "nhnm" in result.curves:
        series.append(Series("nhnm", "NHNM", role="model", color="muted", width=1.2,
                             dash=[6, 4]))
    top = Panel("psd", x, Axis("PSD", psd.y_unit), series, height=2.0, sync="f")
    where = "period_max" if period else "freq_max"
    markers = []
    if where in result.values and "diff_max" in result.values:
        markers.append(Marker(float(result.values[where].value),
                              float(result.values["diff_max"].value), "maximum PSD − NLNM",
                              "maximum", ref="diff_max"))
    bottom = Panel("diff", Axis(x.label, x.unit, "log", x.min, x.max, reciprocal=period),
                   Axis("PSD − NLNM", "dB"),
                   [Series("diff", "PSD − NLNM", fill_negative=True, fill_label="below NLNM")],
                   hlines=[HLine(0.0)], markers=markers, sync="f")
    return FigureSpec(result.title, [top, bottom], results=ResultsSpec(
        ["diff_max", where, "below_nlnm"],
        [("PSD − NLNM", ["quantity", "diff_min", "diff_max", "diff_mean", "freq_max",
                         "period_max", "below_nlnm", "range"]),
         ("Welch", ["nperseg", "n_averages"])],
        links={"diff_max": "diff_max", "freq_max": "diff_max", "period_max": "diff_max"}))


# ---------------------------------------------------------------------------------- sine
FIT = ["frequency", "amplitude", "amplitude_dbfs", "offset", "periods", "full_scale"]


def _time_panel(result: Any) -> Panel:
    return Panel("time", Axis("Time", "s"), Axis("Amplitude", "counts"),
                 [Series("signal", "samples", role="samples", points=True),
                  Series("fit", result.curves["fit"].label or "fit", role="fit",
                         color="series:1")], sync="t")


def _residual_panel(result: Any) -> Panel:
    return Panel("residual", Axis("Time", "s"), Axis("Residual", "counts"),
                 [Series("residual", "residual", width=0.8)], sync="t")


def _spectrum_panel(result: Any, key: str, kind: str) -> Panel:
    c = result.curves[key]
    band = result.extra.get("band")
    x_last = float(np.asarray(c.x)[-1])
    x_max = float(band[1]) * 1.1 if band and band[1] < x_last else x_last
    if c.xscale == "log":
        x_min = float(band[0]) / 1.2 if band and band[0] > 0 else _first_positive(c.x)
    else:
        x_min = 0.0
    markers = [] if kind == "thd" else _mains(result, "excluded" if kind == "sfdr" else "removed")
    return Panel(key, Axis("Frequency", "Hz", c.xscale, x_min, x_max), Axis("Amplitude", "dBFS"),
                 [Series(key, c.label or "spectrum", width=0.8)],
                 bands=_study_band(result, x_min), markers=markers,
                 conditions=_conditions(result, kind).split("\n"), height=1.4)


def _fundamental_and_spur(result: Any) -> list[Marker]:
    out = []
    if "fundamental" in result.extra:
        f0, level = result.extra["fundamental"]
        out.append(Marker(float(f0), float(level), "fundamental", "fundamental",
                          ref="fundamental"))
    if "spur" in result.extra:
        fs_, level = result.extra["spur"]
        out.append(Marker(float(fs_), float(level), "largest spur", "spur", ref="spur"))
    return out


def _harmonic_markers(result: Any) -> list[Marker]:
    harmonics = result.extra.get("harmonics") or []
    if not harmonics or "frequency" not in result.values:
        return []
    f0 = float(result.values["frequency"].value)
    level0 = float(result.values["amplitude_dbfs"].value)
    spectrum = result.curves.get("spectrum")
    floor = float(np.median(spectrum.y)) if spectrum is not None else -np.inf
    out = []
    for fk, dbc in harmonics:
        level = level0 + float(dbc)
        order = round(float(fk) / f0)
        out.append(Marker(float(fk), level, f"H{order}" if level > floor + 20 else "",
                          "harmonic", ref=f"H{order}"))
    return out


def _fundamental_point(result: Any) -> list[Marker]:
    if "frequency" not in result.values or "amplitude_dbfs" not in result.values:
        return []
    return [Marker(float(result.values["frequency"].value),
                   float(result.values["amplitude_dbfs"].value), "fundamental", "fundamental",
                   ref="fundamental")]


#: Fit rows linked to the fundamental, spur rows to the largest spur (hover highlight).
FIT_LINKS = {"frequency": "fundamental", "amplitude": "fundamental",
             "amplitude_dbfs": "fundamental"}
SPUR_LINKS = {k: "spur" for k in ("spur_frequency", "spur_amplitude", "spur_nature",
                                  "spur_emergence", "noise_limited", "sfdr_dbc", "sfdr_dbfs")}
HARMONIC_ROWS = {"harmonics": "H{order}"}

SINAD_RESULTS = ResultsSpec(["sinad", "enob", "enob_fs"], [
    ("Fit", FIT),
    ("Noise and distortion", ["sigma_r", "sinad", "enob", "enob_fs", "thd_n"]),
    ("Study band", ["band", "enbw", "mains_removed"]),
], links=BAND_LINKS)
SFDR_RESULTS = ResultsSpec(["sfdr_dbc", "sfdr_dbfs", "spur_frequency", "spur_nature"], [
    ("Fit", FIT),
    ("Largest spur", ["spur_frequency", "spur_amplitude", "spur_nature", "spur_emergence",
                      "noise_limited"]),
    ("SFDR", ["sfdr_dbc", "sfdr_dbfs"]),
], links={**FIT_LINKS, **SPUR_LINKS, **BAND_LINKS})
THD_RESULTS = ResultsSpec(["thd_db", "thd_pct"], [
    ("Fit", FIT),
    ("Distortion", ["thd_db", "thd_pct", "n_harmonics_used"]),
], ["harmonics"], links=FIT_LINKS, row_refs=HARMONIC_ROWS)


@layout("sinefit")
def sinefit_layout(result: Any) -> FigureSpec:
    return FigureSpec(result.title, [_time_panel(result)], results=ResultsSpec(
        ["frequency", "amplitude", "rms_residual"],
        [("Fit", ["frequency", "amplitude", "phase", "offset", "rms_residual"]),
         ("Convergence", ["periods", "iterations", "converged"])]))


@layout("sinad")
def sinad_layout(result: Any) -> FigureSpec:
    return FigureSpec(result.title, [_time_panel(result), _residual_panel(result),
                                     _spectrum_panel(result, "residual_spectrum", "sinad")],
                      results=SINAD_RESULTS)


@layout("sfdr")
def sfdr_layout(result: Any) -> FigureSpec:
    panel = _spectrum_panel(result, "spectrum", "sfdr")
    panel.markers += _fundamental_and_spur(result)
    return FigureSpec(result.title, [panel], results=SFDR_RESULTS)


@layout("thd")
def thd_layout(result: Any) -> FigureSpec:
    panel = _spectrum_panel(result, "spectrum", "thd")
    panel.markers += _fundamental_point(result) + _harmonic_markers(result)
    return FigureSpec(result.title, [panel], results=THD_RESULTS)


@layout("dynamic")
def dynamic_layout(result: Any) -> list[tuple[str, FigureSpec]]:
    summary = ResultsSpec(["sinad", "enob_fs", "snr", "thd_db", "sfdr_dbc", "dr"], [
        ("Fit", FIT),
        ("Noise and distortion", ["sigma_r", "sinad", "enob", "enob_fs", "thd_n",
                                  "sigma_noise", "snr", "dr"]),
        ("Harmonic distortion", ["thd_db", "thd_pct", "n_harmonics_used"]),
        ("Spurs", ["sfdr_dbc", "sfdr_dbfs", "spur_frequency", "spur_nature", "spur_emergence",
                   "noise_limited"]),
        ("Consistency", ["sinad_check"]),
        ("Study band", ["band", "enbw", "mains_removed"]),
    ], ["harmonics"], links=BAND_LINKS, row_refs=HARMONIC_ROWS)
    sfdr = _spectrum_panel(result, "spectrum", "sfdr")
    sfdr.markers += _fundamental_and_spur(result)
    thd = _spectrum_panel(result, "spectrum", "thd")
    thd.markers += _fundamental_point(result) + _harmonic_markers(result)
    return [
        ("Summary", FigureSpec(result.title, [_time_panel(result), _residual_panel(result)],
                               results=summary)),
        ("SINAD", FigureSpec(result.title,
                             [_spectrum_panel(result, "residual_spectrum", "sinad")],
                             results=SINAD_RESULTS)),
        ("SFDR", FigureSpec(result.title, [sfdr], results=SFDR_RESULTS)),
        ("THD", FigureSpec(result.title, [thd], results=THD_RESULTS)),
    ]


# ---------------------------------------------------------------------------------- measures
def _per_period_panel(result: Any, curve: str, key: str, label: str) -> list[Panel]:
    """Value of each period with the mean as a level (``frequency``, ``period``, §7.4)."""
    c = result.curves.get(curve)
    if c is None:
        return []
    hlines = [HLine(float(result.values[key].value), label, "ink2", [6, 4], ref=key)] \
        if key in result.values else []
    return [Panel(curve, _axis(c, "x"), _axis(c, "y"),
                  [Series(curve, c.label or curve, width=0.8)], hlines=hlines, legend=False)]


@layout("frequency")
def frequency_layout(result: Any) -> FigureSpec:
    method = result.extra.get("method")
    return FigureSpec(result.title, _per_period_panel(result, "frequencies", "frequency",
                                                      "mean frequency"),
                      note=f"Method: {method}" if method else "",
                      results=ResultsSpec(["frequency"], [
                          ("Frequency", ["frequency", "frequency_std", "n_periods"])],
                          ["periods"], links={"frequency": "frequency"}))


@layout("period")
def period_layout(result: Any) -> FigureSpec:
    return FigureSpec(result.title, _per_period_panel(result, "periods", "period", "mean period"),
                      results=ResultsSpec(["period"], [
                          ("Period", ["period", "period_std", "period_min", "period_max",
                                      "n_periods"])], ["periods"], links={"period": "period"}))


@layout("delay50")
def delay50_layout(result: Any) -> FigureSpec:
    c = result.curves["s1"]
    level = float(result.extra.get("level", 0.5))
    markers = [Marker(float(t), level, "", "event", f"series:{i}", ref="delay")
               for i, t in enumerate(result.extra.get("markers", []))]
    panel = Panel("edges", _axis(c, "x"), Axis("Normalized amplitude"),
                  [Series("s1", result.curves["s1"].label),
                   Series("s2", result.curves["s2"].label, color="series:1")],
                  markers=markers, hlines=[HLine(level, f"{level:g} level")])
    return FigureSpec(result.title, [panel], results=ResultsSpec(["delay"], [
        ("Delay", ["delay", "delay_std", "delay_min", "delay_max", "n_edges"])], ["edges"],
        links={"delay": "delay"}))


@layout("coherence")
def coherence_layout(result: Any) -> FigureSpec:
    c = result.curves["coherence"]
    hlines = []
    if "threshold" in result.extra:
        hlines.append(HLine(float(result.extra["threshold"]), "significance level", "ink2",
                            [6, 4]))
    panel = Panel("coherence", _axis(c, "x"), Axis("Coherence", "", "linear", 0.0, 1.02),
                  [Series("coherence", "coherence")], hlines=hlines)
    return FigureSpec(result.title, [panel], results=ResultsSpec(["mean_coherence"], [
        ("Coherence", ["mean_coherence", "band", "n_averages", "df"])]))


def _cell_edges(centers: np.ndarray, step: float | None = None) -> tuple[float, float]:
    """Outer edges of cells centred on regularly spaced ``centers``."""
    centers = np.asarray(centers, float)
    if centers.size > 1:
        step = float(np.median(np.diff(centers)))
    step = step or 1.0
    return float(centers[0]) - step / 2, float(centers[-1]) + step / 2


@layout("spectrogram")
def spectrogram_layout(result: Any) -> FigureSpec:
    """Color map of the short-time PSD under the optional time series (§5.4).

    Both panels use seconds from the start of the analysed window, so that the cursor reads
    the absolute UTC time; the time axis is shared.
    """
    from obspy import UTCDateTime

    image = result.extra["image"]
    t = np.asarray(image["t"], float)
    f = np.asarray(image["f"], float)
    start = result.signals[0].get("starttime") if result.signals else ""
    origin = UTCDateTime(start) if start else UTCDateTime(float(t[0]) * 86400.0)
    iso = origin.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    offset = float(origin.matplotlib_date)
    dt = result.values["dt"].value if "dt" in result.values else None
    df = result.values["df"].value if "df" in result.values else None
    x0, x1 = _cell_edges((t - offset) * 86400.0, dt)
    y0, y1 = _cell_edges(f, df)
    log = image.get("yscale") == "log"
    if log and f.size:
        y0 = y0 if y0 > 0 else float(f[0]) / 2
    # The cells of the image keep their true edges; the axis starts at 0 Hz (linear).
    axis_y0 = y0 if log else max(y0, 0.0)
    lo, hi = x0, x1
    signal = result.curves.get("signal")
    if signal is not None and len(signal.x):
        xs = (np.asarray(signal.x, float) - offset) * 86400.0
        lo, hi = min(lo, float(xs[0])), max(hi, float(xs[-1]))

    def time_axis() -> Axis:
        return Axis("Time", "s", min=lo, max=hi, time_origin=iso, offset=offset, factor=86400.0)

    panels = []
    if signal is not None:
        panels.append(Panel("signal", time_axis(), Axis("Amplitude", signal.y_unit),
                            [Series("signal", signal.label or "signal", width=0.8)],
                            legend=False, sync="t"))
    heatmap = Heatmap("image", image.get("unit", ""), float(image["vmin"]), float(image["vmax"]),
                      x0, x1, y0, y1)
    panels.append(Panel("spectrogram", time_axis(),
                        Axis("Frequency", "Hz", "log" if log else "linear", axis_y0, y1),
                        height=3.0 if signal is not None else 2.5, legend=False, sync="t",
                        heatmap=heatmap))
    return FigureSpec(result.title, panels, results=ResultsSpec([], [
        ("Spectrogram", ["window_duration", "df", "dt", "color_range"])]))


# ---------------------------------------------------------------------------------- generic
def generic(result: Any) -> FigureSpec:
    """Results without a dedicated layout (user scripts): one panel per ordinate quantity."""
    groups: dict[tuple[str, str], list[str]] = {}
    for key, c in result.curves.items():
        groups.setdefault((c.y_label, c.y_unit), []).append(key)
    panels = []
    for i, ((label, unit), keys) in enumerate(groups.items()):
        first = result.curves[keys[0]]
        panels.append(Panel(f"p{i}", _axis(first, "x"), Axis(label, unit, first.yscale),
                            [Series(k, result.curves[k].label or k, color=f"series:{j % 8}")
                             for j, k in enumerate(keys)]))
    return FigureSpec(result.title or result.kind, panels)


# ---------------------------------------------------------------------------------- comparison
#: Panels overlaid when results are compared (default: every panel of the main figure).
COMPARE_PANELS: dict[str, list[str]] = {"sinad": ["residual_spectrum"],
                                         "dynamic": ["residual_spectrum"], "noise": []}
#: Results whose figures cannot be overlaid.
NOT_COMPARABLE = {"spectrogram": "spectrograms cannot be overlaid: open them side by side"}


def _source(results: Sequence[Any], key: str) -> tuple[Any, str]:
    """Result and curve name of a comparison series key ``"<index>/<curve>"``."""
    index, _, curve = key.partition("/")
    return results[int(index)], curve


def comparison_curve(results: Sequence[Any], key: str) -> Any:
    result, curve = _source(results, key)
    return result_curve(result, curve)


def result_label(result: Any) -> str:
    """``R2 · S1`` (result and signal names)."""
    names = ", ".join(str(s.get("name") or s.get("id", "")) for s in result.signals)
    return f"{result.name} · {names}" if names else str(result.name or result.kind)


def _panels_of(result: Any) -> list[Panel]:
    panels: list[Panel] = []
    for _, spec in figure_specs(result):
        for panel in spec.panels:
            if panel.id not in {p.id for p in panels}:
                panels.append(panel)
    keep = COMPARE_PANELS.get(result.kind)
    return [p for p in panels if keep is None or p.id in keep]


def comparison_spec(results: Sequence[Any], colors: Sequence[str]) -> FigureSpec:
    """One figure overlaying results of the same kind (web specification §7.6).

    The curves of result ``i`` are referenced as ``"i/<curve>"`` (:func:`comparison_curve`),
    drawn with ``colors[i]``, the color of its signal, so that a signal keeps its color in
    every view. Models (NLNM) are drawn once; when a panel has a smoothed curve, only the
    smoothed curves are overlaid. Markers, bands and calculation conditions are kept when
    they are the same for every result.
    """
    results = list(results)
    if len(results) < 2:
        raise ParameterError("Choose at least two results to compare")
    kinds = {r.kind for r in results}
    if len(kinds) > 1:
        raise ParameterError(f"Only results of the same analysis can be compared, not "
                             f"{', '.join(sorted(kinds))}")
    kind = results[0].kind
    if kind in NOT_COMPARABLE:
        raise ParameterError(f"{kind}: {NOT_COMPARABLE[kind]}")
    per_result = [{p.id: p for p in _panels_of(r)} for r in results]
    first = _panels_of(results[0])
    panels = []
    for base in first:
        versions = [pr.get(base.id) for pr in per_result]
        units = {v.y.unit for v in versions if v is not None}
        if len(units) > 1:
            raise ParameterError(f"The results have different units ({', '.join(sorted(units))})"
                                 f": set the unit and sensitivity of the signals first")
        smoothed = any(s.role == "smoothed" for s in base.series)
        roles = ("smoothed",) if smoothed else ("data", "fit")
        series: list[Series] = []
        for i, (r, version) in enumerate(zip(results, versions, strict=True)):
            if version is None:
                continue
            kept = [s for s in version.series if s.role in roles and s.curve in r.curves]
            for s in kept:
                suffix = f" · {s.label}" if len(kept) > 1 else ""
                series.append(replace(s, curve=f"{i}/{s.curve}", label=result_label(r) + suffix,
                                      color=colors[i % len(colors)], alpha=1.0, points=False,
                                      fill_negative=False, fill_label=""))
        series += [replace(s, curve=f"0/{s.curve}") for s in base.series
                   if s.role in ("model", "reference")]

        def same(attr: str, versions: list[Panel | None] = versions) -> list:
            values = [getattr(v, attr) for v in versions if v is not None]
            return values[0] if all(v == values[0] for v in values) else []

        x = replace(base.x)
        mins = [v.x.min for v in versions if v is not None and v.x.min is not None]
        maxs = [v.x.max for v in versions if v is not None and v.x.max is not None]
        x.min, x.max = (min(mins) if mins else None), (max(maxs) if maxs else None)
        markers = [m for m in same("markers") if m.kind == "removed_mains"]
        panels.append(replace(base, x=x, y=replace(base.y), series=series, markers=markers,
                              bands=same("bands"), conditions=same("conditions"), legend=True))
    names = ", ".join(result_label(r) for r in results)
    title = f"Comparison of {len(results)} {kind} results — {names}"
    return FigureSpec(title, panels, results=figure_spec(results[0]).results)


def comparison_view(results: Sequence[Any], spec: ResultsSpec | None = None) -> dict[str, Any]:
    """Comparison table shown under the figure: one column per result (§7.6).

    Returns ``columns`` (result labels), ``groups`` (title and rows ``label, values``) and
    ``warnings``. The key figures come first; a row absent from every result is skipped.
    """
    results = list(results)
    spec = spec or figure_spec(results[0]).results

    def cell(r: Any, key: str) -> str:
        v = r.values.get(key)
        if v is None:
            return "—"
        phys = r.values.get(key + "_phys")
        return v.text() + (f" ({phys.text()})" if phys is not None else "")

    def label(key: str) -> str:
        return next(r.values[key].label for r in results if key in r.values)

    used: set[str] = set()
    groups = []
    for title, keys in [("Key figures", spec.headline), *spec.groups]:
        keys = [k for k in keys if k not in used and any(k in r.values for r in results)]
        used.update(keys)
        if keys:
            groups.append({"title": title, "rows": [
                {"key": k, "label": label(k), "values": [cell(r, k) for r in results]}
                for k in keys]})
    rest = []
    for r in results:
        for k in r.values:
            if k not in used and not (k.endswith("_phys") and k[:-5] in r.values):
                used.add(k)
                rest.append(k)
    if rest:
        groups.append({"title": "Other", "rows": [
            {"key": k, "label": label(k), "values": [cell(r, k) for r in results]}
            for k in rest]})
    warnings = [f"{r.name}: {w}" for r in results for w in r.warnings]
    return {"columns": [result_label(r) for r in results], "groups": groups,
            "warnings": warnings}


# ---------------------------------------------------------------------------------- results panel
def _cell(value: Any) -> str:
    from ..core.units import fmt_num

    if isinstance(value, (bool, np.bool_)):
        return "yes" if value else "no"
    if isinstance(value, (int, float, np.integer, np.floating)):
        return fmt_num(float(value))
    return str(value)


def _raw(value: Any) -> Any:
    """Cell value for sorting: numbers stay numbers (``None`` when not finite)."""
    if isinstance(value, (bool, np.bool_)):
        return "yes" if value else "no"
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return str(value)


def _row_ref(pattern: str, row: dict) -> str:
    try:
        return pattern.format(**row) if pattern else ""
    except (KeyError, IndexError, ValueError):
        return ""


def figure_refs(spec: FigureSpec) -> set[str]:
    """References of the elements of a figure that rows of its results can highlight."""
    refs: set[str] = set()
    for p in spec.panels:
        refs.update(m.ref for m in p.markers if m.ref)
        refs.update(b.ref for b in p.bands if b.ref)
        refs.update(h.ref for h in p.hlines if h.ref)
    return refs


def results_view(result: Any, spec: ResultsSpec | None = None) -> dict[str, Any]:
    """Content of the results panel shown under a figure (web specification §7.5).

    Returns ``headline`` (key figures), ``groups`` (detail rows ``label, value, physical``),
    ``tables`` and ``warnings``. Every value of the result appears once in the groups; the
    values that the layout does not place go to a last ``Other`` group. Rows carry the
    ``ref`` of the figure element they describe (``ResultsSpec.links``); tables give their
    cells as text (``rows``), as values for sorting (``values``) and the ``refs`` of the rows.
    """
    spec = spec or figure_spec(result).results

    def row(key: str) -> dict[str, str]:
        v = result.values[key]
        phys = result.values.get(key + "_phys")
        return {"key": key, "label": v.label, "value": v.text(),
                "physical": phys.text() if phys is not None else "",
                "ref": spec.links.get(key, "")}

    present = [k for k in result.values if not (k.endswith("_phys") and k[:-5] in result.values)]
    used: set[str] = set()
    groups = []
    for title, keys in spec.groups:
        rows = [row(k) for k in keys if k in result.values]
        used.update(r["key"] for r in rows)
        if rows:
            groups.append({"title": title, "rows": rows})
    rest = [row(k) for k in present if k not in used]
    if rest:
        groups.append({"title": "Other" if groups else "Values", "rows": rest})
    headline = [row(k) for k in spec.headline if k in result.values]
    names = spec.tables or list(result.tables)
    tables = []
    for name in names:
        rows = result.tables.get(name) or []
        if rows:
            columns = list(rows[0].keys())
            pattern = spec.row_refs.get(name, "")
            tables.append({"name": name.replace("_", " "), "key": name, "columns": columns,
                           "rows": [[_cell(r.get(c, "")) for c in columns] for r in rows],
                           "values": [[_raw(r.get(c, "")) for c in columns] for r in rows],
                           "refs": [_row_ref(pattern, r) for r in rows]})
    return {"headline": headline, "groups": groups, "tables": tables,
            "warnings": list(result.warnings)}


__all__ = ["comparison_curve", "comparison_spec", "comparison_view", "figure_refs",
           "figure_spec", "figure_specs", "generic", "has_layout", "layout", "result_curve",
           "result_label", "results_view"]
