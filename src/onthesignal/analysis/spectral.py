"""Coherence between two signals and spectrogram (specification §12)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.signal as sps

from ..core.params import Param, resolve_params
from ..core.registry import register
from ..core.result import Curve, Result
from ..core.signal import Signal
from ..core.units import COUNTS, fmt_num, pretty_unit
from ..processing.params import TIME_PARAMS, WELCH_PARAMS, XSCALE_PARAM, window_param
from ..processing.spectral import default_nperseg
from ._common import clean_params, signal_label, window_signal

COHERENCE_PARAMS = (
    window_param("hann"),
    *WELCH_PARAMS,
    Param("fmin", float, 0.0, unit="Hz", min=0.0, help="Lower bound for the mean coherence"),
    Param("fmax", float, None, nullable=True, unit="Hz", min=0.0,
          help="Upper bound for the mean coherence (none = Nyquist)"),
    Param("significance", bool, False, help="Draw the zero-coherence significance level"),
    Param("alpha", float, 0.05, min=1e-6, max=0.5, advanced=True,
          help="Risk level of the significance threshold"),
    XSCALE_PARAM,
    *TIME_PARAMS,
)
SPECTROGRAM_PARAMS = (
    window_param("hann"),
    Param("win_duration", float, None, nullable=True, unit="s", min=0.0,
          help="Window duration (default: about 100 time slices)"),
    Param("overlap", float, 0.5, min=0.0, max=0.95, advanced=True, help="Window overlap"),
    Param("fmin", float, 0.0, unit="Hz", min=0.0, help="Lowest frequency shown"),
    Param("fmax", float, None, nullable=True, unit="Hz", min=0.0,
          help="Highest frequency shown (none = Nyquist)"),
    Param("yscale", str, "linear", choices=("linear", "log"), help="Frequency axis scale"),
    Param("vmin", float, None, nullable=True, unit="dB", advanced=True,
          help="Lower color limit (default: 1st percentile)"),
    Param("vmax", float, None, nullable=True, unit="dB", advanced=True,
          help="Upper color limit (default: 99th percentile)"),
    Param("show_signal", bool, True, help="Show the time series above the spectrogram"),
    Param("units", str, "physical", choices=("physical", "counts"), advanced=True,
          help="Display units"),
    *TIME_PARAMS,
)

MAX_SLICES, MAX_BINS = 400, 2000


def aligned(s1: Signal, s2: Signal) -> tuple[Signal, np.ndarray, str]:
    """``s1`` on the common time window and ``s2`` sampled on the same grid."""
    t0 = max(s1.starttime, s2.starttime)
    t1 = min(s1.endtime, s2.endtime)
    from ..core.errors import TimeRangeError

    if t1 < t0:
        raise TimeRangeError("The two signals do not overlap in time")
    a = s1.slice(t0, t1)
    b, note = s2._values_on_grid(a.starttime, a.npts, a.sampling_rate, "linear")
    n = min(a.npts, b.size)
    return a.copy(data=a.data[:n]), b[:n], note


@register("coherence", COHERENCE_PARAMS, n_signals=2, category="spectral",
          description="Magnitude-squared coherence between two signals (Welch)")
def compute_coherence(signal1: Signal, signal2: Signal, **params: Any) -> Result:
    """Magnitude-squared coherence ``|Pxy|² / (Pxx Pyy)`` estimated with Welch's method.

    The second signal is brought onto the time grid of the first over their common window.
    The significance level for zero true coherence is ``1 − α^(1/(n−1))`` with ``n`` the
    number of independent (non-overlapping) segments.
    """
    p = resolve_params(COHERENCE_PARAMS, params, signal1, command="coherence")
    a = window_signal(signal1, p)
    b_sig = window_signal(signal2, p)
    a, b, note = aligned(a, b_sig)
    fs = a.sampling_rate
    if p["seg_duration"]:
        nperseg = int(round(p["seg_duration"] * fs))
    else:
        nperseg = p["nperseg"] or default_nperseg(a.npts)
    nperseg = min(nperseg, a.npts)
    noverlap = min(int(nperseg * p["overlap"]), nperseg - 1)
    f, cxy = sps.coherence(a.data, b, fs=fs, window=p["window"], nperseg=nperseg,
                           noverlap=noverlap, detrend="constant")
    n_avg = 1 + (a.npts - nperseg) // (nperseg - noverlap)
    n_indep = max(a.npts // nperseg, 2)
    fmax = p["fmax"] if p["fmax"] is not None else fs / 2
    band = (f >= p["fmin"]) & (f <= fmax)
    r = Result("coherence", signals=[a.identity(), b_sig.identity()], params=clean_params(p))
    r.title = f"Coherence — {signal_label(a)} / {signal_label(b_sig)} · {fmt_num(a.duration)} s"
    r.add("mean_coherence", float(np.mean(cxy[band])), "", "Mean coherence in the band")
    r.add("band", [p["fmin"], fmax], "Hz", "Band", kind="range")
    r.add("n_averages", int(n_avg), "", "Welch averages")
    r.add("df", fs / nperseg, "Hz", "Frequency resolution")
    if p["significance"]:
        threshold = 1.0 - p["alpha"] ** (1.0 / (n_indep - 1))
        confidence = fmt_num(100 * (1 - p["alpha"]))
        r.add("threshold", threshold, "", f"Significance level ({confidence} %)")
        r.extra["threshold"] = threshold
    if note:
        r.warn(f"{signal2.name or signal2.id}: {note}")
    keep = f > 0
    r.curves["coherence"] = Curve(f[keep], cxy[keep], label="coherence", x_label="Frequency",
                                  x_unit="Hz", y_label="Coherence", xscale=p["xscale"])
    return r


def _block_mean(z: np.ndarray, axis: int, max_n: int) -> tuple[np.ndarray, int]:
    n = z.shape[axis]
    if n <= max_n:
        return z, 1
    k = math.ceil(n / max_n)
    m = n // k
    z = np.take(z, np.arange(m * k), axis=axis)
    shape = list(z.shape)
    shape[axis:axis + 1] = [m, k]
    return z.reshape(shape).mean(axis=axis + 1), k


@register("spectrogram", SPECTROGRAM_PARAMS, category="spectral",
          description="Spectrogram (short-time PSD) of a signal")
def compute_spectrogram(signal: Signal, **params: Any) -> Result:
    """Short-time Fourier PSD in dB re 1 unit²/Hz.

    Default window: Hann of 2^k samples giving about 100 time slices, 50 % overlap. For
    display, slices and frequency bins are averaged in blocks when there are more than 400
    slices or 2000 bins (the effective resolution is reported).
    """
    p = resolve_params(SPECTROGRAM_PARAMS, params, signal, command="spectrogram")
    sig = window_signal(signal, p)
    physical = p["units"] == "physical" and sig.unit != COUNTS
    x = sig.to_physical() if physical else sig.data
    fs = sig.sampling_rate
    if p["win_duration"]:
        nperseg = int(round(p["win_duration"] * fs))
    else:
        nperseg = 1 << max(4, int(math.floor(math.log2(max(sig.npts / 50, 16)))))
    nperseg = min(nperseg, sig.npts)
    noverlap = min(int(nperseg * p["overlap"]), nperseg - 1)
    f, t, sxx = sps.spectrogram(x, fs=fs, window=p["window"], nperseg=nperseg,
                                noverlap=noverlap, detrend="constant", scaling="density")
    fmax = p["fmax"] if p["fmax"] is not None else fs / 2
    keep = (f >= p["fmin"]) & (f <= fmax) & ((f > 0) | (p["yscale"] == "linear"))
    f, sxx = f[keep], sxx[keep]
    sxx, kt = _block_mean(sxx, 1, MAX_SLICES)
    t = t[: kt * sxx.shape[1]].reshape(-1, kt).mean(axis=1) if kt > 1 else t
    sxx, kf = _block_mean(sxx, 0, MAX_BINS)
    f = f[: kf * sxx.shape[0]].reshape(-1, kf).mean(axis=1) if kf > 1 else f
    z = 10.0 * np.log10(np.maximum(sxx, 1e-300)).astype(np.float32)
    vmin = p["vmin"] if p["vmin"] is not None else float(np.percentile(z, 1))
    vmax = p["vmax"] if p["vmax"] is not None else float(np.percentile(z, 99))
    unit = pretty_unit(sig.unit if physical else COUNTS)
    r = Result("spectrogram", signals=[sig.identity()], params=clean_params(p))
    r.title = f"Spectrogram — {signal_label(sig)} · {fmt_num(sig.duration)} s"
    r.add("window_duration", nperseg / fs, "s", "Window duration")
    r.add("df", fs / nperseg * kf, "Hz", "Displayed frequency resolution")
    r.add("dt", (nperseg - noverlap) / fs * kt, "s", "Displayed time step")
    r.add("color_range", [vmin, vmax], "dB", "Color range", kind="range")
    r.extra["image"] = {
        "t": sig.starttime.matplotlib_date + t / 86400.0, "f": f, "z": z,
        "vmin": vmin, "vmax": vmax, "unit": f"dB re 1 {unit}²/Hz", "yscale": p["yscale"],
    }
    if p["show_signal"]:
        from ..processing.spectral import minmax_envelope

        idx, y = minmax_envelope(x, 20000)
        r.curves["signal"] = Curve(sig.times("matplotlib")[idx], y, label=sig.name or sig.id,
                                   x_label="Time (UTC)", y_label="Amplitude", y_unit=unit)
    return r
