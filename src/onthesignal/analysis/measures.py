"""Time measurements: frequency, period and 50 % crossing delay (specification §11).

Crossing instants are found with a Schmitt trigger (hysteresis) to ignore noise-induced
multiple crossings, then refined to a fraction of a sample by linear interpolation between
the two samples surrounding the threshold.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..core.errors import AnalysisError, TimeRangeError
from ..core.params import Param, resolve_params
from ..core.registry import register
from ..core.result import Curve, Result
from ..core.signal import Signal
from ..core.units import fmt_num
from ..processing.params import TIME_PARAMS
from ._common import clean_params, signal_label, window_signal
from .sinefit import estimate_frequency, fit4

#: Rows of the table of the periods (the curve shows all of them).
MAX_PERIOD_ROWS = 10_000

MEASURE_PARAMS = (
    Param("method", str, "zero_crossing", choices=("zero_crossing", "sinefit", "fft"),
          help="Crossings of the mean level, 4-parameter sine fit or interpolated FFT peak"),
    Param("hysteresis", float, 0.05, min=0.0, max=0.5, advanced=True,
          help="Hysteresis, as a fraction of the peak-to-peak amplitude"),
    *TIME_PARAMS,
)
DELAY_PARAMS = (
    Param("edge", str, "rising", choices=("rising", "falling", "both"), help="Edges measured"),
    Param("level", float, 0.5, min=0.0, max=1.0,
          help="Threshold between the low and high levels (0.5 = 50 %)"),
    Param("levels", str, "histogram", choices=("histogram", "minmax"), advanced=True,
          help="Low/high levels: histogram modes (oscilloscope method) or min/max"),
    Param("hysteresis", float, 0.05, min=0.0, max=0.5, advanced=True,
          help="Hysteresis, as a fraction of the high − low amplitude"),
    *TIME_PARAMS,
)


def crossings(x: np.ndarray, level: float, hysteresis: float = 0.0, edge: str = "rising"
              ) -> np.ndarray:
    """Fractional sample indices where ``x`` crosses ``level`` (Schmitt trigger).

    An edge is validated when the signal moves from below ``level - h/2`` to above
    ``level + h/2`` (rising); its instant is the last crossing of ``level`` before
    validation, interpolated linearly between samples.
    """
    x = np.asarray(x, dtype=np.float64)
    if edge == "falling":
        return crossings(-x, -level, hysteresis, "rising")
    h = hysteresis / 2.0
    state = np.where(x >= level + h, 1, np.where(x <= level - h, -1, 0))
    idx = np.where(state != 0, np.arange(x.size), 0)
    np.maximum.accumulate(idx, out=idx)
    filled = state[idx]
    triggers = np.flatnonzero((filled[1:] == 1) & (filled[:-1] == -1)) + 1
    if triggers.size == 0:
        return np.array([])
    cand = np.flatnonzero((x[:-1] < level) & (x[1:] >= level))
    pos = np.searchsorted(cand, triggers, side="left") - 1
    valid = pos >= 0
    k = cand[pos[valid]]
    frac = (level - x[k]) / (x[k + 1] - x[k])
    return k + frac


def _levels(x: np.ndarray, method: str) -> tuple[float, float]:
    """Low and high levels (histogram modes of each half, or min/max)."""
    lo, hi = float(np.min(x)), float(np.max(x))
    if method == "minmax" or hi == lo:
        return lo, hi
    counts, edges = np.histogram(x, bins=256)
    centres = 0.5 * (edges[:-1] + edges[1:])
    mid = 0.5 * (lo + hi)
    low_half, high_half = centres < mid, centres >= mid
    base = float(centres[low_half][np.argmax(counts[low_half])])
    top = float(centres[high_half][np.argmax(counts[high_half])])
    return base, top


def _periodic(signal: Signal, p: dict, kind: str) -> tuple[Signal, Result, np.ndarray]:
    sig = window_signal(signal, p)
    x = sig.data
    fs = sig.sampling_rate
    r = Result(kind, signals=[sig.identity()], params=clean_params(p))
    periods = np.array([])
    if p["method"] == "zero_crossing":
        tc = crossings(x, float(np.mean(x)), p["hysteresis"] * float(np.ptp(x)))
        if tc.size < 2:
            raise AnalysisError("Fewer than two rising crossings of the mean level were found")
        periods = np.diff(tc) / fs
        frequency = (tc.size - 1) / ((tc[-1] - tc[0]) / fs)
        r.curves["periods"] = Curve(tc[1:] / fs, periods, label="period", x_label="Time",
                                    x_unit="s", y_label="Period", y_unit="s")
        # Each period: its start (from the start of the analysed window) and its frequency.
        n = min(periods.size, MAX_PERIOD_ROWS)
        r.tables["periods"] = [
            {"period": i + 1, "start_s": float(tc[i] / fs), "duration_s": float(periods[i]),
             "frequency_hz": float(1.0 / periods[i])} for i in range(n)]
        if periods.size > n:
            r.warn(f"The table of the periods shows the first {n} of {periods.size} periods "
                   "(the curve shows all of them)")
    elif p["method"] == "sinefit":
        frequency = fit4(x, fs).frequency
    else:
        frequency = estimate_frequency(x, fs)
    r.extra["method"] = p["method"]
    return sig, r, periods if periods.size else np.array([1.0 / frequency])


@register("frequency", MEASURE_PARAMS, category="measure",
          description="Frequency of a periodic signal (crossings, sine fit or FFT)")
def compute_frequency(signal: Signal, **params: Any) -> Result:
    """Frequency: number of full periods between the first and last rising crossings of the
    mean level divided by their time interval (or 4-parameter fit, or FFT peak)."""
    p = resolve_params(MEASURE_PARAMS, params, signal, command="frequency")
    sig, r, periods = _periodic(signal, p, "frequency")
    if p["method"] == "zero_crossing":
        f = len(periods) / float(np.sum(periods))
    else:
        f = 1.0 / periods[0]
    r.title = f"Frequency — {signal_label(sig)} · {p['method']}"
    r.add("frequency", float(f), "Hz", "Frequency", digits=9)
    if p["method"] == "zero_crossing":
        freqs = 1.0 / periods
        r.curves["frequencies"] = Curve(r.curves["periods"].x, freqs, label="frequency",
                                        x_label="Time", x_unit="s", y_label="Frequency",
                                        y_unit="Hz")
        r.add("frequency_std", float(np.std(freqs)), "Hz", "Period-to-period dispersion")
        r.add("n_periods", int(periods.size), "", "Periods measured")
    return r


@register("period", MEASURE_PARAMS, category="measure",
          description="Period of a periodic signal: mean, standard deviation, min, max")
def compute_period(signal: Signal, **params: Any) -> Result:
    """Period statistics between successive rising crossings of the mean level."""
    p = resolve_params(MEASURE_PARAMS, params, signal, command="period")
    sig, r, periods = _periodic(signal, p, "period")
    r.title = f"Period — {signal_label(sig)} · {p['method']}"
    r.add("period", float(np.mean(periods)), "s", "Mean period", digits=9)
    r.add("period_std", float(np.std(periods)), "s", "Standard deviation")
    r.add("period_min", float(np.min(periods)), "s", "Minimum", digits=9)
    r.add("period_max", float(np.max(periods)), "s", "Maximum", digits=9)
    r.add("n_periods", int(periods.size), "", "Periods measured")
    return r


def _edges(sig: Signal, p: dict, kind: str, ref: float) -> tuple[np.ndarray, float, float]:
    base, top = _levels(sig.data, p["levels"])
    if top <= base:
        raise AnalysisError(f"{sig.name or sig.id} has no transition (constant signal)")
    threshold = base + p["level"] * (top - base)
    idx = crossings(sig.data, threshold, p["hysteresis"] * (top - base), kind)
    return (sig.starttime.timestamp - ref) + idx / sig.sampling_rate, base, top


@register("delay50", DELAY_PARAMS, n_signals=2, category="measure",
          description="Delay between two signals at 50 % of their transitions")
def compute_delay50(signal1: Signal, signal2: Signal, **params: Any) -> Result:
    """Delay ``t(S2) − t(S1)`` between the 50 % crossings of two signals.

    Low/high levels come from the histogram of each signal (or min/max); crossing instants
    are interpolated between samples and expressed in absolute time, so the two signals may
    have different sampling rates. Each edge of S1 is paired with the nearest edge of S2.
    """
    p = resolve_params(DELAY_PARAMS, params, signal1, command="delay50")
    s1, s2 = window_signal(signal1, p), window_signal(signal2, p)
    if min(s1.endtime, s2.endtime) < max(s1.starttime, s2.starttime):
        raise TimeRangeError("The two signals do not overlap in time")
    ref = min(s1.starttime.timestamp, s2.starttime.timestamp)
    kinds = ["rising", "falling"] if p["edge"] == "both" else [p["edge"]]
    rows, delays = [], []
    levels = {}
    for kind in kinds:
        t1, b1, h1 = _edges(s1, p, kind, ref)
        t2, b2, h2 = _edges(s2, p, kind, ref)
        levels = {"s1": (b1, h1), "s2": (b2, h2)}
        if t1.size == 0 or t2.size == 0:
            continue
        j = np.searchsorted(t2, t1)
        left = np.clip(j - 1, 0, t2.size - 1)
        right = np.clip(j, 0, t2.size - 1)
        nearest = np.where(np.abs(t2[left] - t1) <= np.abs(t2[right] - t1), left, right)
        for a, b in zip(t1, t2[nearest], strict=True):
            delays.append(b - a)
            rows.append({"edge": kind, "t1_s": a, "t2_s": b, "delay_s": b - a})
    if not delays:
        raise AnalysisError("No matching edges were found in the two signals")
    d = np.asarray(delays)
    r = Result("delay50", signals=[s1.identity(), s2.identity()], params=clean_params(p))
    r.title = (f"Delay at {fmt_num(100 * p['level'])} % — {signal_label(s2)} vs "
               f"{signal_label(s1)} · {p['edge']} edges")
    r.add("delay", float(np.mean(d)), "s", "Mean delay t(S2) − t(S1)", digits=6)
    r.add("delay_std", float(np.std(d)), "s", "Standard deviation")
    r.add("delay_min", float(np.min(d)), "s", "Minimum", digits=6)
    r.add("delay_max", float(np.max(d)), "s", "Maximum", digits=6)
    r.add("n_edges", int(d.size), "", "Edges paired")
    r.tables["edges"] = rows[:50]
    first = rows[0]["t1_s"]
    for key, sig in (("s1", s1), ("s2", s2)):
        base, top = levels[key]
        t = (sig.starttime.timestamp - ref) + sig.times()
        span = 10.0 * max(s1.delta, s2.delta) + abs(float(np.mean(d)))
        keep = np.abs(t - first) <= span
        r.curves[key] = Curve(t[keep] - first, (sig.data[keep] - base) / (top - base),
                              label=sig.name or sig.id, x_label="Time from the first S1 edge",
                              x_unit="s", y_label="Normalized amplitude")
    r.extra["markers"] = [0.0, float(rows[0]["delay_s"])]
    r.extra["level"] = p["level"]
    return r
