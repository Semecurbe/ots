"""Synthetic test signals (ideal N-bit digitizer)."""

from __future__ import annotations

import inspect
import math
import warnings

import numpy as np
import pytest

import onthesignal as ots
from onthesignal.analysis import compute_noise, compute_sinad, compute_thd
from onthesignal.core.errors import OnTheSignalWarning, ParameterError
from onthesignal.core.result import Result
from onthesignal.synthetic import (
    NOISE_PARAMS,
    SINE_PARAMS,
    harmonic_levels,
    make_noise,
    make_sine,
)


@pytest.mark.parametrize("bits", [16, 24])
def test_ideal_quantized_sine_gives_theoretical_sinad(bits):
    """Full band: SINAD = 6.02 N + 1.76 + 20 log10(ratio), ENOB_fs = N (± 0.1 bit)."""
    s = make_sine(7.3, ratio=0.9, bits=bits, duration=60, seed=1)
    assert s.full_scale == 2.0**bits and s.unit == "counts"
    assert np.all(s.data == np.round(s.data)) and s.metadata["dtype"] == "int32"
    r = compute_sinad(s, fmax=1e9)
    expected = 6.02 * bits + 1.76 + 20 * math.log10(0.9)
    assert r["sinad"] == pytest.approx(expected, abs=0.2)
    assert r["enob_fs"] == pytest.approx(bits, abs=0.1)
    assert r["amplitude_dbfs"] == pytest.approx(20 * math.log10(0.9), abs=1e-3)


def test_sine_amplitude_options_and_title():
    s = make_sine(10.1, dbfs=-6.0206, bits=16, duration=10, seed=1)
    assert s.metadata["ratio"] == pytest.approx(0.5, rel=1e-4)
    assert s.title == "sine 10.1 Hz, -6.02 dBFS, 16 bits"
    assert make_sine(ratio=0.5, bits=16, duration=10, seed=1).title == s.title.replace("10.1",
                                                                                       "7.3")
    with pytest.raises(ParameterError, match="Nyquist"):
        make_sine(600.0, fs=1000.0, duration=1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        clipped = make_sine(ratio=1.2, bits=16, duration=10, seed=1)
    assert any(issubclass(w.category, OnTheSignalWarning) and "clipped" in str(w.message)
               for w in caught)
    assert clipped.data.max() == 2**15 - 1 and clipped.data.min() == -(2**15)


def test_harmonics_noise_and_mains():
    s = make_sine(7.3, ratio=0.9, bits=24, harmonics="2:-100,3:-110", noise_rms=3.0,
                  mains_dbfs=-80, seed=2)
    thd = compute_thd(s)["thd_db"]
    assert thd == pytest.approx(10 * math.log10(1e-10 + 1e-11), abs=0.2)
    assert compute_sinad(s, remove_mains=True)["sinad"] > compute_sinad(s)["sinad"] + 15
    assert harmonic_levels({2: -90}) == {2: -90.0}
    with pytest.raises(ParameterError):
        harmonic_levels("1:-90")
    with pytest.raises(ParameterError):
        harmonic_levels("2=-90")


def test_noise_rms_color_and_seed():
    white = make_noise(5.0, bits=24, duration=600, seed=3)
    assert white.data.std() == pytest.approx(math.sqrt(25 + 1 / 12), rel=0.01)
    assert compute_noise(white, fmax=1e9)["rms"] == pytest.approx(white.data.std(), rel=1e-6)
    again = make_noise(5.0, bits=24, duration=600, seed=3)
    assert np.array_equal(white.data, again.data)
    assert make_noise(5.0, duration=10).metadata["seed"] != make_noise(5.0, duration=10).metadata[
        "seed"]
    pink = make_noise(5.0, "pink", quantize=False, duration=600, seed=4)
    assert pink.data.std() == pytest.approx(5.0, rel=1e-9)
    f = np.fft.rfftfreq(pink.npts, 1 / pink.sampling_rate)
    power = np.abs(np.fft.rfft(pink.data)) ** 2
    low = power[(f > 1) & (f < 2)].mean()
    high = power[(f > 100) & (f < 200)].mean()
    assert 10 * math.log10(low / high) == pytest.approx(20.0, abs=1.5)  # 1/f: 10 dB/decade


def test_param_declarations_match_signatures():
    """The console forms and AI schemas use the same names and defaults as the functions."""
    for func, decl in ((make_sine, SINE_PARAMS), (make_noise, NOISE_PARAMS)):
        sig = inspect.signature(func).parameters
        assert [p.name for p in decl] and set(sig) == {p.name for p in decl}
        for p in decl:
            assert sig[p.name].default == p.default, (func.__name__, p.name)


def test_session_versions_register_signals(session):
    s = ots.make_sine(bits=16, duration=5, seed=1)
    n = ots.make_noise(2.0, duration=5, seed=1, name="N")
    assert list(session.signals) == ["S1", "N"] and s.name == "S1" and n.name == "N"
    assert session.history[-1] == "make_noise(2.0, duration=5, seed=1)"
    assert "name : str" in ots.make_sine.__doc__


def test_console_and_ai_tools(tmp_path, monkeypatch):
    from onthesignal.ai.tools import build_tools
    from onthesignal.cli.console import OnTheSignalConsole
    from onthesignal.core.config import Config

    monkeypatch.chdir(tmp_path)
    con = OnTheSignalConsole(files=[], config=Config(), ask=lambda label, d: "", forms=False)
    con.execute("/make_sine 7.3 0.5 16 duration=5 harmonics=2:-90 seed=1")
    con.execute("/make_noise rms=3 color=pink duration=5 name=N")
    assert list(con.session.signals) == ["S1", "N"]
    assert con.session.signals["S1"].full_scale == 2.0**16
    assert con.ns["N"].title == "pink noise 3 counts RMS, 24 bits"
    tools = build_tools(con.session)
    assert "harmonics" in tools["make_sine"].spec.schema["properties"]
    out = tools["make_noise"].func({"rms": 1.0, "duration": 2, "name": "AI1"})
    assert out["name"] == "AI1" and not tools["make_noise"].confirm
    assert isinstance(ots.sinad("S1", show=False), Result)
