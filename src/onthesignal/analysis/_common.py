"""Helpers shared by the analysis modules."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..core.result import Result
from ..core.signal import Signal
from ..core.units import COUNTS
from ..processing.band import BandResult, band_limit, detrend_data


def window_signal(signal: Signal, p: dict) -> Signal:
    """Signal restricted to the ``t_start`` / ``t_end`` window of the parameters."""
    if p.get("t_start") is None and p.get("t_end") is None:
        return signal
    return signal.slice(p.get("t_start"), p.get("t_end"))


def apply_band(x: np.ndarray, fs: float, p: dict, detrend: str | None = None) -> BandResult:
    """Detrend then limit ``x`` to the study band described by the parameters."""
    xd = detrend_data(x, p.get("detrend", "constant") if detrend is None else detrend)
    return band_limit(
        xd,
        fs,
        fmin=p["fmin"],
        fmax=p["fmax"],
        remove_mains=p["remove_mains"],
        mains_freq=p["mains_freq"],
        mains_width=p["mains_width"],
        mains_harmonics=p["mains_harmonics"],
        method=p["filter_method"],
        order=p["filter_order"],
    )


def show_physical(signal: Signal, p: dict) -> bool:
    """True when results must also be given in physical units."""
    return signal.unit != COUNTS and p.get("units", "physical") == "physical"


def add_counts(
    result: Result,
    key: str,
    value: float,
    label: str,
    signal: Signal,
    p: dict,
    digits: int = 4,
    signed: bool = False,
) -> None:
    """Add a value in counts and, when relevant, its physical counterpart (``key_phys``).

    ``signed`` values (offsets) follow the sign of the sensitivity; magnitudes (RMS,
    peak-to-peak) use its absolute value.
    """
    result.add(key, value, COUNTS, label, digits)
    if show_physical(signal, p):
        factor = signal.sensitivity if signed else abs(signal.sensitivity)
        result.add(key + "_phys", value * factor, signal.unit, label, digits)


def band_title(band: BandResult) -> str:
    """``band 0–100 Hz · mains removed (50, 100 Hz)``."""
    text = f"band {band.fmin:.6g}–{band.fmax:.6g} Hz"
    if band.removed_lines:
        text += f" · mains removed ({', '.join(f'{f:.6g}' for f in band.removed_lines)} Hz)"
    return text


def signal_label(signal: Signal) -> str:
    """``S1 · acquisition_FHZ (RD.SN270.00.FHZ)`` (see :attr:`Signal.label`)."""
    return signal.label


def add_band_values(result: Result, band: BandResult) -> None:
    """Band, noise bandwidth and removed mains lines."""
    result.add("band", [band.fmin, band.fmax], "Hz", "Study band", kind="range")
    result.add("enbw", band.enbw, "Hz", "Noise bandwidth (ENBW)")
    if band.removed_lines:
        result.add("mains_removed", list(band.removed_lines), "Hz", "Mains lines removed")
    for w in band.warnings:
        result.warn(w)


def clean_params(p: dict) -> dict[str, Any]:
    """Parameters as stored in results (signals replaced by their names)."""
    out = {}
    for k, v in p.items():
        out[k] = (v.name or v.id) if isinstance(v, Signal) else v
    return out
