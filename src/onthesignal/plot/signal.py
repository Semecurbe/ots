"""Time-series figure (``S.show()``)."""

from __future__ import annotations

from typing import Any

import matplotlib.dates as mdates

from . import plotter
from .style import SERIES, THIN_W, finish, physical_axis, style_axes


@plotter("signal")
def plot_signal(result: Any, fig: Any) -> None:
    c = result.curves["signal"]
    ax = fig.add_subplot()
    ax.plot(c.x, c.y, color=SERIES[0], lw=THIN_W)
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_xlabel("Time (UTC)")
    physical_axis(ax, c.y_label, c.y_unit)
    style_axes(ax)
    finish(fig, result.title, result, note=result.extra.get("decimated"))
