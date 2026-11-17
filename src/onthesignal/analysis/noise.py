"""Noise analyses: ``noise``, ``noise_fft``, ``noise_dsp`` (specification §8)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..core.params import Param, resolve_params
from ..core.registry import register
from ..core.result import Curve, Result
from ..core.signal import Signal
from ..core.units import COUNTS, fmt_num
from ..processing.checks import duration_warning, gaps_warning, saturation_warning
from ..processing.params import (
    BAND_PARAMS,
    FULL_SCALE_PARAM,
    TIME_PARAMS,
    UNITS_PARAM,
    WELCH_PARAMS,
    XSCALE_PARAM,
    window_param,
)
from ..processing.spectral import amplitude_spectrum, rms_from_psd, welch_psd
from ._common import (
    add_band_values,
    add_counts,
    apply_band,
    band_title,
    clean_params,
    show_physical,
    signal_label,
    window_signal,
)

NOISE_PARAMS = (*BAND_PARAMS, FULL_SCALE_PARAM, UNITS_PARAM, *TIME_PARAMS)
NOISE_FFT_PARAMS = (
    *NOISE_PARAMS,
    window_param("hann"),
    Param("scale", str, "amplitude", choices=("amplitude", "rms", "asd", "dbfs"),
          help="Spectrum scale: peak amplitude, RMS, amplitude density or dBFS"),
    XSCALE_PARAM,
)
NOISE_DSP_PARAMS = (
    *NOISE_PARAMS,
    window_param("hann"),
    *WELCH_PARAMS,
    Param("scale", str, "psd", choices=("psd", "asd"),
          help="psd: dB re 1 unit²/Hz; asd: amplitude density (unit/√Hz)"),
    Param("cumulative", bool, False, help="Also plot the cumulative RMS versus frequency"),
    XSCALE_PARAM,
)


def dynamic_range(full_scale: float, rms_counts: float) -> float:
    """Dynamic range in dB: ``20 log10((PE / (2 sqrt 2)) / rms)``, both in counts."""
    if rms_counts <= 0:
        return math.inf
    return 20.0 * math.log10(full_scale / (2.0 * math.sqrt(2.0)) / rms_counts)


def _noise(signal: Signal, p: dict, kind: str) -> tuple[Result, Signal, Any]:
    sig = window_signal(signal, p)
    x = sig.data
    mean = float(np.mean(x))
    band = apply_band(x, sig.sampling_rate, p)
    y = band.data
    rms = float(np.std(y))
    pp = float(np.ptp(y))
    full_scale = p["full_scale"]
    dr = dynamic_range(full_scale, rms)

    title = f"Noise — {signal_label(sig)} · {band_title(band)} · {fmt_num(sig.duration)} s"
    r = Result(kind, title=title, signals=[sig.identity()], params=clean_params(p))
    add_counts(r, "mean", mean, "Mean", sig, p, signed=True)
    add_counts(r, "rms", rms, "RMS", sig, p)
    add_counts(r, "pp", pp, "Peak-to-peak", sig, p)
    add_counts(r, "pp_gauss", 6.6 * rms, "Gaussian p-p (6.6 × RMS)", sig, p)
    r.add("dr", dr, "dB", "Dynamic range", digits=5)
    r.add("enob", (dr - 1.76) / 6.02, "bits", "Noise ENOB")
    r.add("full_scale", full_scale, COUNTS, "Full scale (p-p)", digits=8)
    add_band_values(r, band)
    r.add("duration", sig.duration, "s", "Duration analysed", digits=6)
    r.add("npts", int(y.size), "", "Samples analysed")
    checks = (
        saturation_warning(x, full_scale), gaps_warning(sig), duration_warning(sig, p["fmin"])
    )
    for w in checks:
        if w:
            r.warn(w)
    r.extra.update(
        {
            "band": [band.fmin, band.fmax],
            "mains_lines": list(band.removed_lines),
            "mains_width": p["mains_width"],
        }
    )
    return r, sig, band


@register("noise", NOISE_PARAMS, category="noise",
          description="Noise RMS, peak-to-peak, mean and dynamic range in the study band")
def compute_noise(signal: Signal, **params: Any) -> Result:
    """Noise of a record without useful signal: RMS, peak-to-peak, mean, dynamic range.

    The mean (offset) is computed on the raw samples. The record is then detrended and limited
    to the study band (default: low-pass 100 Hz), optionally without the mains lines; RMS
    (standard deviation) and peak-to-peak are computed on this band-limited noise. The dynamic
    range is ``20 log10((PE / (2 sqrt 2)) / rms)`` with PE the full scale peak-to-peak and the
    RMS in counts.

    Examples
    --------
    >>> import numpy as np
    >>> from onthesignal import Signal
    >>> s = Signal(np.random.default_rng(0).normal(0, 100, 100_000), 200.0)
    >>> round(compute_noise(s)["rms"])
    100
    """
    p = resolve_params(NOISE_PARAMS, params, signal, command="noise")
    return _noise(signal, p, "noise")[0]


@register("noise_fft", NOISE_FFT_PARAMS, category="noise",
          description="Amplitude spectrum (FFT) of the noise with the noise results")
def compute_noise_fft(signal: Signal, **params: Any) -> Result:
    """Noise results plus the one-sided amplitude spectrum of the detrended record.

    ``scale`` selects peak amplitude (a sine of amplitude A reads A), RMS amplitude, amplitude
    spectral density (window ENBW corrected) or dBFS.
    """
    p = resolve_params(NOISE_FFT_PARAMS, params, signal, command="noise_fft")
    r, sig, band = _noise(signal, p, "noise_fft")
    from ..processing.band import detrend_data

    xd = detrend_data(sig.data, p["detrend"])
    physical = show_physical(sig, p) and p["scale"] != "dbfs"
    f, a, info = amplitude_spectrum(xd, sig.sampling_rate, p["window"], p["scale"], p["full_scale"])
    if physical:
        a = a * abs(sig.sensitivity)
    unit = sig.unit if physical else COUNTS
    y_unit = {"asd": f"{unit}/√Hz", "dbfs": "dBFS"}.get(p["scale"], unit)
    y_label = {"amplitude": "Amplitude (peak)", "rms": "Amplitude (RMS)",
               "asd": "Amplitude density", "dbfs": "Amplitude"}[p["scale"]]
    keep = f > 0
    r.curves["spectrum"] = Curve(
        f[keep], a[keep], label=sig.name or sig.id, x_label="Frequency", x_unit="Hz",
        y_label=y_label, y_unit=y_unit, xscale=p["xscale"],
        yscale="linear" if p["scale"] == "dbfs" else "log",
    )
    r.add("window", p["window"], "", "Window")
    r.add("df", info["df"], "Hz", "Frequency resolution")
    r.title = r.title.replace("Noise —", "Noise spectrum —", 1)
    return r


@register("noise_dsp", NOISE_DSP_PARAMS, category="noise",
          description="Welch power spectral density of the noise with the noise results")
def compute_noise_dsp(signal: Signal, **params: Any) -> Result:
    """Noise results plus the Welch PSD and the RMS obtained by integrating it over the band."""
    p = resolve_params(NOISE_DSP_PARAMS, params, signal, command="noise_dsp")
    r, sig, band = _noise(signal, p, "noise_dsp")
    from ..processing.band import detrend_data

    xd = detrend_data(sig.data, p["detrend"])
    f, psd, info = welch_psd(
        xd, sig.sampling_rate, p["window"], p["nperseg"], p["seg_duration"], p["overlap"],
        p["average"],
    )
    rms_psd = rms_from_psd(f, psd, band.fmin, band.fmax, band.removed_lines, p["mains_width"])
    add_counts(r, "rms_psd", rms_psd, "RMS from PSD integration", sig, p)
    r.add("nperseg", info["nperseg"], "", "Welch segment (samples)")
    r.add("n_averages", info["n_averages"], "", "Welch averages")
    r.add("df", info["df"], "Hz", "Frequency resolution")

    physical = show_physical(sig, p)
    factor = sig.sensitivity**2 if physical else 1.0
    unit = sig.unit if physical else COUNTS
    keep = f > 0
    if p["scale"] == "psd":
        y = 10.0 * np.log10(np.maximum(psd[keep] * factor, 1e-300))
        curve = Curve(f[keep], y, label=sig.name or sig.id, x_label="Frequency", x_unit="Hz",
                      y_label="PSD", y_unit=f"dB re 1 {unit}²/Hz", xscale=p["xscale"])
    else:
        curve = Curve(f[keep], np.sqrt(psd[keep] * factor), label=sig.name or sig.id,
                      x_label="Frequency", x_unit="Hz", y_label="ASD", y_unit=f"{unit}/√Hz",
                      xscale=p["xscale"], yscale="log")
    r.curves["psd"] = curve
    if p["cumulative"]:
        in_band = (f >= band.fmin) & (f <= band.fmax)
        for line in band.removed_lines:
            in_band &= np.abs(f - line) > p["mains_width"] / 2.0
        cum = np.sqrt(np.cumsum(np.where(in_band, psd, 0.0)) * info["df"] * factor)
        r.curves["cumulative_rms"] = Curve(
            f[keep], cum[keep], label="Cumulative RMS", x_label="Frequency", x_unit="Hz",
            y_label="Cumulative RMS", y_unit=unit, xscale=p["xscale"],
        )
    r.title = r.title.replace("Noise —", "Noise PSD —", 1)
    return r
