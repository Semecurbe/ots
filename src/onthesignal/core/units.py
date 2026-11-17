"""Physical units: normalization, classification and formatting.

Recognized units are ``counts``, ``V``, ``m``, ``m/s`` and ``m/s**2``. Common spellings
(``m/s2``, ``m/s²``, ``M/S``, ``m.s-2``...) are normalized to these canonical forms. Other
units are accepted unchanged, but analyses that need a ground-motion quantity (``lnm``)
reject them.
"""

from __future__ import annotations

import math

import numpy as np

COUNTS = "counts"
CANONICAL_UNITS = ("counts", "V", "m", "m/s", "m/s**2")

_ALIASES = {
    "count": COUNTS,
    "counts": COUNTS,
    "cts": COUNTS,
    "lsb": COUNTS,
    "digit": COUNTS,
    "digits": COUNTS,
    "v": "V",
    "volt": "V",
    "volts": "V",
    "m": "m",
    "m/s": "m/s",
    "m.s-1": "m/s",
    "m s-1": "m/s",
    "ms-1": "m/s",
    "m/s**2": "m/s**2",
    "m/s^2": "m/s**2",
    "m/s2": "m/s**2",
    "m/s²": "m/s**2",
    "m.s-2": "m/s**2",
    "m s-2": "m/s**2",
    "ms-2": "m/s**2",
}

_MOTION = {"m": "displacement", "m/s": "velocity", "m/s**2": "acceleration"}
_PREFIXABLE = {"V", "m", "m/s", "m/s**2"}
_PREFIXES = [
    (1e-15, "f"),
    (1e-12, "p"),
    (1e-9, "n"),
    (1e-6, "µ"),
    (1e-3, "m"),
    (1.0, ""),
    (1e3, "k"),
    (1e6, "M"),
    (1e9, "G"),
]


def normalize_unit(unit: str | None) -> str:
    """Return the canonical spelling of ``unit`` (``counts`` when empty)."""
    if unit is None or str(unit).strip() == "":
        return COUNTS
    text = str(unit).strip()
    return _ALIASES.get(text.lower(), text)


def is_counts(unit: str) -> bool:
    """True when ``unit`` designates raw digitizer counts."""
    return normalize_unit(unit) == COUNTS


def motion_quantity(unit: str) -> str | None:
    """Ground-motion quantity of a unit: ``displacement``, ``velocity``, ``acceleration``.

    Returns ``None`` for units that are not ground-motion units (``counts``, ``V``...).
    """
    return _MOTION.get(normalize_unit(unit))


def pretty_unit(unit: str) -> str:
    """Unit spelling for display (``m/s**2`` becomes ``m/s²``)."""
    return normalize_unit(unit).replace("**2", "²") if unit else ""


def fmt_num(value: float | int | None, digits: int = 4) -> str:
    """Format a number with about ``digits`` significant digits, avoiding needless exponents."""
    if value is None:
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value))
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    v = float(value)
    if math.isnan(v):
        return "nan"
    if math.isinf(v):
        return "inf" if v > 0 else "-inf"
    if v == 0:
        return "0"
    a = abs(v)
    if v.is_integer() and a < 1e12:
        return str(int(v))
    if 1e-3 <= a < 1e7:
        decimals = max(0, digits - 1 - int(math.floor(math.log10(a))))
        return f"{v:.{decimals}f}"
    return f"{v:.{max(digits - 1, 1)}e}"


def format_quantity(value: float | None, unit: str, digits: int = 4) -> str:
    """Format a value with its unit, using an SI prefix for physical units (``2.43 µV``)."""
    if value is None:
        return "—"
    u = normalize_unit(unit) if unit else ""
    if u in _PREFIXABLE and value != 0 and math.isfinite(float(value)):
        a = abs(float(value))
        factor, prefix = _PREFIXES[0]
        for f, p in _PREFIXES:
            if a >= f:
                factor, prefix = f, p
        return f"{fmt_num(float(value) / factor, digits)} {prefix}{pretty_unit(u)}"
    text = fmt_num(value, digits)
    return f"{text} {pretty_unit(u) if u else ''}".strip()
