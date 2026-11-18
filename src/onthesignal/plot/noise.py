"""Noise figures: amplitude spectrum (``noise_fft``) and Welch PSD (``noise_dsp``)."""

from __future__ import annotations

from typing import Any

from . import no_figure, plotter
from .style import (
    LINE_W,
    SERIES,
    THIN_W,
    axis_label,
    finish,
    info_box,
    legend,
    mark_lines,
    physical_axis,
    shade_band,
    style_axes,
    value_line,
)

no_figure("noise")


def noise_lines(result: Any) -> list[str]:
    """Information box lines shared by the noise figures."""
    lines = [
        value_line(result, "mean", "Mean"),
        value_line(result, "rms", "RMS"),
        value_line(result, "rms_psd", "RMS (PSD)"),
        value_line(result, "pp", "P-P"),
        value_line(result, "dr", "Dynamic range"),
        value_line(result, "enob", "Noise ENOB"),
    ]
    band = result.values.get("band")
    enbw = result.values.get("enbw")
    if band is not None:
        lines.append(f"Band: {band.text()}" + (f" · ENBW {enbw.text()}" if enbw else ""))
    mains = result.values.get("mains_removed")
    if mains is not None:
        lines.append(f"Mains removed: {mains.text()}")
    return lines


def _spectral_axes(ax: Any, result: Any, curve: Any) -> None:
    shade_band(ax, result.extra.get("band"))
    mark_lines(ax, result.extra.get("mains_lines", []),
               label=f"{result.params.get('mains_freq', 50.0):g} Hz and harmonics (removed)")
    ax.set_xscale(curve.xscale)
    ax.set_yscale(curve.yscale)
    ax.set_xlabel(axis_label(curve.x_label, curve.x_unit))
    ax.set_ylabel(axis_label(curve.y_label, curve.y_unit))
    style_axes(ax)


@plotter("noise_fft")
def plot_noise_fft(result: Any, fig: Any) -> None:
    c = result.curves["spectrum"]
    ax = fig.add_subplot()
    ax.plot(c.x, c.y, color=SERIES[0], lw=THIN_W, label="spectrum")
    _spectral_axes(ax, result, c)
    extra = [value_line(result, "window", "Window") + " · " + value_line(result, "df", "Δf")]
    info_box(ax, noise_lines(result) + extra)
    legend(ax, loc="lower left")
    finish(fig, result.title, result)


@plotter("noise_dsp")
def plot_noise_dsp(result: Any, fig: Any) -> None:
    c = result.curves["psd"]
    cumulative = result.curves.get("cumulative_rms")
    if cumulative is not None:
        ax, ax2 = fig.subplots(2, 1, sharex=True, height_ratios=[2, 1])
    else:
        ax, ax2 = fig.add_subplot(), None
    ax.plot(c.x, c.y, color=SERIES[0], lw=LINE_W, label="PSD")
    _spectral_axes(ax, result, c)
    extra = [
        value_line(result, "n_averages", "Welch averages") + " · " + value_line(result, "df", "Δf")
    ]
    info_box(ax, noise_lines(result) + extra)
    legend(ax, loc="lower left")
    if ax2 is not None:
        ax2.plot(cumulative.x, cumulative.y, color=SERIES[0], lw=LINE_W)
        shade_band(ax2, result.extra.get("band"))
        ax2.set_xscale(cumulative.xscale)
        physical_axis(ax2, cumulative.y_label, cumulative.y_unit)
        ax2.set_xlabel(axis_label(cumulative.x_label, cumulative.x_unit))
        ax.set_xlabel("")
        style_axes(ax2)
    finish(fig, result.title, result)
