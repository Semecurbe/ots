"""Synthetic test signals: a sine and random noise digitized by an ideal N-bit converter.

Digitizer model
---------------
The full scale is ``2**bits`` counts peak-to-peak; the codes run from ``-2**(bits-1)`` to
``2**(bits-1) - 1`` and one count is one LSB. Quantization rounds to the nearest code, which
adds a uniform quantization noise of ``1/√12`` count RMS. Values beyond the code range are
clipped, with a warning. The signals are in counts (``unit="counts"``) and carry
``full_scale = 2**bits``, so the analyses use the right full scale without any option.

Every random draw comes from a seeded generator; the seed is recorded in
``Signal.metadata["seed"]`` so that a signal can be regenerated identically.

The session-aware versions :func:`onthesignal.make_sine` and :func:`onthesignal.make_noise`
also register the signal in the current session (``S1``, ``S2``...).
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from typing import Any

import numpy as np
import scipy.fft

from .core.errors import OnTheSignalWarning, ParameterError
from .core.params import Param, resolve_params
from .core.signal import Signal

_COMMON = (
    Param("bits", int, 24, min=2, max=32,
          help="Number of encoding bits (full scale = 2**bits counts p-p)"),
    Param("fs", float, 1000.0, unit="Hz", min=0.0, help="Sampling rate"),
    Param("duration", float, 60.0, unit="s", min=0.0, help="Duration"),
)
_EXTRA = (
    Param("offset", float, 0.0, unit="counts", advanced=True, help="DC offset"),
    Param("mains_dbfs", float, None, nullable=True, unit="dBFS", advanced=True,
          help="Level of an added mains line (none = no mains line)"),
    Param("mains_freq", float, 50.0, unit="Hz", min=0.0, advanced=True, help="Mains frequency"),
    Param("quantize", bool, True, advanced=True,
          help="Round to integer counts (ideal digitizer); false keeps exact values"),
    Param("seed", int, None, nullable=True, min=0, advanced=True,
          help="Random seed (none = new seed, recorded in the metadata)"),
    Param("starttime", object, None, advanced=True,
          help="Time of the first sample (default 1970-01-01)"),
)

#: Parameters of :func:`make_sine` (console form, AI tool schema, documentation).
SINE_PARAMS = (
    Param("frequency", float, 7.3, unit="Hz", min=0.0, help="Sine frequency"),
    Param("ratio", float, 0.9, min=0.0,
          help="Amplitude as a fraction of full scale (1 = full scale = 0 dBFS)"),
    *_COMMON,
    Param("noise_rms", float, 0.0, unit="counts", min=0.0,
          help="Added Gaussian noise RMS (the quantization noise comes on top)"),
    Param("dbfs", float, None, nullable=True, unit="dBFS", advanced=True,
          help="Amplitude in dBFS; replaces ratio when given"),
    Param("phase", float, 0.0, unit="rad", advanced=True, help="Phase at the first sample"),
    Param("harmonics", object, None, advanced=True,
          help="Harmonic levels in dBc, e.g. 2:-100,3:-110"),
    *_EXTRA,
)

#: Parameters of :func:`make_noise`.
NOISE_PARAMS = (
    Param("rms", float, 1.0, unit="counts", min=0.0, help="Noise RMS before quantization"),
    Param("color", str, "white", choices=("white", "pink", "brown"),
          help="Spectrum shape: white (flat), pink (1/f power), brown (1/f² power)"),
    *_COMMON,
    *_EXTRA,
)


def make_sine(
    frequency: float = 7.3,
    ratio: float = 0.9,
    bits: int = 24,
    fs: float = 1000.0,
    duration: float = 60.0,
    noise_rms: float = 0.0,
    *,
    dbfs: float | None = None,
    phase: float = 0.0,
    harmonics: Mapping[int, float] | str | None = None,
    offset: float = 0.0,
    mains_dbfs: float | None = None,
    mains_freq: float = 50.0,
    quantize: bool = True,
    seed: int | None = None,
    starttime: Any = None,
) -> Signal:
    """Sine wave digitized by an ideal ``bits``-bit converter.

    The amplitude is ``ratio`` times the half full scale: ``A = ratio * 2**(bits-1)`` counts
    (peak), i.e. ``20*log10(ratio)`` dBFS. Without added noise, the only noise is the
    quantization noise, so a full-band SINAD of ``6.02*bits + 1.76 + 20*log10(ratio)`` dB is
    expected (``ENOB_fs = bits``).

    Parameters
    ----------
    frequency : float
        Sine frequency in Hz (below Nyquist). Avoid sub-multiples of the mains frequency and
        of the sampling rate (default 7.3 Hz).
    ratio : float
        Amplitude as a fraction of full scale: peak-to-peak amplitude / full scale (1 = full
        scale = 0 dBFS; 0.9 = −0.92 dBFS). Above 1 the sine is clipped.
    bits : int
        Number of encoding bits; the full scale is ``2**bits`` counts peak-to-peak.
    fs : float
        Sampling rate in Hz.
    duration : float
        Duration in seconds.
    noise_rms : float
        RMS of an added Gaussian white noise, in counts, before quantization.
    dbfs : float, optional
        Amplitude in dBFS; replaces ``ratio`` when given (``ratio = 10**(dbfs/20)``).
    phase : float
        Phase of the sine at the first sample, in radians.
    harmonics : dict or str, optional
        Harmonic levels in dBc (relative to the fundamental): ``{2: -100, 3: -110}`` or
        ``"2:-100,3:-110"``. Harmonics at or above Nyquist are skipped with a warning.
    offset : float
        DC offset in counts.
    mains_dbfs : float, optional
        Level in dBFS of an added sine at ``mains_freq`` (mains interference).
    mains_freq : float
        Frequency of the mains line in Hz.
    quantize : bool
        Round to integer counts (default). ``False`` keeps exact values (no quantization
        noise), still clipped to the code range.
    seed : int, optional
        Seed of the random generator; a new seed is drawn and recorded when omitted.
    starttime : optional
        Time of the first sample (default 1970-01-01T00:00:00).

    Returns
    -------
    Signal
        Signal in counts, ``full_scale = 2**bits``, titled after its parameters.

    Examples
    --------
    >>> s = make_sine(7.3, ratio=0.5, bits=16, duration=10, seed=1)
    >>> s.full_scale, s.npts, s.title
    (65536.0, 10000, 'sine 7.3 Hz, -6.02 dBFS, 16 bits')
    """
    p = resolve_params(SINE_PARAMS, {k: v for k, v in locals().items()}, command="make_sine")
    n, t, rng, seed_used = _time_base(p)
    f0 = p["frequency"]
    if not 0 < f0 < p["fs"] / 2.0:
        raise ParameterError(
            f"frequency must be between 0 and Nyquist ({p['fs'] / 2.0:g} Hz), got {f0:g} Hz"
        )
    half = 2.0 ** (p["bits"] - 1)
    ratio = 10.0 ** (p["dbfs"] / 20.0) if p["dbfs"] is not None else p["ratio"]
    amplitude = ratio * half
    arg = 2.0 * math.pi * f0 * t + p["phase"]
    x = amplitude * np.sin(arg)
    levels = harmonic_levels(p["harmonics"])
    for order, dbc in sorted(levels.items()):
        if order * f0 >= p["fs"] / 2.0:
            warnings.warn(f"Harmonic H{order} ({order * f0:g} Hz) is above Nyquist: skipped",
                          OnTheSignalWarning, stacklevel=2)
            continue
        x += amplitude * 10.0 ** (dbc / 20.0) * np.sin(order * arg)
    if p["noise_rms"] > 0:
        x += rng.normal(0.0, p["noise_rms"], n)

    level = 20.0 * math.log10(ratio) if ratio > 0 else -math.inf
    title = f"sine {f0:g} Hz, {level:.2f} dBFS, {p['bits']} bits"
    details = [f"f = {f0:g} Hz", f"A = {amplitude:.6g} counts ({level:.2f} dBFS)"]
    if levels:
        details.append("harmonics "
                       + ", ".join(f"H{k} {v:g} dBc" for k, v in sorted(levels.items())))
    if p["noise_rms"] > 0:
        title += f", noise {p['noise_rms']:g} counts RMS"
        details.append(f"noise {p['noise_rms']:g} counts RMS")
    metadata = {"synthetic": "sine", "frequency": f0, "ratio": float(f"{ratio:.6g}"),
                "amplitude": float(f"{amplitude:.6g}"), "noise_rms": p["noise_rms"]}
    if levels:
        metadata["harmonics"] = " ".join(f"{k}:{v:g}" for k, v in sorted(levels.items()))
    return _digitize(x, t, p, rng, seed_used, "SIN", title, details, metadata)


def make_noise(
    rms: float = 1.0,
    color: str = "white",
    bits: int = 24,
    fs: float = 1000.0,
    duration: float = 60.0,
    *,
    offset: float = 0.0,
    mains_dbfs: float | None = None,
    mains_freq: float = 50.0,
    quantize: bool = True,
    seed: int | None = None,
    starttime: Any = None,
) -> Signal:
    """Random Gaussian noise digitized by an ideal ``bits``-bit converter.

    White noise has a standard deviation of ``rms`` counts. Pink (1/f power) and brown
    (1/f² power) noises are white noise shaped in the frequency domain, then scaled to an RMS
    of exactly ``rms`` counts. When quantized, the quantization noise (``1/√12`` count RMS)
    adds to it: ``σ = sqrt(rms² + 1/12)`` for white noise.

    Parameters
    ----------
    rms : float
        Noise RMS in counts, before quantization.
    color : {"white", "pink", "brown"}
        Spectrum shape.
    bits : int
        Number of encoding bits; the full scale is ``2**bits`` counts peak-to-peak.
    fs : float
        Sampling rate in Hz.
    duration : float
        Duration in seconds.
    offset : float
        DC offset in counts.
    mains_dbfs : float, optional
        Level in dBFS of an added sine at ``mains_freq`` (mains interference).
    mains_freq : float
        Frequency of the mains line in Hz.
    quantize : bool
        Round to integer counts (default).
    seed : int, optional
        Seed of the random generator; a new seed is drawn and recorded when omitted.
    starttime : optional
        Time of the first sample (default 1970-01-01T00:00:00).

    Returns
    -------
    Signal
        Signal in counts, ``full_scale = 2**bits``, titled after its parameters.

    Examples
    --------
    >>> s = make_noise(rms=5.0, bits=24, duration=100, seed=1)
    >>> s.title, round(float(s.data.std()), 1)
    ('white noise 5 counts RMS, 24 bits', 5.0)
    """
    p = resolve_params(NOISE_PARAMS, {k: v for k, v in locals().items()}, command="make_noise")
    n, t, rng, seed_used = _time_base(p)
    x = colored_noise(rng, n, p["color"], p["rms"])
    title = f"{p['color']} noise {p['rms']:g} counts RMS, {p['bits']} bits"
    details = [f"{p['color']} Gaussian noise, {p['rms']:g} counts RMS"]
    metadata = {"synthetic": f"{p['color']} noise", "rms": p["rms"]}
    return _digitize(x, t, p, rng, seed_used, "NOI", title, details, metadata)


# ---------------------------------------------------------------------------------- helpers
def harmonic_levels(value: Mapping[int, float] | str | None) -> dict[int, float]:
    """Harmonic levels in dBc from ``{2: -100}`` or ``"2:-100,3:-110"``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return {}
    items: list[tuple[Any, Any]]
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, str):
        items = []
        for part in value.strip().strip("{}").split(","):
            if not part.strip():
                continue
            order_text, sep, level_text = part.partition(":")
            if not sep:
                raise ParameterError(f"Harmonic {part.strip()!r}: use order:dBc, e.g. 2:-100")
            items.append((order_text, level_text))
    else:
        raise ParameterError("harmonics must be a dict {order: dBc} or a string '2:-100,3:-110'")
    out: dict[int, float] = {}
    for order, level in items:
        try:
            k, dbc = int(str(order).strip()), float(str(level).strip())
        except ValueError:
            raise ParameterError(f"Invalid harmonic {order}:{level} (order:dBc)") from None
        if k < 2:
            raise ParameterError(f"Harmonic orders start at 2, got {k}")
        out[k] = dbc
    return out


def colored_noise(rng: np.random.Generator, n: int, color: str, rms: float) -> np.ndarray:
    """Gaussian noise of ``n`` samples: white (std ``rms``) or pink/brown (RMS exactly ``rms``)."""
    white = rng.normal(0.0, 1.0, n)
    if color == "white" or rms == 0:
        return rms * white
    exponent = {"pink": 0.5, "brown": 1.0}.get(color)
    if exponent is None:
        raise ParameterError("color must be 'white', 'pink' or 'brown'")
    spec = scipy.fft.rfft(white)
    f = scipy.fft.rfftfreq(n)
    spec[0] = 0.0
    spec[1:] /= f[1:] ** exponent  # amplitude ∝ f^-exponent, i.e. power ∝ 1/f or 1/f²
    shaped = scipy.fft.irfft(spec, n=n)
    return shaped * (rms / float(np.std(shaped)))


def _time_base(p: dict) -> tuple[int, np.ndarray, np.random.Generator, int]:
    n = int(round(p["duration"] * p["fs"]))
    if n < 2:
        raise ParameterError("duration × fs must give at least 2 samples")
    seed = p["seed"]
    if seed is None:
        seed = int(np.random.SeedSequence().generate_state(1)[0])
    return n, np.arange(n) / p["fs"], np.random.default_rng(seed), seed


def _digitize(x: np.ndarray, t: np.ndarray, p: dict, rng: np.random.Generator, seed: int,
              channel: str, title: str, details: list[str], metadata: dict) -> Signal:
    """Add offset and mains line, quantize, clip to the code range and build the signal."""
    bits = p["bits"]
    half = 2.0 ** (bits - 1)
    x = x + p["offset"]
    if p["mains_dbfs"] is not None:
        if not 0 < p["mains_freq"] < p["fs"] / 2.0:
            raise ParameterError("mains_freq must be between 0 and Nyquist")
        mains = 10.0 ** (p["mains_dbfs"] / 20.0) * half
        x = x + mains * np.sin(2.0 * math.pi * p["mains_freq"] * t)
        title += f", mains {p['mains_dbfs']:g} dBFS"
        details.append(f"mains {p['mains_freq']:g} Hz at {p['mains_dbfs']:g} dBFS")
        metadata["mains_dbfs"] = p["mains_dbfs"]
    if p["offset"]:
        details.append(f"offset {p['offset']:g} counts")
    if p["quantize"]:
        x = np.round(x)
    lo, hi = -half, half - 1.0
    clipped = int(np.count_nonzero((x < lo) | (x > hi)))
    if clipped:
        warnings.warn(
            f"{clipped} sample(s) clipped to the code range [{lo:.0f}, {hi:.0f}] of a "
            f"{bits}-bit digitizer", OnTheSignalWarning, stacklevel=3)
        x = np.clip(x, lo, hi)
    data = x.astype(np.int64 if bits > 31 else np.int32) if p["quantize"] else x
    details.append(f"{bits} bits" + (", quantized" if p["quantize"] else ", not quantized"))
    metadata.update({"bits": bits, "seed": seed})
    return Signal(
        data, p["fs"], starttime=p["starttime"], network="XX", station="SYNTH", channel=channel,
        full_scale=2.0**bits, title=title, metadata=metadata,
        history=[f"synthetic: {', '.join(details)} (seed {seed})"],
    )


__all__ = ["NOISE_PARAMS", "SINE_PARAMS", "colored_noise", "harmonic_levels", "make_noise",
           "make_sine"]
