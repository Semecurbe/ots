"""PSD versus Peterson models (``lnm``): PSD and models on top, difference below."""

from __future__ import annotations

from typing import Any

import numpy as np

from . import plotter
from .style import (
    AXIS,
    INK2,
    LINE_W,
    MUTED,
    SERIES,
    finish,
    info_box,
    legend,
    style_axes,
    value_line,
)


@plotter("lnm")
def plot_lnm(result: Any, fig: Any) -> None:
    period = result.extra.get("x", "freq") == "period"

    def to_x(f: np.ndarray) -> np.ndarray:
        return 1.0 / np.asarray(f) if period else np.asarray(f)

    ax1, ax2 = fig.subplots(2, 1, sharex=True, height_ratios=[2, 1])
    psd, smooth = result.curves["psd"], result.curves["psd_smooth"]
    ax1.plot(to_x(psd.x), psd.y, color=SERIES[0], lw=0.6, alpha=0.35, label="PSD (raw)")
    ax1.plot(to_x(smooth.x), smooth.y, color=SERIES[0], lw=LINE_W, label=smooth.label)
    nlnm = result.curves["nlnm"]
    ax1.plot(to_x(nlnm.x), nlnm.y, color=INK2, lw=1.2, label="NLNM")
    if "nhnm" in result.curves:
        nhnm = result.curves["nhnm"]
        ax1.plot(to_x(nhnm.x), nhnm.y, color=MUTED, lw=1.2, ls="--", label="NHNM")
    in_view = (nlnm.x >= psd.x[0]) & (nlnm.x <= psd.x[-1])
    refs = [nlnm.y[in_view]]
    if "nhnm" in result.curves:
        refs.append(result.curves["nhnm"].y[in_view])
    ref = np.concatenate(refs) if np.any(in_view) else nlnm.y
    ax1.set_ylim(min(np.nanmin(smooth.y), np.nanmin(ref)) - 10,
                 max(np.nanmax(smooth.y), np.nanmax(ref)) + 10)
    ax1.set_ylabel(f"PSD ({psd.y_unit})")
    style_axes(ax1)
    # Above the axes: the models cross the whole plot, so no inner corner is reliably free.
    legend(ax1, loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=4, borderaxespad=0.1)

    diff = result.curves["diff"]
    xd = to_x(diff.x)
    ax2.plot(xd, diff.y, color=SERIES[0], lw=LINE_W)
    ax2.axhline(0.0, color=AXIS, lw=1.0)
    ax2.fill_between(xd, diff.y, 0.0, where=diff.y < 0, color=SERIES[0], alpha=0.1, lw=0,
                     label="below NLNM")
    ax2.set_ylabel("PSD − NLNM (dB)")
    ax2.set_xlabel("Period (s)" if period else "Frequency (Hz)")
    ax2.set_xscale("log")
    style_axes(ax2)
    info_box(ax2, [
        value_line(result, "diff_max", "Max"),
        value_line(result, "period_max", "at period") if period
        else value_line(result, "freq_max", "at frequency"),
        value_line(result, "below_nlnm", "Below NLNM"),
    ])
    lims = sorted(to_x(np.array([diff.x[0], diff.x[-1]])))
    span = to_x(np.array([psd.x[0], psd.x[-1]]))
    ax2.set_xlim(min(lims[0], span.min()), max(lims[1], span.max()))
    finish(fig, result.title, result)
