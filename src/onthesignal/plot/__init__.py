"""Rendering of :class:`~onthesignal.Result` objects as matplotlib figures (rule R5).

Plot functions receive a result and fill a figure; they never compute anything and never
call ``plt.show()``. Without a figure argument, a headless ``matplotlib.figure.Figure`` is
created (reports); the console passes a pyplot-managed figure to display it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from matplotlib.figure import Figure

_PLOTTERS: dict[str, Callable | None] = {}


def plotter(*kinds: str) -> Callable[[Callable], Callable]:
    """Register a plot function for result kinds."""

    def decorator(func: Callable) -> Callable:
        for kind in kinds:
            _PLOTTERS[kind] = func
        return func

    return decorator


def no_figure(*kinds: str) -> None:
    """Declare result kinds that are displayed as tables only."""
    for kind in kinds:
        _PLOTTERS[kind] = None


def has_figure(kind: str) -> bool:
    _load()
    return _PLOTTERS.get(kind, _default) is not None


def _load() -> None:
    from . import lnm, measures, noise, signal, sine  # noqa: F401


def plot_result(result: Any, fig: Any = None) -> Any:
    """Render ``result`` into ``fig`` (created when omitted); ``None`` for table-only results."""
    _load()
    func = _PLOTTERS.get(result.kind, _default)
    if func is None:
        return None
    if fig is None:
        fig = Figure(figsize=(10, 6.5), layout="constrained")
    else:
        fig.set_layout_engine("constrained")
    func(result, fig)
    return fig


def _default(result: Any, fig: Any) -> None:
    """Generic rendering: every curve in one axes."""
    from .style import LINE_W, SERIES, finish, legend, style_axes

    ax = fig.add_subplot()
    for i, (name, c) in enumerate(result.curves.items()):
        ax.plot(c.x, c.y, color=SERIES[i % len(SERIES)], lw=LINE_W, label=c.label or name)
        ax.set_xscale(c.xscale)
        ax.set_yscale(c.yscale)
    style_axes(ax)
    legend(ax)
    finish(fig, result.title or result.kind, result)
