"""Figure style: validated categorical palette, recessive axes, information boxes.

Colors follow a validated reference palette (categorical slots in a fixed order, ink and
hairline grid tokens). Text always uses ink colors, never series colors.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: Categorical slots, light surface, fixed order (never cycled).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
NEUTRAL_WASH = "#f0efec"

LINE_W = 1.5
THIN_W = 0.8
MARKER = 6


def style_axes(ax: Any) -> None:
    """Recessive axes: hairline solid grid, light spines, ink labels."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK2, labelsize=8, length=3, width=0.6)
    ax.grid(True, which="major", color=GRID, linewidth=0.6, linestyle="-")
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)
    ax.xaxis.label.set_size(9)
    ax.yaxis.label.set_size(9)


def axis_label(name: str, unit: str) -> str:
    """``Frequency (Hz)``."""
    return f"{name} ({unit})" if unit else name


_PHYSICAL = {"V", "m", "m/s", "m/s²", "m/s**2"}


def physical_axis(ax: Any, name: str, unit: str) -> None:
    """Y label for a linear physical axis, with engineering ticks (``2 µV`` rather than 1e-6)."""
    if unit in _PHYSICAL:
        from matplotlib.ticker import EngFormatter

        ax.yaxis.set_major_formatter(EngFormatter(unit=unit.replace("**2", "²"), places=1))
        ax.set_ylabel(name)
    else:
        ax.set_ylabel(axis_label(name, unit))


def legend(ax: Any, **kwargs: Any) -> None:
    """Frameless legend in secondary ink (only when there are two series or more)."""
    handles, labels = ax.get_legend_handles_labels()
    if len(handles) >= 2:
        leg = ax.legend(frameon=False, fontsize=8, labelcolor=INK2, **kwargs)
        leg.set_zorder(5)


def info_box(ax: Any, lines: Iterable[str], loc: str = "upper right") -> None:
    """Results box drawn inside an axes."""
    lines = [ln for ln in lines if ln]
    if not lines:
        return
    x, ha = (0.985, "right") if "right" in loc else (0.015, "left")
    y, va = (0.975, "top") if "upper" in loc else (0.03, "bottom")
    ax.text(
        x, y, "\n".join(lines), transform=ax.transAxes, ha=ha, va=va, fontsize=7.5,
        family="monospace", color=INK, zorder=6,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": SURFACE, "edgecolor": GRID,
              "alpha": 0.92},
    )


def shade_band(ax: Any, band: list[float] | None) -> None:
    """Shade the study band."""
    if band:
        ax.axvspan(band[0], band[1], color=NEUTRAL_WASH, zorder=0, lw=0)


def mark_lines(ax: Any, freqs: Iterable[float], label: str = "mains (removed)") -> None:
    """Thin vertical lines at the given frequencies (e.g. removed mains lines)."""
    for i, f in enumerate(freqs):
        ax.axvline(f, color=MUTED, lw=0.7, ls=":", zorder=1, label=label if i == 0 else None)


def finish(fig: Any, title: str, result: Any = None, note: str | None = None) -> None:
    """Figure title, surface color and footnote (decimation, warning count)."""
    fig.patch.set_facecolor(SURFACE)
    fig.suptitle(title, x=0.01, ha="left", fontsize=10.5, color=INK)
    notes = [note] if note else []
    if result is not None and result.warnings:
        n = len(result.warnings)
        notes.append(f"{n} warning{'s' if n > 1 else ''}: see the result text")
    if notes:
        fig.text(0.01, 0.005, " · ".join(notes), fontsize=7.5, color=MUTED, ha="left", va="bottom")


def value_line(result: Any, key: str, label: str | None = None) -> str:
    """``label  value (physical value)`` for an information box ('' when absent)."""
    if key not in result.values:
        return ""
    v = result.values[key]
    text = f"{label or v.label}: {v.text()}"
    phys = result.values.get(key + "_phys")
    if phys is not None:
        text += f" ({phys.text()})"
    return text
