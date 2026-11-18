"""Sine-analysis figures: fit, residual, spectra with fundamental, harmonics and spur."""

from __future__ import annotations

from typing import Any

from ..core.units import fmt_num
from . import plotter
from .style import (
    INK2,
    LINE_W,
    MARKER,
    SERIES,
    SURFACE,
    THIN_W,
    axis_label,
    conditions_title,
    finish,
    frequency_axis,
    info_box,
    legend,
    mark_lines,
    shade_band,
    style_axes,
    value_line,
)


def _time(ax: Any, result: Any) -> None:
    s, f = result.curves["signal"], result.curves["fit"]
    ax.plot(s.x, s.y, ls="none", marker="o", ms=3, color=SERIES[0], label="samples")
    ax.plot(f.x, f.y, color=SERIES[1], lw=LINE_W, label=f.label)
    ax.set_xlabel(axis_label("Time", "s"))
    ax.set_ylabel(axis_label("Amplitude", "counts"))
    style_axes(ax)
    legend(ax, loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=2, borderaxespad=0.1)


def _residual(ax: Any, result: Any) -> None:
    c = result.curves["residual"]
    ax.plot(c.x, c.y, color=SERIES[0], lw=THIN_W)
    ax.set_xlabel(axis_label("Time", "s"))
    ax.set_ylabel(axis_label("Residual", "counts"))
    style_axes(ax)


def _conditions(result: Any) -> str:
    """``Conditions: residual band 0–100 Hz (ideal FFT mask), ENBW 98.5 Hz · 50 Hz and
    harmonics removed (50, 100 Hz, ±0.5 Hz)``."""
    p, kind = result.params, result.kind
    band = result.extra.get("band")
    parts = []
    if band:
        span = f"{fmt_num(band[0])}–{fmt_num(band[1])} Hz"
        if kind in ("sinad", "dynamic"):
            method = ("ideal FFT mask" if p.get("filter_method", "fft") == "fft"
                      else f"zero-phase Butterworth, order {p.get('filter_order')}")
            text = f"residual band {span} ({method})"
            if "enbw" in result.values:
                text += f", ENBW {result.values['enbw'].text()}"
        elif kind == "thd":
            text = f"harmonics H2–H{p.get('n_harmonics')} within {span}"
        else:
            text = f"spur search within {span}"
        parts.append(text)
    mains = f"{p.get('mains_freq', 50.0):g} Hz and harmonics"
    lines = result.extra.get("mains_lines") or []
    verb = _mains_verb(kind)
    if kind == "thd":
        if p.get("remove_mains"):
            parts.append(f"harmonics on the {p.get('mains_freq', 50.0):g} Hz lines excluded")
    elif p.get("remove_mains"):
        if lines:
            width = float(p.get("mains_width", 1.0)) / 2.0
            parts.append(f"{mains} {verb} ({', '.join(f'{f:g}' for f in lines)} Hz, "
                         f"±{width:g} Hz)")
        else:
            parts.append(f"{mains} {verb} (no line in the band)")
    else:
        parts.append(f"{mains} not {verb}")
    return "\n".join(("Conditions: " if i == 0 else "") + part for i, part in enumerate(parts))


def _mains_verb(kind: str) -> str:
    """The mains lines are removed from the SINAD residual, excluded from the spur search."""
    return "excluded from the spur search" if kind == "sfdr" else "removed"


def _box_loc(result: Any, key: str) -> str:
    """Results box corner: on a log frequency axis the low-frequency end is usually free."""
    return "upper left" if result.curves[key].xscale == "log" else "upper right"


def _spectrum(ax: Any, result: Any, key: str = "spectrum") -> None:
    c = result.curves[key]
    band = result.extra.get("band")
    x_max = band[1] * 1.1 if band and band[1] < c.x[-1] else c.x[-1]
    if c.xscale == "log":
        x_min = band[0] / 1.2 if band and band[0] > 0 else c.x[0]
    else:
        x_min = 0.0
    if band:
        shade_band(ax, [max(band[0], x_min), band[1]])
    ax.plot(c.x, c.y, color=SERIES[0], lw=THIN_W, label=c.label)
    if result.kind != "thd":
        verb = "excluded" if result.kind == "sfdr" else "removed"
        mark_lines(ax, result.extra.get("mains_lines") or [],
                   label=f"{result.params.get('mains_freq', 50.0):g} Hz and harmonics ({verb})")
    frequency_axis(ax, c.xscale, x_min, x_max)
    ax.set_xlabel(axis_label("Frequency", "Hz"))
    ax.set_ylabel(axis_label("Amplitude", "dBFS"))
    style_axes(ax)
    conditions_title(ax, _conditions(result))


def _marker(ax: Any, x: float, y: float, color: str, label: str | None, text: str = "") -> None:
    ax.plot([x], [y], ls="none", marker="o", ms=MARKER, color=color, mec=SURFACE, mew=1.5,
            label=label, zorder=4)
    if text:
        ax.annotate(text, (x, y), xytext=(4, 5), textcoords="offset points", fontsize=7.5,
                    color=INK2)


def _fundamental_and_spur(ax: Any, result: Any) -> None:
    if "fundamental" in result.extra:
        f0, l0 = result.extra["fundamental"]
        _marker(ax, f0, l0, SERIES[1], "fundamental")
    if "spur" in result.extra:
        fs_, ls_ = result.extra["spur"]
        _marker(ax, fs_, ls_, SERIES[2], "largest spur")


def _harmonics(ax: Any, result: Any) -> None:
    if not result.extra.get("harmonics"):
        return
    import numpy as np

    f0 = result.values["frequency"].value
    level0 = result.values["amplitude_dbfs"].value
    spectrum = result.curves.get("spectrum")
    floor = float(np.median(spectrum.y)) if spectrum is not None else -np.inf
    for i, (fk, dbc) in enumerate(result.extra["harmonics"]):
        level = level0 + dbc
        label = f"H{round(fk / f0)}" if level > floor + 20 else ""
        _marker(ax, fk, level, SERIES[3], "harmonics" if i == 0 else None, label)


def _sine_lines(result: Any, keys: list[tuple[str, str]]) -> list[str]:
    return [value_line(result, k, label) for k, label in keys]


@plotter("sinefit")
def plot_sinefit(result: Any, fig: Any) -> None:
    ax = fig.add_subplot()
    _time(ax, result)
    info_box(ax, _sine_lines(result, [("frequency", "f0"), ("amplitude", "A"),
                                      ("offset", "Offset"), ("rms_residual", "Residual RMS")]),
             loc="upper right")
    finish(fig, result.title, result)


@plotter("sinad")
def plot_sinad(result: Any, fig: Any) -> None:
    ax1, ax2, ax3 = fig.subplots(3, 1, height_ratios=[1, 1, 1.4])
    _time(ax1, result)
    _residual(ax2, result)
    _spectrum(ax3, result, "residual_spectrum")
    info_box(ax3, _sine_lines(result, [
        ("sinad", "SINAD"), ("enob", "ENOB"), ("enob_fs", "ENOB (FS)"),
        ("amplitude_dbfs", "Amplitude"), ("frequency", "f0"), ("sigma_r", "Residual RMS"),
    ]), loc=_box_loc(result, "residual_spectrum"))
    legend(ax3, loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=2, borderaxespad=0.1)
    finish(fig, result.title, result)


@plotter("sfdr")
def plot_sfdr(result: Any, fig: Any) -> None:
    ax = fig.add_subplot()
    _spectrum(ax, result)
    _fundamental_and_spur(ax, result)
    info_box(ax, _sine_lines(result, [
        ("sfdr_dbc", "SFDR"), ("sfdr_dbfs", "SFDR (FS)"), ("spur_frequency", "Spur at"),
        ("spur_nature", "Spur"), ("frequency", "f0"),
    ]), loc=_box_loc(result, "spectrum"))
    legend(ax, loc="lower left")
    finish(fig, result.title, result)


@plotter("thd")
def plot_thd(result: Any, fig: Any) -> None:
    ax = fig.add_subplot()
    _spectrum(ax, result)
    if "frequency" in result.values:
        _marker(ax, result.values["frequency"].value, result.values["amplitude_dbfs"].value,
                SERIES[1], "fundamental")
    _harmonics(ax, result)
    info_box(ax, _sine_lines(result, [("thd_db", "THD"), ("thd_pct", "THD"),
                                      ("n_harmonics_used", "Harmonics"), ("frequency", "f0")]),
             loc=_box_loc(result, "spectrum"))
    legend(ax, loc="lower left")
    finish(fig, result.title, result)


@plotter("dynamic")
def plot_dynamic(result: Any, fig: Any) -> None:
    grid = fig.add_gridspec(2, 2, width_ratios=[1, 1.5])
    ax_time = fig.add_subplot(grid[0, 0])
    ax_res = fig.add_subplot(grid[1, 0])
    ax_spec = fig.add_subplot(grid[:, 1])
    _time(ax_time, result)
    _residual(ax_res, result)
    _spectrum(ax_spec, result)
    _fundamental_and_spur(ax_spec, result)
    _harmonics(ax_spec, result)
    info_box(ax_spec, _sine_lines(result, [
        ("sinad", "SINAD"), ("enob", "ENOB"), ("enob_fs", "ENOB (FS)"), ("snr", "SNR"),
        ("thd_db", "THD"), ("sfdr_dbc", "SFDR"), ("dr", "Dynamic range"),
        ("amplitude_dbfs", "Amplitude"), ("frequency", "f0"),
    ]), loc=_box_loc(result, "spectrum"))
    legend(ax_spec, loc="lower left")
    finish(fig, result.title, result)
