"""Automatic checks shared by the analyses (specification §7.4)."""

from __future__ import annotations

import numpy as np

from ..core.signal import Signal
from ..core.units import fmt_num


def saturation_warning(data_counts: np.ndarray, full_scale: float) -> str | None:
    """Warning when samples reach 99.9 % of the half full scale."""
    limit = 0.999 * full_scale / 2.0
    n = int(np.count_nonzero(np.abs(data_counts) >= limit))
    if n:
        return (
            f"Probable saturation: {n} sample(s) reach 99.9 % of the half full scale "
            f"({fmt_num(full_scale / 2)} counts)"
        )
    return None


def gaps_warning(signal: Signal) -> str | None:
    """Reminder of the gaps found when the file was loaded."""
    gaps = [g for g in signal.gaps if g.get("type", "gap") == "gap"]
    if not gaps:
        return None
    total = sum(g.get("duration", 0.0) for g in gaps)
    actions = sorted({g.get("action", "") for g in gaps} - {""})
    return (
        f"The source file has {len(gaps)} gap(s) ({fmt_num(total)} s)"
        + (f": {', '.join(actions)}" if actions else "")
    )


def duration_warning(signal: Signal, fmin: float) -> str | None:
    """Warning when the record holds fewer than 10 periods of ``fmin``."""
    if fmin > 0 and signal.duration * fmin < 10:
        return (
            f"The record ({fmt_num(signal.duration)} s) holds fewer than 10 periods of "
            f"fmin = {fmt_num(fmin)} Hz"
        )
    return None
