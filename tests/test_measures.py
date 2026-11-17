"""Measurements, coherence and spectrogram (V-10, V-11, V-12)."""

from __future__ import annotations

import numpy as np
import pytest

from onthesignal import Signal
from onthesignal.analysis import (
    compute_coherence,
    compute_delay50,
    compute_frequency,
    compute_period,
    compute_spectrogram,
    crossings,
)

from .conftest import sine


def test_crossings_with_hysteresis(rng):
    x = np.sin(2 * np.pi * np.arange(1000) / 100.0) + rng.normal(0, 0.02, 1000)
    tc = crossings(x, 0.0, hysteresis=0.2)
    assert tc.size == 9  # one rising crossing per period despite the noise
    # timing jitter: noise 0.02 / slope 0.063 per sample ≈ 0.32 sample per crossing
    assert np.allclose(np.diff(tc), 100.0, atol=1.5)
    assert crossings(x, 0.0, 0.2, "falling").size in (10, 9)


@pytest.mark.parametrize("method", ["zero_crossing", "sinefit", "fft"])
def test_v12_frequency_and_period(method):
    fs, f0 = 1000.0, 7.3123
    s = Signal(sine(200_000, fs, f0, 1000.0), fs)  # ~1460 periods, ~137 samples per period
    r = compute_frequency(s, method=method)
    tol = 1e-4 if method != "fft" else 1e-3
    assert r["frequency"] == pytest.approx(f0, rel=tol)
    p = compute_period(s, method=method)
    assert p["period"] == pytest.approx(1 / f0, rel=tol)


def _ramp_steps(fs: float, delay: float, n: int = 4000, period: float = 1.0):
    """Square wave with linear ramps of 10 samples (at fs = 1000 Hz), delayed by ``delay``."""
    t = np.arange(n) / fs
    phase = ((t - delay) % period) / period
    rise = 10 / 1000.0 / period
    up = np.clip(phase / rise, 0, 1)
    down = np.clip((phase - 0.5) / rise, 0, 1)
    return up - down


def test_v11_delay50_subsample_and_different_rates():
    fs1, fs2 = 1000.0, 500.0
    delta = 0.37 / fs1
    s1 = Signal(_ramp_steps(fs1, 0.1), fs1, name="A")
    s2 = Signal(_ramp_steps(fs2, 0.1 + delta, n=2000) * 3 + 7, fs2, name="B")
    r = compute_delay50(s1, s2, edge="both", levels="minmax")
    assert r["delay"] == pytest.approx(delta, abs=0.01 / fs1)
    assert r["n_edges"] >= 6


def test_v10_coherence(rng):
    fs, n = 100.0, 200_000
    a = Signal(rng.normal(0, 1, n), fs)
    same = compute_coherence(a, a.copy())
    assert same["mean_coherence"] == pytest.approx(1.0, abs=0.01)
    b = Signal(rng.normal(0, 1, n), fs)
    indep = compute_coherence(a, b, significance=True)
    n_avg = indep["n_averages"]
    assert indep["mean_coherence"] < 3.0 / n_avg
    assert 0 < indep["threshold"] < 1


def test_spectrogram_shape_and_limits(rng):
    fs, n = 200.0, 400_000
    x = rng.normal(0, 1, n) + 5 * np.sin(2 * np.pi * 30 * np.arange(n) / fs)
    r = compute_spectrogram(Signal(x, fs), fmax=80)
    img = r.extra["image"]
    assert img["z"].shape[1] <= 400 and img["z"].shape[0] <= 2000
    assert img["f"].max() <= 80
    row = np.argmin(np.abs(img["f"] - 30))
    assert np.median(img["z"][row]) > np.median(img["z"]) + 10
