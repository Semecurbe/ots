"""Least-squares sine-wave fitting (IEEE Std 1057): 3-parameter, 4-parameter, multi-harmonic.

The normal equations are accumulated block by block, so memory stays bounded for records of
tens of millions of samples. Columns are normalized (Jacobi scaling) before solving, and the
time origin is the centre of the record for numerical conditioning.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.errors import AnalysisError
from ..core.params import Param, resolve_params
from ..core.registry import register
from ..core.result import Curve, Result
from ..core.signal import Signal
from ..processing.spectral import interp_peak, make_window
from ._common import add_counts, clean_params, signal_label, window_signal

_CHUNK = 1 << 20


def centred_times(n: int, fs: float) -> np.ndarray:
    """Sample times in seconds relative to the centre of the record."""
    return (np.arange(n) - (n - 1) / 2.0) / fs


def _lstsq(
    x: np.ndarray, t: np.ndarray, columns: Callable[[np.ndarray], np.ndarray], ncols: int
) -> np.ndarray:
    """Solve ``M c ≈ x`` where ``columns(t_block)`` returns the block of ``M``."""
    gram = np.zeros((ncols, ncols))
    rhs = np.zeros(ncols)
    for i in range(0, x.size, _CHUNK):
        block = columns(t[i : i + _CHUNK])
        gram += block.T @ block
        rhs += block.T @ x[i : i + _CHUNK]
    scale = np.sqrt(np.diag(gram))
    scale[scale == 0] = 1.0
    try:
        sol = np.linalg.solve(gram / np.outer(scale, scale), rhs / scale)
    except np.linalg.LinAlgError as exc:
        raise AnalysisError("Singular least-squares problem (degenerate data?)") from exc
    return sol / scale


def _evaluate(
    t: np.ndarray, columns: Callable[[np.ndarray], np.ndarray], coef: np.ndarray
) -> np.ndarray:
    out = np.empty(t.size)
    for i in range(0, t.size, _CHUNK):
        out[i : i + _CHUNK] = columns(t[i : i + _CHUNK]) @ coef
    return out


def estimate_frequency(x: np.ndarray, fs: float) -> float:
    """Frequency of the main spectral peak (Hann window, parabolic interpolation)."""
    xd = np.asarray(x, dtype=np.float64) - np.mean(x)
    spectrum = np.abs(np.fft.rfft(xd * make_window("hann", xd.size)))
    if spectrum.size < 4:
        raise AnalysisError("Record too short to estimate a frequency")
    k = int(np.argmax(spectrum[2:])) + 2
    k_frac, _ = interp_peak(spectrum, k)
    return k_frac * fs / xd.size


def fit3(x: np.ndarray, t: np.ndarray, omega: float) -> np.ndarray:
    """3-parameter fit at a known angular frequency: returns ``[A0, B0, C0]``."""

    def cols(tb: np.ndarray) -> np.ndarray:
        return np.column_stack([np.cos(omega * tb), np.sin(omega * tb), np.ones(tb.size)])

    return _lstsq(x, t, cols, 3)


@dataclass
class SineFit:
    """Result of a 4-parameter sine fit ``y = A cos(ω t + φ) + C`` (t from the record centre)."""

    frequency: float
    amplitude: float
    phase: float
    offset: float
    a0: float
    b0: float
    iterations: int
    converged: bool
    t: np.ndarray
    fitted: np.ndarray
    residual: np.ndarray

    @property
    def omega(self) -> float:
        return 2.0 * math.pi * self.frequency

    @property
    def rms_residual(self) -> float:
        return float(np.sqrt(np.mean(self.residual**2)))


def fit4(
    x: np.ndarray,
    fs: float,
    f0: float | None = None,
    tol: float = 1e-9,
    maxiter: int = 100,
) -> SineFit:
    """4-parameter sine fit (IEEE Std 1057).

    Parameters
    ----------
    x : ndarray
        Samples.
    fs : float
        Sampling rate in Hz.
    f0 : float, optional
        Initial frequency; estimated from the spectrum peak when omitted.
    tol : float
        Convergence threshold on the relative frequency update ``|Δω/ω|``.
    maxiter : int
        Maximum number of Gauss-Newton iterations.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < 8:
        raise AnalysisError("At least 8 samples are needed for a sine fit")
    t = centred_times(x.size, fs)
    omega = 2.0 * math.pi * (f0 if f0 else estimate_frequency(x, fs))
    a0, b0, c0 = fit3(x, t, omega)
    converged = False
    iterations = 0
    for iterations in range(1, maxiter + 1):  # noqa: B007 (value used after the loop)
        a_, b_, w_ = a0, b0, omega

        def cols(tb: np.ndarray, a_=a_, b_=b_, w_=w_) -> np.ndarray:
            c, s = np.cos(w_ * tb), np.sin(w_ * tb)
            return np.column_stack([c, s, np.ones(tb.size), -a_ * tb * s + b_ * tb * c])

        a0, b0, c0, d_omega = _lstsq(x, t, cols, 4)
        omega += d_omega
        if omega <= 0 or omega >= math.pi * fs:
            raise AnalysisError("The sine fit diverged (frequency outside 0–Nyquist)")
        if abs(d_omega / omega) < tol:
            converged = True
            break
    a0, b0, c0 = fit3(x, t, omega)
    fitted = a0 * np.cos(omega * t) + b0 * np.sin(omega * t) + c0
    return SineFit(
        frequency=omega / (2.0 * math.pi),
        amplitude=float(math.hypot(a0, b0)),
        phase=float(math.atan2(-b0, a0)),
        offset=float(c0),
        a0=float(a0),
        b0=float(b0),
        iterations=iterations,
        converged=converged,
        t=t,
        fitted=fitted,
        residual=x - fitted,
    )


@dataclass
class HarmonicFit:
    """Multi-harmonic fit at fixed frequencies ``k * f0``."""

    orders: list[int]
    amplitudes: dict[int, float]
    phases: dict[int, float]
    offset: float
    residual: np.ndarray


def fit_harmonics(x: np.ndarray, t: np.ndarray, f0: float, orders: list[int]) -> HarmonicFit:
    """Linear least-squares fit of the harmonics ``orders`` of ``f0`` (``1`` = fundamental)."""
    x = np.asarray(x, dtype=np.float64)
    w = 2.0 * math.pi * f0
    orders = sorted(set(orders))

    def cols(tb: np.ndarray) -> np.ndarray:
        blocks = [np.ones(tb.size)]
        for k in orders:
            blocks += [np.cos(k * w * tb), np.sin(k * w * tb)]
        return np.column_stack(blocks)

    coef = _lstsq(x, t, cols, 1 + 2 * len(orders))
    residual = x - _evaluate(t, cols, coef)
    amplitudes, phases = {}, {}
    for i, k in enumerate(orders):
        a, b = coef[1 + 2 * i], coef[2 + 2 * i]
        amplitudes[k] = float(math.hypot(a, b))
        phases[k] = float(math.atan2(-b, a))
    return HarmonicFit(orders, amplitudes, phases, float(coef[0]), residual)


SINEFIT_PARAMS = (
    Param("f0", float, None, nullable=True, unit="Hz", min=0.0,
          help="Approximate sine frequency (none = automatic)"),
    Param("tol", float, 1e-9, min=0.0, advanced=True, help="Convergence threshold on |Δω/ω|"),
    Param("maxiter", int, 100, min=1, advanced=True, help="Maximum number of iterations"),
    Param("units", str, "physical", choices=("physical", "counts"), advanced=True,
          help="Display units"),
    Param("t_start", object, None, advanced=True, help="Start of the analysed window"),
    Param("t_end", object, None, advanced=True, help="End of the analysed window"),
)


@register("sinefit", SINEFIT_PARAMS, category="sine",
          description="4-parameter sine fit (IEEE 1057): amplitude, phase, offset, frequency")
def compute_sinefit(signal: Signal, **params: Any) -> Result:
    """4-parameter sine fit of the record: amplitude, phase, offset, frequency and residual."""
    p = resolve_params(SINEFIT_PARAMS, params, signal, command="sinefit")
    sig = window_signal(signal, p)
    fit = fit4(sig.data, sig.sampling_rate, p["f0"], p["tol"], p["maxiter"])
    r = Result("sinefit", title=f"Sine fit — {signal_label(sig)}", signals=[sig.identity()],
               params=clean_params(p))
    r.add("frequency", fit.frequency, "Hz", "Frequency", digits=10)
    add_counts(r, "amplitude", fit.amplitude, "Amplitude (peak)", sig, p, digits=6)
    r.add("phase", math.degrees(fit.phase), "°", "Phase at the record centre", digits=6)
    add_counts(r, "offset", fit.offset, "Offset", sig, p, signed=True)
    add_counts(r, "rms_residual", fit.rms_residual, "Residual RMS", sig, p)
    r.add("periods", fit.frequency * sig.duration, "", "Periods in the record")
    r.add("iterations", fit.iterations, "", "Iterations")
    r.add("converged", fit.converged, "", "Converged")
    n = min(sig.npts, int(5 * sig.sampling_rate / fit.frequency) + 1)
    t = sig.times()[:n]
    r.curves["signal"] = Curve(t, sig.data[:n], label="signal", x_label="Time", x_unit="s",
                               y_label="Amplitude", y_unit="counts")
    r.curves["fit"] = Curve(t, fit.fitted[:n], label="fit", x_label="Time", x_unit="s",
                            y_label="Amplitude", y_unit="counts")
    if not fit.converged:
        r.warn(f"The fit did not converge in {fit.iterations} iterations")
    if fit.frequency * sig.duration < 5:
        r.warn("The record holds fewer than 5 periods of the sine")
    return r
