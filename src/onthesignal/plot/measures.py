"""Figures of the measurements, coherence and spectrogram."""

from __future__ import annotations

from typing import Any

import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap

from . import no_figure, plotter
from .style import (
    AXIS,
    INK2,
    LINE_W,
    MARKER,
    SERIES,
    SURFACE,
    THIN_W,
    axis_label,
    finish,
    info_box,
    legend,
    physical_axis,
    style_axes,
    value_line,
)

no_figure("frequency")

#: Sequential single-hue ramp (light → dark) for magnitudes.
SEQUENTIAL = LinearSegmentedColormap.from_list(
    "onthesignal_blue",
    ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
)


@plotter("period")
def plot_period(result: Any, fig: Any) -> None:
    ax = fig.add_subplot()
    c = result.curves.get("periods")
    if c is None:
        ax.text(0.5, 0.5, "No period series (method without crossings)", ha="center",
                color=INK2, transform=ax.transAxes)
    else:
        ax.plot(c.x, c.y, color=SERIES[0], lw=THIN_W, marker="o", ms=2)
        ax.set_xlabel(axis_label(c.x_label, c.x_unit))
        ax.set_ylabel(axis_label(c.y_label, c.y_unit))
    style_axes(ax)
    info_box(ax, [value_line(result, k) for k in ("period", "period_std", "n_periods")])
    finish(fig, result.title, result)


@plotter("delay50")
def plot_delay(result: Any, fig: Any) -> None:
    ax = fig.add_subplot()
    for i, key in enumerate(("s1", "s2")):
        c = result.curves[key]
        ax.plot(c.x, c.y, color=SERIES[i], lw=LINE_W, label=c.label, marker="o", ms=3)
    level = result.extra.get("level", 0.5)
    ax.axhline(level, color=AXIS, lw=1.0)
    for i, t in enumerate(result.extra.get("markers", [])):
        ax.plot([t], [level], ls="none", marker="o", ms=MARKER, color=SERIES[i], mec=SURFACE,
                mew=1.5, zorder=4)
    c = result.curves["s1"]
    ax.set_xlabel(axis_label(c.x_label, c.x_unit))
    ax.set_ylabel("Normalized amplitude")
    style_axes(ax)
    legend(ax, loc="lower right")
    info_box(ax, [value_line(result, k) for k in ("delay", "delay_std", "n_edges")],
             loc="upper left")
    finish(fig, result.title, result)


@plotter("coherence")
def plot_coherence(result: Any, fig: Any) -> None:
    ax = fig.add_subplot()
    c = result.curves["coherence"]
    ax.plot(c.x, c.y, color=SERIES[0], lw=LINE_W)
    if "threshold" in result.extra:
        ax.axhline(result.extra["threshold"], color=INK2, lw=1.0, ls="--",
                   label="significance level")
        ax.plot([], [], color=SERIES[0], lw=LINE_W, label="coherence")
        legend(ax, loc="lower left")
    ax.set_xscale(c.xscale)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel(axis_label(c.x_label, c.x_unit))
    ax.set_ylabel("Coherence")
    style_axes(ax)
    info_box(ax, [value_line(result, k) for k in ("mean_coherence", "band", "n_averages")])
    finish(fig, result.title, result)


@plotter("spectrogram")
def plot_spectrogram(result: Any, fig: Any) -> None:
    image = result.extra["image"]
    signal = result.curves.get("signal")
    if signal is not None:
        ax_sig, ax = fig.subplots(2, 1, sharex=True, height_ratios=[1, 3])
        ax_sig.plot(signal.x, signal.y, color=SERIES[0], lw=THIN_W)
        physical_axis(ax_sig, signal.y_label, signal.y_unit)
        style_axes(ax_sig)
    else:
        ax = fig.add_subplot()
    mesh = ax.pcolormesh(image["t"], image["f"], image["z"], shading="auto", cmap=SEQUENTIAL,
                         vmin=image["vmin"], vmax=image["vmax"], rasterized=True)
    ax.set_yscale(image["yscale"])
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_xlabel("Time (UTC)")
    ax.set_ylabel("Frequency (Hz)")
    style_axes(ax)
    ax.grid(False)
    bar = fig.colorbar(mesh, ax=ax, pad=0.01)
    bar.set_label(image["unit"], color=INK2, fontsize=9)
    bar.ax.tick_params(colors=INK2, labelsize=8)
    bar.outline.set_edgecolor(AXIS)
    finish(fig, result.title, result)
