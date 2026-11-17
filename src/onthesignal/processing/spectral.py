"""Spectral estimation helpers: windows, amplitude spectra, Welch PSD, smoothing."""

from __future__ import annotations

import numpy as np
import scipy.fft
import scipy.signal as sps

from ..core.errors import ParameterError

#: Half-width (in bins) of the main lobe of common windows.
LOBE_HALF_WIDTH = {
    "boxcar": 1,
    "hann": 2,
    "hamming": 2,
    "blackman": 3,
    "blackmanharris": 4,
    "nuttall": 4,
    "flattop": 5,
}


def make_window(name: str, n: int) -> np.ndarray:
    """Periodic (DFT-even) window of length ``n``."""
    try:
        return sps.get_window(name, n, fftbins=True)
    except ValueError as exc:
        raise ParameterError(f"Unknown window: {name!r}") from exc


def lobe_half_width(name: str) -> int:
    """Main-lobe half-width of a window, in bins (3 for unknown windows)."""
    return LOBE_HALF_WIDTH.get(name, 3)


def amplitude_spectrum(
    x: np.ndarray,
    fs: float,
    window: str = "hann",
    scale: str = "amplitude",
    full_scale: float | None = None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """One-sided spectrum of ``x``.

    Parameters
    ----------
    scale : {"amplitude", "rms", "asd", "dbfs"}
        ``amplitude``: peak amplitude corrected for the window coherent gain (a sine of
        amplitude A reads A); ``rms``: amplitude / sqrt(2); ``asd``: amplitude spectral density
        (unit/sqrt(Hz)), corrected for the window ENBW; ``dbfs``: peak amplitude relative to
        the full-scale peak ``full_scale / 2``.

    Returns
    -------
    f, a, info
        Frequencies, spectrum and a dict (window, n, df, enbw_bins, enbw_hz).
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    w = make_window(window, n)
    spec = scipy.fft.rfft(x * w, workers=-1)
    f = scipy.fft.rfftfreq(n, 1.0 / fs)
    s1, s2 = float(np.sum(w)), float(np.sum(w**2))
    edge = [0] + ([f.size - 1] if n % 2 == 0 else [])
    if scale in ("amplitude", "rms", "dbfs"):
        a = 2.0 * np.abs(spec) / s1
        a[edge] /= 2.0
        if scale == "rms":
            a /= np.sqrt(2.0)
        elif scale == "dbfs":
            if not full_scale:
                raise ParameterError("full_scale is required for dBFS spectra")
            a = 20.0 * np.log10(np.maximum(a, 1e-300) / (full_scale / 2.0))
    elif scale == "asd":
        psd = 2.0 * np.abs(spec) ** 2 / (fs * s2)
        psd[edge] /= 2.0
        a = np.sqrt(psd)
    else:
        raise ParameterError("scale must be 'amplitude', 'rms', 'asd' or 'dbfs'")
    info = {
        "window": window,
        "n": n,
        "df": fs / n,
        "enbw_bins": n * s2 / s1**2,
        "enbw_hz": fs * s2 / s1**2,
    }
    return f, a, info


def default_nperseg(n: int) -> int:
    """Largest power of two not above ``n / 8`` (about 15 averages with 50 % overlap)."""
    if n < 128:
        return n
    return max(16, 1 << int(np.floor(np.log2(n / 8.0))))


def welch_psd(
    x: np.ndarray,
    fs: float,
    window: str = "hann",
    nperseg: int | None = None,
    seg_duration: float | None = None,
    overlap: float = 0.5,
    average: str = "mean",
    detrend: str | bool = "constant",
) -> tuple[np.ndarray, np.ndarray, dict]:
    """One-sided Welch power spectral density (unit²/Hz)."""
    x = np.asarray(x, dtype=np.float64)
    if seg_duration:
        nperseg = int(round(seg_duration * fs))
    nperseg = int(min(nperseg or default_nperseg(x.size), x.size))
    noverlap = int(nperseg * overlap)
    if noverlap >= nperseg:
        noverlap = nperseg - 1
    f, p = sps.welch(
        x, fs=fs, window=window, nperseg=nperseg, noverlap=noverlap,
        detrend=detrend if detrend not in (None, "none") else False,
        scaling="density", average=average,
    )
    n_avg = 1 + (x.size - nperseg) // (nperseg - noverlap)
    info = {
        "window": window,
        "nperseg": nperseg,
        "noverlap": noverlap,
        "n_averages": int(n_avg),
        "df": fs / nperseg,
        "average": average,
    }
    return f, p, info


def rms_from_psd(
    f: np.ndarray,
    p: np.ndarray,
    fmin: float,
    fmax: float,
    exclude: list[float] | None = None,
    width: float = 0.0,
) -> float:
    """RMS value obtained by integrating a one-sided PSD over ``[fmin, fmax]``.

    Lines listed in ``exclude`` are skipped over ``width`` Hz each. The rectangle rule is used
    on the uniform frequency grid, with half weights at DC and Nyquist.
    """
    df = float(f[1] - f[0])
    mask = (f >= fmin - 1e-12) & (f <= fmax + 1e-12)
    for line in exclude or []:
        mask &= np.abs(f - line) > width / 2.0
    weights = np.ones(f.size)
    weights[0] = 0.5
    weights[-1] = 0.5
    return float(np.sqrt(np.sum(p[mask] * weights[mask]) * df))


def octave_smooth(
    f: np.ndarray, p: np.ndarray, fraction: int = 8
) -> tuple[np.ndarray, np.ndarray]:
    """Average a PSD in bands 1/``fraction`` octave wide, centred on log-spaced frequencies.

    Returns the band centre frequencies and the mean PSD (linear power) in each band; empty
    bands are skipped.
    """
    pos = f > 0
    f, p = f[pos], p[pos]
    if f.size == 0:
        return f, p
    n_bands = int(np.floor(np.log2(f[-1] / f[0]) * fraction)) + 1
    centres = f[0] * 2.0 ** (np.arange(n_bands) / fraction)
    half = 2.0 ** (1.0 / (2 * fraction))
    lo = np.searchsorted(f, centres / half, side="left")
    hi = np.searchsorted(f, centres * half, side="right")
    csum = np.concatenate([[0.0], np.cumsum(p)])
    count = hi - lo
    ok = count > 0
    mean = (csum[hi[ok]] - csum[lo[ok]]) / count[ok]
    return centres[ok], mean


def interp_peak(a: np.ndarray, k: int) -> tuple[float, float]:
    """Parabolic interpolation of a spectral peak on the log amplitude.

    Returns the fractional bin index and the interpolated amplitude.
    """
    if k <= 0 or k >= a.size - 1:
        return float(k), float(a[k])
    y0, y1, y2 = np.log(np.maximum(a[k - 1 : k + 2], 1e-300))
    denom = y0 - 2 * y1 + y2
    delta = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    delta = float(np.clip(delta, -0.5, 0.5))
    return k + delta, float(np.exp(y1 - 0.25 * (y0 - y2) * delta))


def minmax_envelope(y: np.ndarray, max_points: int = 20000) -> tuple[np.ndarray, np.ndarray]:
    """Decimate a long series for display, keeping each bin's minimum and maximum.

    Returns sample indices and values (interleaved min/max) suitable for a line plot.
    """
    n = y.size
    if n <= max_points:
        return np.arange(n), y
    n_bins = max_points // 2
    edges = np.linspace(0, n, n_bins + 1).astype(int)
    idx = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        if b <= a:
            continue
        seg = y[a:b]
        i_min, i_max = a + int(np.argmin(seg)), a + int(np.argmax(seg))
        idx.extend(sorted((i_min, i_max)))
    idx_arr = np.asarray(idx)
    return idx_arr, y[idx_arr]
