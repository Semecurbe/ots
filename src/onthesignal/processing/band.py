"""Study band limitation and mains removal (specification §7.2 and §7.3).

Two methods are available:

* ``fft`` (default): ideal rectangular mask applied to the real FFT of the whole record. The
  noise-equivalent bandwidth is exactly the kept band, the phase is zero and the result is
  consistent with the integration of the PSD.
* ``iir``: Butterworth filter applied forward-backward (``sosfiltfilt``) plus notch filters.
  The effective noise bandwidth of the zero-phase filter is computed and reported, and the
  filter transients are trimmed at both ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.fft
import scipy.signal as sps

from ..core.errors import ParameterError
from ..core.units import fmt_num


@dataclass
class BandResult:
    """Band-limited data and the effective band characteristics."""

    data: np.ndarray
    fmin: float
    fmax: float
    method: str
    enbw: float
    removed_lines: list[float] = field(default_factory=list)
    removed_width: float = 0.0
    trim: int = 0
    warnings: list[str] = field(default_factory=list)


def detrend_data(x: np.ndarray, kind: str | None) -> np.ndarray:
    """Remove the mean (``constant``), a line (``linear``) or nothing (``none``/``None``)."""
    x = np.asarray(x, dtype=np.float64)
    if kind in (None, "none"):
        return x.copy()
    if kind not in ("constant", "linear"):
        raise ParameterError(f"Unknown detrend kind: {kind!r}")
    return sps.detrend(x, type=kind)


def mains_lines(
    mains_freq: float, fmax: float, n_harmonics: int | None = None, fmin: float = 0.0
) -> list[float]:
    """Mains line frequencies ``k * mains_freq`` within ``[fmin, fmax]``."""
    if mains_freq <= 0:
        raise ParameterError("mains_freq must be positive")
    lines = []
    k = 1
    while k * mains_freq <= fmax + 1e-9:
        f = k * mains_freq
        if f >= fmin - 1e-9:
            lines.append(f)
        if n_harmonics is not None and k >= n_harmonics:
            break
        k += 1
    return lines


def _check_band(fs: float, fmin: float, fmax: float | None) -> tuple[float, float, list[str]]:
    nyq = fs / 2.0
    notes = []
    if fmax is None:
        fmax_eff = nyq
    elif fmax >= nyq:
        fmax_eff = nyq
        notes.append(
            f"fmax = {fmt_num(fmax)} Hz is not below Nyquist ({fmt_num(nyq)} Hz): no low-pass "
            "applied, the band is limited by the sampling"
        )
    else:
        fmax_eff = float(fmax)
    if fmin < 0 or fmin >= fmax_eff:
        raise ParameterError(f"Invalid study band: fmin = {fmin} Hz, fmax = {fmax_eff} Hz")
    return float(fmin), fmax_eff, notes


def band_limit(
    x: np.ndarray,
    fs: float,
    fmin: float = 0.0,
    fmax: float | None = None,
    remove_mains: bool = False,
    mains_freq: float = 50.0,
    mains_width: float = 1.0,
    mains_harmonics: int | None = None,
    method: str = "fft",
    order: int = 4,
) -> BandResult:
    """Limit ``x`` to the band ``[fmin, fmax]`` and optionally remove the mains lines.

    Parameters
    ----------
    x : ndarray
        Samples (already detrended if needed).
    fs : float
        Sampling rate in Hz.
    fmin, fmax : float
        Study band in Hz; ``fmax`` at or above Nyquist means "no low-pass".
    remove_mains : bool
        Remove ``k * mains_freq`` lines over ``mains_width`` Hz each.
    method : {"fft", "iir"}
        Ideal FFT mask (default) or zero-phase Butterworth with notches.
    order : int
        Butterworth order for the ``iir`` method.

    Returns
    -------
    BandResult
        Filtered data, effective band, noise-equivalent bandwidth (ENBW), removed lines.
    """
    x = np.asarray(x, dtype=np.float64)
    fmin, fmax_eff, notes = _check_band(fs, fmin, fmax)
    lines = mains_lines(mains_freq, fmax_eff, mains_harmonics, fmin) if remove_mains else []
    if method == "fft":
        out = _band_fft(x, fs, fmin, fmax_eff, lines, mains_width)
    elif method == "iir":
        out = _band_iir(x, fs, fmin, fmax_eff, lines, mains_width, order)
    else:
        raise ParameterError("filter_method must be 'fft' or 'iir'")
    out.warnings = notes + out.warnings
    return out


def _band_fft(
    x: np.ndarray, fs: float, fmin: float, fmax: float, lines: list[float], width: float
) -> BandResult:
    n = x.size
    spec = scipy.fft.rfft(x, workers=-1)
    f = scipy.fft.rfftfreq(n, 1.0 / fs)
    in_band = (f >= fmin - 1e-12) & (f <= fmax + 1e-12)
    keep = in_band.copy()
    for line in lines:
        keep &= np.abs(f - line) > width / 2.0
    spec[~keep] = 0.0
    y = scipy.fft.irfft(spec, n=n, workers=-1)
    weights = np.ones(f.size)
    weights[0] = 0.5
    if n % 2 == 0:
        weights[-1] = 0.5
    df = fs / n
    enbw = df * float(np.sum(weights[keep]))
    removed = df * float(np.sum(weights[in_band & ~keep]))
    return BandResult(y, fmin, fmax, "fft", enbw, list(lines), removed)


def _band_iir(
    x: np.ndarray,
    fs: float,
    fmin: float,
    fmax: float,
    lines: list[float],
    width: float,
    order: int,
) -> BandResult:
    nyq = fs / 2.0
    lowpass = fmax < nyq
    highpass = fmin > 0
    sections = []
    if lowpass and highpass:
        sections.append(sps.butter(order, [fmin, fmax], btype="bandpass", fs=fs, output="sos"))
    elif lowpass:
        sections.append(sps.butter(order, fmax, btype="lowpass", fs=fs, output="sos"))
    elif highpass:
        sections.append(sps.butter(order, fmin, btype="highpass", fs=fs, output="sos"))
    kept_lines = []
    for line in lines:
        if 0 < line < nyq and width > 0:
            b, a = sps.iirnotch(line, Q=line / width, fs=fs)
            sections.append(sps.tf2sos(b, a))
            kept_lines.append(line)
    if not sections:
        return BandResult(x.copy(), fmin, fmax, "iir", nyq)
    sos = np.vstack(sections)

    # Effective noise bandwidth of the zero-phase filter: power gain |H|^4.
    freqs, h = sps.sosfreqz(sos, worN=1 << 16, fs=fs)
    enbw = float(np.trapezoid(np.abs(h) ** 4, freqs))
    removed = 0.0
    if kept_lines:
        if lowpass or highpass:
            _, hb = sps.sosfreqz(sections[0], worN=freqs, fs=fs)
            removed = float(np.trapezoid(np.abs(hb) ** 4, freqs)) - enbw
        else:
            removed = nyq - enbw

    # Transient duration from the impulse response (99.9 % of its energy).
    scales = ([fmin] if highpass else []) + ([fmax] if lowpass else [])
    scales += [width] if kept_lines else []
    length = int(min(x.size, max(1024, 50 * fs / min(scales))))
    impulse = np.zeros(length)
    impulse[0] = 1.0
    response = sps.sosfilt(sos, impulse)
    energy = np.cumsum(response**2)
    trim = int(np.searchsorted(energy, 0.999 * energy[-1])) + 1
    trim = min(trim, int(0.1 * x.size))
    if 2 * trim >= x.size:
        raise ParameterError("Record too short for the requested IIR filters")
    y = sps.sosfiltfilt(sos, x)
    if trim > 0:
        y = y[trim : x.size - trim]
    notes = []
    if trim > 0:
        notes.append(f"IIR transients: {trim} samples removed at each end")
    return BandResult(y, fmin, fmax, "iir", enbw, kept_lines, removed, trim, notes)
