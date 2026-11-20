"""Analysis results (specification rule R4).

A :class:`Result` holds everything an analysis produced: scalar values with units, curves,
tables, warnings and the exact parameters used. It is serializable (``to_dict`` / ``to_json``)
so that the same object feeds the console, the reports, the AI assistant and, later, the web
interface. Rendering is done elsewhere (``onthesignal.plot``).
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .._version import __version__
from .units import fmt_num, format_quantity


def _cell(value: Any) -> str:
    return fmt_num(value) if isinstance(value, (int, float)) else str(value)


def jsonable(obj: Any) -> Any:
    """Convert numpy types, times and non-finite floats into JSON-compatible values."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        if math.isnan(v):
            return None
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return v
    if obj is None or isinstance(obj, (int, str)):
        return obj
    return str(obj)


@dataclass
class Value:
    """Scalar result with unit and label."""

    value: Any
    unit: str = ""
    label: str = ""
    digits: int = 4
    #: ``"range"`` for ``[low, high]`` intervals, displayed ``low–high``.
    kind: str = ""

    def __float__(self) -> float:
        return float(self.value)

    def text(self) -> str:
        """Value formatted with its unit (SI prefix for physical units)."""
        if isinstance(self.value, str):
            return self.value
        if isinstance(self.value, (list, tuple)):
            sep = "–" if self.kind == "range" else ", "
            return sep.join(f"{float(v):.6g}" for v in self.value) + (
                f" {self.unit}" if self.unit else ""
            )
        return format_quantity(self.value, self.unit, self.digits)

    def to_dict(self) -> dict:
        return {"value": jsonable(self.value), "unit": self.unit, "label": self.label}

    def __repr__(self) -> str:
        return f"<{self.label or 'Value'}: {self.text()}>"


@dataclass
class Curve:
    """Curve for rendering: ``x`` and ``y`` arrays with labels, units and scales."""

    x: np.ndarray
    y: np.ndarray
    label: str = ""
    x_label: str = ""
    y_label: str = ""
    x_unit: str = ""
    y_unit: str = ""
    xscale: str = "linear"
    yscale: str = "linear"

    def to_dict(self, max_points: int | None = None) -> dict:
        x, y = np.asarray(self.x), np.asarray(self.y)
        if max_points and x.size > max_points:
            idx = np.unique(np.linspace(0, x.size - 1, max_points).astype(int))
            x, y = x[idx], y[idx]
        return {
            "label": self.label,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "x_unit": self.x_unit,
            "y_unit": self.y_unit,
            "xscale": self.xscale,
            "yscale": self.yscale,
            "x": jsonable(x),
            "y": jsonable(y),
        }


@dataclass
class Result:
    """Outcome of an analysis.

    Attributes
    ----------
    kind : str
        Analysis name (``noise``, ``lnm``, ``sinad``...).
    title : str
        Human-readable title (analysis, signal and main options).
    signals : list of dict
        Identity of the analysed signals (name, NSLC id, source, SHA-256).
    params : dict
        Parameters actually used, after defaults and adjustments.
    values : dict of Value
        Scalar results. ``result["rms"]`` returns the bare number.
    curves : dict of Curve
        Curves for rendering.
    tables : dict of list of dict
        Tabular results (e.g. harmonics).
    warnings : list of str
        Warnings (saturation, gaps, reduced band...).
    extra : dict
        Additional rendering information (markers, shaded bands...).
    meta : dict
        Software version, creation time, computation time.
    name : str
        Session name (``R1``, ``R2``...), given when the result is added to a session.
    """

    kind: str
    title: str = ""
    signals: list[dict] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    values: dict[str, Value] = field(default_factory=dict)
    curves: dict[str, Curve] = field(default_factory=dict)
    tables: dict[str, list[dict]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    name: str = ""

    def __post_init__(self) -> None:
        self.meta.setdefault("version", __version__)
        self.meta.setdefault("created", datetime.now(UTC).isoformat(timespec="seconds"))

    # ------------------------------------------------------------------ building
    def add(self, key: str, value: Any, unit: str = "", label: str = "", digits: int = 4,
            kind: str = "") -> None:
        """Add a scalar value (``kind="range"`` for ``[low, high]`` intervals)."""
        self.values[key] = Value(value, unit, label or key, digits, kind)

    def warn(self, message: str) -> None:
        """Add a warning (duplicates are ignored)."""
        if message not in self.warnings:
            self.warnings.append(message)

    def merge(self, other: Result, prefix: str = "") -> None:
        """Copy values, curves, tables and warnings of ``other`` into this result."""
        for k, v in other.values.items():
            self.values[prefix + k] = v
        for k, c in other.curves.items():
            self.curves[prefix + k] = c
        for k, t in other.tables.items():
            self.tables[prefix + k] = t
        for w in other.warnings:
            self.warn(w)

    # ------------------------------------------------------------------ access
    def __getitem__(self, key: str) -> Any:
        return self.values[key].value

    def __contains__(self, key: str) -> bool:
        return key in self.values

    # ------------------------------------------------------------------ export
    def to_dict(self, curves: bool = True, max_points: int | None = None) -> dict:
        """Serializable representation; ``curves=False`` keeps only scalar results."""
        out = {
            "name": self.name,
            "kind": self.kind,
            "title": self.title,
            "signals": jsonable(self.signals),
            "params": jsonable(self.params),
            "values": {k: v.to_dict() for k, v in self.values.items()},
            "tables": jsonable(self.tables),
            "warnings": list(self.warnings),
            "meta": jsonable(self.meta),
        }
        if curves:
            out["curves"] = {k: c.to_dict(max_points) for k, c in self.curves.items()}
        return out

    def to_json(self, curves: bool = True, max_points: int | None = None, indent: int = 2) -> str:
        return json.dumps(self.to_dict(curves, max_points), indent=indent, ensure_ascii=False)

    def save(self, path: str | Path) -> Path:
        """Save as JSON (``.json``) or as a value table (``.csv``)."""
        path = Path(path)
        if path.suffix.lower() == ".csv":
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["key", "label", "value", "unit"])
                for k, v in self.values.items():
                    writer.writerow([k, v.label, jsonable(v.value), v.unit])
        else:
            path.write_text(self.to_json(), encoding="utf-8")
        return path

    def rows(self) -> list[tuple[str, str, str]]:
        """Display rows ``(label, value, physical value)``.

        A key ``k_phys`` holds the physical-unit counterpart of key ``k`` (in counts); both are
        shown on the same row.
        """
        out = []
        for key, v in self.values.items():
            if key.endswith("_phys") and key[:-5] in self.values:
                continue
            phys = self.values.get(key + "_phys")
            out.append((v.label, v.text(), phys.text() if phys is not None else ""))
        return out

    def to_text(self) -> str:
        """Plain-text rendering: title, values and warnings."""
        lines = [self.title or self.kind]
        rows = self.rows()
        width = max((len(r[0]) for r in rows), default=0)
        vwidth = max((len(r[1]) for r in rows if r[2]), default=0)
        for label, text, phys in rows:
            if phys:
                lines.append(f"  {label:<{width}}  {text:>{vwidth}}   ({phys})")
            else:
                lines.append(f"  {label:<{width}}  {text}")
        for name, table in self.tables.items():
            if table:
                lines.append(f"  [{name}]")
                keys = list(table[0].keys())
                lines.append("    " + "  ".join(f"{k:>12}" for k in keys))
                for row in table:
                    cells = [_cell(row[k]) for k in keys]
                    lines.append("    " + "  ".join(f"{c:>12}" for c in cells))
        for w in self.warnings:
            lines.append(f"  Warning: {w}")
        return "\n".join(lines)

    def print(self) -> None:
        """Print :meth:`to_text`."""
        print(self.to_text())

    def plot(self, fig: Any = None) -> Any:
        """Render the result as a matplotlib figure (see :mod:`onthesignal.plot`)."""
        from ..plot import plot_result

        return plot_result(self, fig)

    def show(self) -> None:
        """Display the result with the active display handler (console or script)."""
        from .. import api

        api.display(self, show=True)

    def __repr__(self) -> str:
        names = ", ".join(s.get("name", "?") for s in self.signals)
        main = ", ".join(f"{k}={v.text()}" for k, v in list(self.values.items())[:3])
        prefix = f"{self.name} " if self.name else ""
        return f"<Result {prefix}{self.kind} {names}: {main}>"
