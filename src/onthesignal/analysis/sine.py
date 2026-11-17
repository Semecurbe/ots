"""Sine-wave analyses: SINAD / ENOB, SFDR, THD, SNR and the dynamic analysis (spec §10)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.fft

from ..core.params import Param, resolve_params
from ..core.registry import register
from ..core.result import Curve, Result
from ..core.signal import Signal
from ..core.units import COUNTS, fmt_num
from ..processing.band import BandResult, mains_lines
from ..processing.checks import gaps_warning, saturation_warning
from ..processing.params import (
    BAND_PARAMS,
    FULL_SCALE_PARAM,
    TIME_PARAMS,
    UNITS_PARAM,
    window_param,
)
from ..processing.spectral import amplitude_spectrum, lobe_half_width, make_window, minmax_envelope
from ._common import (
    add_band_values,
    add_counts,
    apply_band,
    band_title,
    clean_params,
    signal_label,
    window_signal,
)
from .sinefit import SineFit, fit4, fit_harmonics

FIT_PARAMS = (
    Param("f0", float, None, nullable=True, unit="Hz", min=0.0,
          help="Approximate sine frequency (none = automatic)"),
    Param("tol", float, 1e-9, min=0.0, advanced=True, help="Convergence threshold on |Δω/ω|"),
    Param("maxiter", int, 100, min=1, advanced=True, help="Maximum number of iterations"),
)
SINAD_PARAMS = (*BAND_PARAMS, FULL_SCALE_PARAM, *FIT_PARAMS, UNITS_PARAM, *TIME_PARAMS)
SFDR_EXTRA = (
    window_param("blackmanharris"),
    Param("exclude_f0", float, None, nullable=True, unit="Hz", min=0.0, advanced=True,
          help="Half-width excluded around the fundamental (default: 3 main-lobe half-widths)"),
    Param("emergence", float, 6.0, unit="dB", advanced=True,
          help="Margin above the expected noise maximum for a spur to count as a real line"),
)
THD_EXTRA = (
    Param("n_harmonics", int, 10, min=2, max=100, help="Highest harmonic order (H2 to Hn)"),
)
SFDR_PARAMS = (*SINAD_PARAMS, *SFDR_EXTRA)
THD_PARAMS = (*SINAD_PARAMS, *THD_EXTRA)
DYNAMIC_PARAMS = (
    *SINAD_PARAMS,
    *THD_EXTRA,
    *SFDR_EXTRA,
    Param("noise", object, None, help="Noise record (no signal) used for the dynamic range"),
)


def _db(ratio: float) -> float:
    return 20.0 * math.log10(ratio) if ratio > 0 else -math.inf


# ---------------------------------------------------------------------------------- common
def _fit(signal: Signal, p: dict, kind: str) -> tuple[Signal, SineFit, Result]:
    sig = window_signal(signal, p)
    fit = fit4(sig.data, sig.sampling_rate, p["f0"], p["tol"], p["maxiter"])
    r = Result(kind, signals=[sig.identity()], params=clean_params(p))
    full_scale = p["full_scale"]
    r.add("frequency", fit.frequency, "Hz", "Frequency", digits=10)
    add_counts(r, "amplitude", fit.amplitude, "Amplitude (peak)", sig, p, digits=6)
    r.add("amplitude_dbfs", _db(fit.amplitude / (full_scale / 2.0)), "dBFS", "Amplitude")
    add_counts(r, "offset", fit.offset, "Offset", sig, p, signed=True)
    r.add("periods", fit.frequency * sig.duration, "", "Periods in the record")
    r.add("full_scale", full_scale, COUNTS, "Full scale (p-p)", digits=8)
    if not fit.converged:
        r.warn(f"The sine fit did not converge in {fit.iterations} iterations")
    if fit.frequency * sig.duration < 5:
        r.warn("The record holds fewer than 5 periods of the sine")
    for w in (saturation_warning(sig.data, full_scale), gaps_warning(sig)):
        if w:
            r.warn(w)
    lines = mains_lines(p["mains_freq"], sig.nyquist)
    for k in range(1, 11):
        fk = k * fit.frequency
        if fk > min(p["fmax"], sig.nyquist):
            break
        if any(abs(fk - m) <= p["mains_width"] / 2.0 for m in lines):
            r.warn(
                f"{'The fundamental' if k == 1 else f'Harmonic H{k}'} ({fmt_num(fk)} Hz) "
                "coincides with a mains line: choose another test frequency"
            )
    return sig, fit, r


def _residual_band(residual: np.ndarray, fs: float, p: dict) -> BandResult:
    return apply_band(residual, fs, p, detrend="constant")


def _time_curves(r: Result, sig: Signal, fit: SineFit) -> None:
    n = min(sig.npts, int(4 * sig.sampling_rate / fit.frequency) + 2)
    t = sig.times()
    r.curves["signal"] = Curve(t[:n], sig.data[:n], label="signal", x_label="Time", x_unit="s",
                               y_label="Amplitude", y_unit="counts")
    r.curves["fit"] = Curve(t[:n], fit.fitted[:n], label="4-parameter fit", x_label="Time",
                            x_unit="s", y_label="Amplitude", y_unit="counts")
    idx, res = minmax_envelope(fit.residual)
    r.curves["residual"] = Curve(t[idx], res, label="residual", x_label="Time", x_unit="s",
                                 y_label="Residual", y_unit="counts")


def _spectrum_curve(x: np.ndarray, fs: float, full_scale: float, window: str, label: str) -> Curve:
    f, a, _ = amplitude_spectrum(x - np.mean(x), fs, window, "dbfs", full_scale)
    keep = f > 0
    return Curve(f[keep], a[keep], label=label, x_label="Frequency", x_unit="Hz",
                 y_label="Amplitude", y_unit="dBFS", xscale="linear")


# ---------------------------------------------------------------------------------- parts
def _sinad_part(r: Result, sig: Signal, fit: SineFit, p: dict) -> float:
    band = _residual_band(fit.residual, sig.sampling_rate, p)
    sigma = float(np.std(band.data))
    sinad = _db((fit.amplitude / math.sqrt(2.0)) / sigma) if sigma > 0 else math.inf
    enob = (sinad - 1.76) / 6.02
    enob_fs = (sinad + _db((p["full_scale"] / 2.0) / fit.amplitude) - 1.76) / 6.02
    add_counts(r, "sigma_r", sigma, "Noise + distortion RMS (residual)", sig, p)
    r.add("sinad", sinad, "dB", "SINAD", digits=5)
    r.add("enob", enob, "bits", "ENOB (relative to the sine)")
    r.add("enob_fs", enob_fs, "bits", "ENOB (full scale)")
    r.add("thd_n", -sinad, "dB", "THD+N", digits=5)
    add_band_values(r, band)
    r.extra.update({"band": [band.fmin, band.fmax], "mains_lines": list(band.removed_lines),
                    "mains_width": p["mains_width"]})
    r.title = (f"{r.title or 'SINAD'} — {signal_label(sig)} · f0 {fmt_num(fit.frequency, 6)} Hz · "
               f"{band_title(band)}")
    return sinad


def _sfdr_part(r: Result, sig: Signal, fit: SineFit, p: dict) -> None:
    fs = sig.sampling_rate
    res = fit.residual - np.mean(fit.residual)
    n = res.size
    w = make_window(p["window"], n)
    power = np.abs(scipy.fft.rfft(res * w, workers=-1)) ** 2
    f = scipy.fft.rfftfreq(n, 1.0 / fs)
    df = fs / n
    half = lobe_half_width(p["window"])
    excl = p["exclude_f0"] if p["exclude_f0"] is not None else 3 * half * df
    fmax = min(p["fmax"], sig.nyquist)
    cand = (f >= max(p["fmin"], (half + 1) * df)) & (f <= fmax)
    cand &= np.abs(f - fit.frequency) > excl
    lines = mains_lines(p["mains_freq"], fmax) if p["remove_mains"] else []
    for m in lines:
        cand &= np.abs(f - m) > p["mains_width"] / 2.0
    if not np.any(cand):
        r.warn("No frequency left to search for spurs in the study band")
        return
    k = int(np.flatnonzero(cand)[np.argmax(power[cand])])
    lo, hi = max(0, k - half), min(power.size, k + half + 1)
    a_spur = 2.0 * math.sqrt(float(np.sum(power[lo:hi])) / (n * float(np.sum(w**2))))
    f_spur = float(f[k])
    peak_amp = 2.0 * np.sqrt(power) / float(np.sum(w))
    floor = float(np.median(peak_amp[cand]))
    emergence = _db(a_spur / floor) if floor > 0 else math.inf
    # Expected max/median ratio of M exponentially distributed noise bins (power):
    # (ln M + γ) / ln 2. A real line must exceed it by the "emergence" margin.
    n_cand = int(np.count_nonzero(cand))
    noise_max = 10.0 * math.log10((math.log(max(n_cand, 2)) + 0.5772) / math.log(2.0))
    threshold = noise_max + p["emergence"]

    nature = "other"
    tol = max(p["mains_width"] / 2.0, (half + 1) * df)
    order = round(f_spur / fit.frequency)
    if order >= 2 and abs(f_spur - order * fit.frequency) <= tol:
        nature = f"harmonic H{order}"
    elif any(abs(f_spur - m) <= tol for m in mains_lines(p["mains_freq"], sig.nyquist)):
        nature = "mains"
    sfdr_dbc = _db(fit.amplitude / a_spur)
    r.add("sfdr_dbc", sfdr_dbc, "dBc", "SFDR", digits=5)
    r.add("sfdr_dbfs", _db((p["full_scale"] / 2.0) / a_spur), "dBFS", "SFDR (full scale)", digits=5)
    r.add("spur_frequency", f_spur, "Hz", "Largest spur frequency", digits=6)
    add_counts(r, "spur_amplitude", a_spur, "Largest spur amplitude (peak)", sig, p)
    r.add("spur_nature", nature, "", "Largest spur nature")
    r.add("spur_emergence", emergence, "dB", "Spur emergence above the median noise floor")
    r.add("noise_limited", emergence < threshold, "", "SFDR limited by the noise floor")
    if emergence < threshold:
        r.warn(
            f"The largest spur emerges by only {fmt_num(emergence, 3)} dB above the median noise "
            f"floor (a noise maximum is expected around {fmt_num(noise_max, 3)} dB): the SFDR "
            "is limited by the noise floor, which depends on N and the window"
        )
    r.curves["residual_spectrum"] = _spectrum_curve(res, fs, p["full_scale"], p["window"],
                                                    "residual spectrum")
    r.extra.update({"spur": [f_spur, _db(a_spur / (p["full_scale"] / 2.0))],
                    "fundamental": [fit.frequency, _db(fit.amplitude / (p["full_scale"] / 2.0))]})


def _harmonic_orders(fit: SineFit, sig: Signal, p: dict) -> tuple[list[int], list[dict]]:
    kept, excluded = [], []
    fmax = min(p["fmax"], sig.nyquist)
    lines = mains_lines(p["mains_freq"], sig.nyquist)
    for k in range(2, p["n_harmonics"] + 1):
        fk = k * fit.frequency
        if fk < p["fmin"] or fk > fmax or fk >= sig.nyquist:
            continue
        if p["remove_mains"] and any(abs(fk - m) <= p["mains_width"] / 2.0 for m in lines):
            excluded.append({"order": k, "frequency": fk, "reason": "coincides with a mains line"})
            continue
        kept.append(k)
    return kept, excluded


def _thd_part(r: Result, sig: Signal, fit: SineFit, p: dict) -> tuple[list[int], Any]:
    orders, excluded = _harmonic_orders(fit, sig, p)
    hfit = fit_harmonics(sig.data, fit.t, fit.frequency, [1, *orders])
    a1 = hfit.amplitudes[1]
    total = math.sqrt(sum(hfit.amplitudes[k] ** 2 for k in orders))
    thd = total / a1 if a1 > 0 else math.nan
    rows = [
        {
            "order": k,
            "frequency": k * fit.frequency,
            "amplitude": hfit.amplitudes[k],
            "dBc": _db(hfit.amplitudes[k] / a1),
        }
        for k in orders
    ]
    r.add("thd_db", _db(thd) if thd > 0 else -math.inf, "dBc", "THD", digits=5)
    r.add("thd_pct", 100.0 * thd, "%", "THD", digits=4)
    r.add("n_harmonics_used", len(orders), "", "Harmonics used")
    r.tables["harmonics"] = rows
    if excluded:
        r.tables["excluded_harmonics"] = excluded
        r.warn(f"{len(excluded)} harmonic(s) excluded because they coincide with mains lines")
    if not orders:
        r.warn("No harmonic of the fundamental lies in the study band")
    r.extra["harmonics"] = [[row["frequency"], row["dBc"]] for row in rows]
    return orders, hfit


# ---------------------------------------------------------------------------------- commands
@register("sinad", SINAD_PARAMS, category="sine", aliases=("SINAD",),
          description="SINAD and ENOB from the residual of a 4-parameter sine fit")
def compute_sinad(signal: Signal, **params: Any) -> Result:
    """SINAD and ENOB.

    A 4-parameter sine fit (IEEE Std 1057) gives the amplitude A; the residual (noise and
    distortion) is limited to the study band (default 0–100 Hz), optionally without the mains
    lines, and its RMS σ is computed. ``SINAD = 20 log10((A/√2)/σ)``,
    ``ENOB = (SINAD − 1.76)/6.02``; ``ENOB_fs`` refers the SINAD to the full scale.
    """
    p = resolve_params(SINAD_PARAMS, params, signal, command="sinad")
    sig, fit, r = _fit(signal, p, "sinad")
    r.title = "SINAD"
    _sinad_part(r, sig, fit, p)
    _time_curves(r, sig, fit)
    r.curves["residual_spectrum"] = _spectrum_curve(fit.residual, sig.sampling_rate,
                                                    p["full_scale"], "blackmanharris",
                                                    "residual spectrum")
    return r


@register("sfdr", SFDR_PARAMS, category="sine", aliases=("SFDR",),
          description="Spurious-free dynamic range from the spectrum of the fit residual")
def compute_sfdr(signal: Signal, **params: Any) -> Result:
    """SFDR: ratio between the fundamental and the largest spur in the study band.

    The fundamental is removed by a 4-parameter fit; the largest line of the windowed residual
    spectrum (outside DC, the fundamental zone and, optionally, the mains lines) is the spur.
    Its amplitude is estimated by summing the power over its main lobe.
    """
    p = resolve_params(SFDR_PARAMS, params, signal, command="sfdr")
    sig, fit, r = _fit(signal, p, "sfdr")
    _sfdr_part(r, sig, fit, p)
    r.curves["spectrum"] = _spectrum_curve(sig.data, sig.sampling_rate, p["full_scale"],
                                           p["window"], "signal spectrum")
    r.title = (f"SFDR — {signal_label(sig)} · f0 {fmt_num(fit.frequency, 6)} Hz · band "
               f"{fmt_num(p['fmin'])}–{fmt_num(min(p['fmax'], sig.nyquist))} Hz")
    r.extra["band"] = [p["fmin"], min(p["fmax"], sig.nyquist)]
    return r


@register("thd", THD_PARAMS, category="sine", aliases=("THD",),
          description="Total harmonic distortion (multi-harmonic least-squares fit)")
def compute_thd(signal: Signal, **params: Any) -> Result:
    """THD = sqrt(sum of A_k², k = 2..n) / A_1, harmonics fitted by linear least squares."""
    p = resolve_params(THD_PARAMS, params, signal, command="thd")
    sig, fit, r = _fit(signal, p, "thd")
    _thd_part(r, sig, fit, p)
    r.curves["spectrum"] = _spectrum_curve(sig.data, sig.sampling_rate, p["full_scale"],
                                           "blackmanharris", "signal spectrum")
    r.title = (f"THD — {signal_label(sig)} · f0 {fmt_num(fit.frequency, 6)} Hz · "
               f"H2–H{p['n_harmonics']}")
    r.extra["band"] = [p["fmin"], min(p["fmax"], sig.nyquist)]
    return r


@register("dynamic", (*DYNAMIC_PARAMS, Param("report", bool, False,
                                             help="Generate a Quarto report")),
          category="sine", signal_params=("noise",),
          description="SINAD, ENOB, SFDR, THD and SNR from a single sine fit")
def compute_dynamic(signal: Signal, **params: Any) -> Result:
    """Dynamic analysis: SINAD, ENOB, SFDR, THD and SNR computed from one sine fit.

    ``SNR`` uses the residual after removing the fundamental and its harmonics. A consistency
    check compares the measured SINAD with the value predicted from SNR and THD. When a noise
    record is given (``noise=S_noise``), its dynamic range is added to the summary.
    """
    params = {k: v for k, v in params.items() if k != "report"}
    p = resolve_params(DYNAMIC_PARAMS, params, signal, command="dynamic")
    sig, fit, r = _fit(signal, p, "dynamic")
    r.title = "Dynamic analysis"
    sinad = _sinad_part(r, sig, fit, p)
    orders, hfit = _thd_part(r, sig, fit, p)
    _sfdr_part(r, sig, fit, p)

    band = _residual_band(hfit.residual, sig.sampling_rate, p)
    sigma_n = float(np.std(band.data))
    snr = _db((hfit.amplitudes[1] / math.sqrt(2.0)) / sigma_n) if sigma_n > 0 else math.inf
    add_counts(r, "sigma_noise", sigma_n, "Noise RMS (harmonics removed)", sig, p)
    r.add("snr", snr, "dB", "SNR", digits=5)
    thd_db = r["thd_db"]
    predicted = -10.0 * math.log10(10 ** (-snr / 10.0) + 10 ** (thd_db / 10.0))
    r.add("sinad_check", sinad - predicted, "dB", "SINAD − SINAD(SNR, THD)", digits=3)
    if abs(sinad - predicted) > 0.5:
        r.warn("Measured SINAD and SINAD predicted from SNR and THD differ by more than 0.5 dB")

    noise_sig = p.get("noise")
    if noise_sig is not None:
        from .noise import compute_noise

        band_keys = [q.name for q in BAND_PARAMS] + ["full_scale"]
        nres = compute_noise(noise_sig, **{k: p[k] for k in band_keys})
        r.add("noise_rms", nres["rms"], COUNTS, f"Noise RMS ({noise_sig.name or noise_sig.id})")
        r.add("dr", nres["dr"], "dB", "Dynamic range (noise record)", digits=5)
        for w in nres.warnings:
            r.warn(f"Noise record: {w}")
        r.signals.append(noise_sig.identity())

    _time_curves(r, sig, fit)
    r.curves["spectrum"] = _spectrum_curve(sig.data, sig.sampling_rate, p["full_scale"],
                                           p["window"], "signal spectrum")
    r.extra["band"] = [p["fmin"], min(p["fmax"], sig.nyquist)]
    return r
