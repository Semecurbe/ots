"""Validation of the analyses on synthetic signals (specification §19, V-01 to V-13)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from onthesignal import Signal
from onthesignal.analysis import (
    compute_dynamic,
    compute_lnm,
    compute_noise,
    compute_noise_dsp,
    compute_noise_fft,
    compute_sfdr,
    compute_sinad,
    compute_thd,
    fit4,
    peterson_models,
)
from onthesignal.core.errors import UnitError
from onthesignal.processing import band_limit

from .conftest import sine

FULL = {"fmax": 1e9}  # full band (fmax above Nyquist)


# ---------------------------------------------------------------------------------- noise
def test_v01_white_noise_rms(white_noise):
    r = compute_noise(white_noise)
    assert r["rms"] == pytest.approx(100.0, rel=0.01)
    assert r["enbw"] == pytest.approx(100.0)
    assert r["pp_gauss"] == pytest.approx(6.6 * r["rms"])


def test_v02_psd_integration_matches_time_rms(white_noise):
    r = compute_noise_dsp(white_noise)
    assert r["rms_psd"] == pytest.approx(r["rms"], rel=0.02)


def test_v03_ideal_quantization_dynamic_range(rng):
    s = Signal(rng.uniform(-0.5, 0.5, 1_000_000), 200.0)
    r = compute_noise(s, full_scale=2**24)
    assert r["dr"] == pytest.approx(146.26, abs=0.1)


def test_band_limited_white_noise(white_noise):
    """A 0–50 Hz band keeps half of the white-noise power."""
    r = compute_noise(white_noise, fmax=50.0)
    assert r["rms"] == pytest.approx(100.0 / math.sqrt(2.0), rel=0.01)
    assert r["enbw"] == pytest.approx(50.0, rel=1e-3)


def test_mains_removal_and_enbw(rng):
    fs, n = 1000.0, 400_000
    x = rng.normal(0, 1.0, n) + 50.0 * np.sin(2 * np.pi * 50.0 * np.arange(n) / fs)
    s = Signal(x, fs)
    with_mains = compute_noise(s)
    without = compute_noise(s, remove_mains=True)
    assert with_mains["rms"] > 30
    assert without["rms"] == pytest.approx(math.sqrt(1.0 * 98.5 / 500), rel=0.02)
    assert without["enbw"] == pytest.approx(98.5, abs=0.01)
    assert without["mains_removed"] == [50.0, 100.0]


def test_iir_band_reports_effective_enbw(white_noise):
    # Butterworth order 4 applied forward-backward: ENBW ≈ 0.898 × fc when fc << fs
    # (analog approximation; the bilinear transform warps the response near Nyquist).
    out = band_limit(white_noise.data, 200.0, fmax=5.0, method="iir", order=4)
    assert out.enbw == pytest.approx(0.898 * 5.0, rel=0.01)
    # Whatever the cut-off, the measured RMS follows the reported ENBW.
    for fc in (5.0, 50.0):
        out = band_limit(white_noise.data, 200.0, fmax=fc, method="iir", order=4)
        assert np.std(out.data) == pytest.approx(100 * math.sqrt(out.enbw / 100.0), rel=0.02)


def test_v13_fft_amplitude_scaling():
    fs, n = 1000.0, 10_000
    s = Signal(sine(n, fs, 10.0, 3.0), fs)  # 10 Hz exactly on a bin (df = 0.1 Hz)
    r = compute_noise_fft(s, fmax=1e9, window="hann", scale="amplitude")
    c = r.curves["spectrum"]
    assert c.y[np.argmin(np.abs(c.x - 10.0))] == pytest.approx(3.0, rel=1e-3)


def test_physical_units(white_noise):
    white_noise.unit = "V"
    white_noise.sensitivity = 2.384e-6
    r = compute_noise(white_noise)
    assert r["rms_phys"] == pytest.approx(r["rms"] * 2.384e-6)
    assert "rms_phys" not in compute_noise(white_noise, units="counts").values


def test_saturation_warning():
    s = Signal(np.clip(sine(10_000, 100.0, 1.3, 2**23), -2**23, 2**23 - 1), 100.0)
    assert any("saturation" in w for w in compute_noise(s).warnings)


# ---------------------------------------------------------------------------------- lnm
def test_v09_lnm_levels(rng):
    sigma, fs = 1e-8, 100.0
    s = Signal(rng.normal(0, sigma, 360_000), fs, unit="m/s**2")
    r = compute_lnm(s, smoothing=None)
    psd = r.curves["psd"]
    expected = 10 * math.log10(2 * sigma**2 / fs)
    assert np.median(psd.y) == pytest.approx(expected - 2.5, abs=0.5) or abs(
        np.mean(10 ** (psd.y / 10)) - 2 * sigma**2 / fs) < 0.1 * 2 * sigma**2 / fs
    periods, acc, _ = peterson_models("acceleration")
    _, vel, _ = peterson_models("velocity")
    _, disp, _ = peterson_models("displacement")
    w = 2 * np.pi / periods
    assert np.allclose(vel, acc - 20 * np.log10(w), atol=0.01)
    assert np.allclose(disp, acc - 40 * np.log10(w), atol=0.01)


# Peterson (1993) tables: level = A + B log10(P) in dB re 1 (m/s²)²/Hz, (P, A, B).
_NLNM_POINTS = [(0.1, -162.36, 5.64), (1.0, -166.40, 28.90), (5.0, -71.36, -99.77),
                (10.0, -132.18, -31.57), (100.0, -216.47, 15.70), (300.0, -168.34, -7.61)]
_NHNM_POINTS = [(0.1, -108.73, -17.23), (1.0, -116.85, 32.51), (5.0, -74.66, -32.95),
                (10.0, -93.37, -22.42), (100.0, -151.52, 10.01), (300.0, -151.52, 10.01)]


def test_peterson_models_match_the_published_tables():
    """Regression: ObsPy gives decreasing periods; np.interp needs them increasing."""
    periods, nlnm, nhnm = peterson_models("acceleration")
    assert np.all(np.diff(periods) > 0)
    for points, model in ((_NLNM_POINTS, nlnm), (_NHNM_POINTS, nhnm)):
        for period, a, b in points:
            level = np.interp(np.log10(period), np.log10(periods), model)
            assert level == pytest.approx(a + b * math.log10(period), abs=0.2), period


def test_lnm_difference_follows_the_model(rng):
    """PSD − NLNM must follow the model shape (it was flat with unsorted model periods)."""
    sigma, fs = 1e-6, 20.0
    s = Signal(rng.normal(0, sigma, 72_000), fs, unit="m")
    r = compute_lnm(s)
    diff, smooth = r.curves["diff"], r.curves["psd_smooth"]
    periods, nlnm, _ = peterson_models("displacement")
    keep = np.isin(smooth.x, diff.x)
    model = smooth.y[keep] - diff.y
    expected = np.interp(np.log10(1.0 / diff.x), np.log10(periods), nlnm)
    assert np.allclose(model, expected, atol=1e-9)
    at_1s = np.interp(0.0, np.log10(1.0 / diff.x[::-1]), model[::-1])
    assert at_1s == pytest.approx(-166.40 - 40 * math.log10(2 * math.pi), abs=0.3)
    assert np.ptp(diff.y) > 50  # displacement NLNM spans tens of dB over 0.01–10 Hz
    assert r.extra["x"] == "freq" and np.all(np.diff(r.curves["nlnm"].x) > 0)


def test_lnm_requires_motion_unit(white_noise):
    white_noise.unit = "V"
    with pytest.raises(UnitError, match="ground-motion"):
        compute_lnm(white_noise)


# ---------------------------------------------------------------------------------- sine
def test_v08_four_parameter_fit():
    fs, f0 = 1000.0, 7.3
    n = int(7.3 / f0 * fs * 7.3)  # 7.3 periods
    x = sine(n, fs, f0, 1234.5, phase=0.7, offset=42.0)
    fit = fit4(x, fs)
    assert fit.converged
    assert fit.frequency == pytest.approx(f0, rel=1e-6)
    assert fit.amplitude == pytest.approx(1234.5, rel=1e-6)
    assert fit.offset == pytest.approx(42.0, abs=1e-3)
    assert np.max(np.abs(fit.residual)) < 1e-6


def test_v05_sinad(rng):
    fs, n, a, sigma = 1000.0, 400_000, 1e6, 10.0
    s = Signal(sine(n, fs, 13.7, a) + rng.normal(0, sigma, n), fs)
    r = compute_sinad(s, **FULL)
    assert r["sinad"] == pytest.approx(20 * math.log10(a / math.sqrt(2) / sigma), abs=0.1)
    assert r["thd_n"] == pytest.approx(-r["sinad"])


@pytest.mark.parametrize("bits", [16, 24])
def test_v04_enob_of_ideal_quantizer(bits):
    fs, n = 1000.0, 500_000
    amplitude = 0.49 * 2**bits
    s = Signal(np.round(sine(n, fs, 13.7123, amplitude)), fs)
    r = compute_sinad(s, full_scale=2**bits, **FULL)
    assert r["enob_fs"] == pytest.approx(bits, abs=0.1)


def test_v06_thd(rng):
    fs, n, a1 = 1000.0, 300_000, 1e6
    x = sine(n, fs, 7.3, a1) + 40 * np.sin(2 * np.pi * 14.6 * np.arange(n) / fs) \
        + 15 * np.sin(2 * np.pi * 21.9 * np.arange(n) / fs) + rng.normal(0, 1, n)
    r = compute_thd(Signal(x, fs))
    expected = 20 * math.log10(math.hypot(40, 15) / a1)
    assert r["thd_db"] == pytest.approx(expected, abs=0.1)
    assert r.tables["harmonics"][0]["order"] == 2


def test_v07_sfdr_on_non_harmonic_spur(rng):
    fs, n, a1, a_spur = 1000.0, 300_000, 1e6, 20.0
    t = np.arange(n) / fs
    x = sine(n, fs, 7.3, a1) + a_spur * np.sin(2 * np.pi * 33.37 * t) + rng.normal(0, 0.5, n)
    r = compute_sfdr(Signal(x, fs))
    assert r["sfdr_dbc"] == pytest.approx(20 * math.log10(a1 / a_spur), abs=0.2)
    assert r["spur_frequency"] == pytest.approx(33.37, abs=2 * fs / n)
    assert r["spur_nature"] == "other"
    assert not r["noise_limited"]


def test_sfdr_noise_limited_warning(rng):
    fs, n = 1000.0, 200_000
    x = sine(n, fs, 7.3, 1e6) + rng.normal(0, 1, n)
    r = compute_sfdr(Signal(x, fs))
    assert r["noise_limited"]


def test_dynamic_consistency_and_noise_record(rng, white_noise):
    fs, n = 1000.0, 300_000
    x = sine(n, fs, 7.3, 1e6) + 30 * np.sin(2 * np.pi * 14.6 * np.arange(n) / fs) \
        + rng.normal(0, 3, n)
    r = compute_dynamic(Signal(x, fs, name="S2"), noise=white_noise)
    assert abs(r["sinad_check"]) < 0.05
    assert r["snr"] > r["sinad"]
    assert r["dr"] == pytest.approx(compute_noise(white_noise)["dr"])


def test_mains_coincidence_warning():
    fs, n = 1000.0, 100_000
    r = compute_sinad(Signal(sine(n, fs, 10.0, 1e5), fs))
    assert any("coincides with a mains line" in w for w in r.warnings)


def test_sine_figures_show_conditions_and_removed_mains(rng):
    """Sine spectra: log frequency axis by default, conditions above, red mains markers."""
    from onthesignal.plot import plot_result
    from onthesignal.plot.style import REMOVED

    fs, n = 1000.0, 100_000
    t = np.arange(n) / fs
    x = sine(n, fs, 7.3, 1e6) + 2e3 * np.sin(2 * np.pi * 50.0 * t) + rng.normal(0, 10, n)
    sig = Signal(x, fs, name="S1")
    kept = compute_sinad(sig)
    removed = compute_sinad(sig, remove_mains=True)
    assert removed["sinad"] > kept["sinad"] + 20  # the 50 Hz dominated the residual
    assert removed.curves["residual_spectrum"].xscale == "log"
    assert compute_sinad(sig, xscale="linear").curves["residual_spectrum"].xscale == "linear"
    assert compute_sfdr(sig, remove_mains=True).extra["mains_lines"] == [50.0, 100.0]

    spec = plot_result(removed).axes[2]
    assert spec.get_xscale() == "log"
    title = spec.get_title(loc="left")
    assert "0–100 Hz" in title and "50 Hz and harmonics removed (50, 100 Hz, ±0.5 Hz)" in title
    red = [ln for ln in spec.get_lines() if ln.get_color() == REMOVED]
    assert sorted(ln.get_xdata()[0] for ln in red) == [50.0, 100.0]
    spec_kept = plot_result(kept).axes[2]
    assert "50 Hz and harmonics not removed" in spec_kept.get_title(loc="left")
    assert not [ln for ln in spec_kept.get_lines() if ln.get_color() == REMOVED]
