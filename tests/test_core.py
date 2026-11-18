"""Signal model, parameters, results and session."""

from __future__ import annotations

import json
import warnings

import numpy as np
import pytest

from onthesignal import Signal
from onthesignal.core.errors import (
    OnTheSignalWarning,
    ParameterError,
    TimeRangeError,
    UnitError,
)
from onthesignal.core.params import Param, resolve_params, safe_eval
from onthesignal.core.result import Result
from onthesignal.core.units import format_quantity, normalize_unit


# ---------------------------------------------------------------------------------- params
def test_safe_eval_arithmetic():
    assert safe_eval("2**24") == 16777216
    assert safe_eval("-1e-3 * 4") == pytest.approx(-0.004)
    with pytest.raises(ParameterError):
        safe_eval("__import__('os')")
    with pytest.raises(ParameterError):
        safe_eval("2**10000")


def test_param_coercion():
    assert Param("x", bool, False).coerce("true") is True
    assert Param("x", float, 1.0).coerce("2**23") == 2.0**23
    assert Param("x", int, 1).coerce("12") == 12
    with pytest.raises(ParameterError):
        Param("x", int, 1).coerce("1.5")
    with pytest.raises(ParameterError):
        Param("x", str, "a", choices=("a", "b")).coerce("c")
    with pytest.raises(ParameterError):
        Param("x", float, 1.0, min=0).coerce(-1)


def test_resolve_precedence():
    decl = [
        Param("full_scale", float, 2.0**24, from_signal="full_scale"),
        Param("fmax", float, 100.0),
    ]

    class Cfg:
        def get(self, key, default=None):
            return {"analysis.fmax": 50.0, "analysis.full_scale": 1000.0}.get(key, default)

    s = Signal(np.zeros(10), 10.0)
    p = resolve_params(decl, {}, s, Cfg())
    assert p == {"full_scale": 1000.0, "fmax": 50.0}  # config beats default
    s.full_scale = 2.0**23
    assert resolve_params(decl, {}, s, Cfg())["full_scale"] == 2.0**23  # signal beats config
    assert resolve_params(decl, {"full_scale": 7}, s, Cfg())["full_scale"] == 7.0  # call wins
    with pytest.raises(ParameterError, match="Unknown parameter"):
        resolve_params(decl, {"fmaxx": 1}, s)


# ---------------------------------------------------------------------------------- units
def test_units():
    assert normalize_unit("M/S") == "m/s"
    assert normalize_unit("m/s²") == "m/s**2"
    assert normalize_unit("") == "counts"
    assert format_quantity(2.432e-6, "V") == "2.432 µV"
    assert format_quantity(135.29, "dB", 5) == "135.29 dB"


# ---------------------------------------------------------------------------------- signal
def test_signal_attributes():
    s = Signal(np.arange(1000), 100.0, starttime="2026-11-17T10:00:00", network="RD",
               station="SN270", location="00", channel="FHZ", unit="V", sensitivity=2.384e-6)
    assert s.id == "RD.SN270.00.FHZ"
    assert s.npts == 1000 and s.duration == 10.0
    assert s.endtime - s.starttime == pytest.approx(9.99)
    assert s.to_physical()[10] == pytest.approx(10 * 2.384e-6)
    assert "Sensitivity" in s.describe() and "2**24" in s.describe()
    assert s.metadata["dtype"].startswith("int")
    with pytest.raises(ParameterError):
        s.sensitivity = 0


def test_signal_title_and_label():
    s = Signal(np.zeros(10), 10.0, network="RD", station="SN270", location="00", channel="FHZ",
               title=" bench_1 ")
    assert s.title == "bench_1"
    assert s.label == "bench_1 (RD.SN270.00.FHZ)"
    s.name = "S1"
    assert s.label == "S1 · bench_1 (RD.SN270.00.FHZ)"
    assert "bench_1" in s.describe() and s.identity()["title"] == "bench_1"
    assert (2 * s).title == "bench_1" and s.slice(0, 0.5).title == "bench_1"
    s.title = None
    assert s.title == "" and s.label == "S1 (RD.SN270.00.FHZ)"
    a = Signal(np.ones(10), 10.0, name="A", title="run_a")
    b = Signal(np.ones(10), 10.0, name="B", title="run_b")
    assert (a - b).title == "run_a − run_b"
    assert (a + a.copy()).title == "run_a"


def test_scalar_operators_do_not_modify_original():
    s = Signal(np.ones(10), 10.0, name="S1")
    d = 2 * s
    assert np.all(d.data == 2) and np.all(s.data == 1)
    assert (s / 4).data[0] == 0.25 and (-s).data[0] == -1
    assert d.history[-1] == "amplitude × 2"


def test_add_aligned_and_interpolated():
    fs = 100.0
    a = Signal(np.arange(1000.0), fs, starttime=0.0, name="A")
    b = Signal(np.arange(1000.0), fs, starttime=0.5, name="B")
    c = a + b  # aligned grids, common window 0.5..9.99
    assert c.starttime.timestamp == pytest.approx(0.5)
    assert c.npts == 950
    assert c.data[0] == pytest.approx(50.0 + 0.0)
    shifted = Signal(np.arange(1000.0), fs, starttime=0.505, name="C")  # half a sample
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        d = a + shifted  # V-14
    assert any(issubclass(w.category, OnTheSignalWarning) for w in caught)
    # shifted ramp interpolated at a's grid: value = (t - 0.505) * 100
    t = d.times("timestamp")
    assert np.allclose(d.data, t * 100 + (t - 0.505) * 100, atol=1e-6)


def test_add_rescales_sensitivity_and_checks_units():
    a = Signal(np.ones(100), 10.0, unit="V", sensitivity=1e-6)
    b = Signal(np.ones(100), 10.0, unit="V", sensitivity=2e-6)
    assert (a + b).data[0] == pytest.approx(3.0)  # b expressed in a's counts
    with pytest.raises(UnitError):
        a + Signal(np.ones(100), 10.0, unit="m/s")
    with pytest.raises(TimeRangeError):
        a + Signal(np.ones(100), 10.0, unit="V", starttime=1000.0)


def test_slice_and_resample():
    s = Signal(np.arange(1000.0), 100.0, starttime=0.0)
    w = s.slice(1.0, 2.0)
    assert w.npts == 101 and w.data[0] == 100
    assert s.resample(50.0).sampling_rate == 50.0
    with pytest.raises(TimeRangeError):
        s.slice(100.0, 200.0)


# ---------------------------------------------------------------------------------- result
def test_result_serialization(tmp_path):
    r = Result("noise", title="t")
    r.add("rms", 1.5, "counts", "RMS")
    r.add("rms_phys", 3e-6, "V", "RMS")
    r.add("dr", float("inf"), "dB", "DR")
    data = json.loads(r.to_json())
    assert data["values"]["dr"]["value"] == "inf"
    assert r["rms"] == 1.5
    assert "(3 µV)" in r.to_text() or "(3.000 µV)" in r.to_text()
    r.save(tmp_path / "r.csv")
    assert (tmp_path / "r.csv").read_text().startswith("key,label,value,unit")


# ---------------------------------------------------------------------------------- session
def test_session_names_and_namespace(session):
    s = Signal(np.zeros(10), 10.0)
    assert session.add_signal(s) == "S1"
    ns = {"S1": s, "X": s, "S5": 2 * s}
    session.sync_namespace(ns)
    assert set(session.signals) == {"S1", "S5"}  # X is an alias of S1
    assert ns["S5"].name == "S5"
    del ns["S5"]
    session.sync_namespace(ns)
    assert set(session.signals) == {"S1"}
    assert "S1" in session.list_text()
