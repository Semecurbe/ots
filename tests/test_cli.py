"""Console: Python input, slash commands, forms, namespace synchronization."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime
from prompt_toolkit.document import Document

from onthesignal.cli import commands
from onthesignal.cli.completion import ConsoleCompleter
from onthesignal.cli.console import OnTheSignalConsole
from onthesignal.cli.forms import ask_params
from onthesignal.core.config import Config
from onthesignal.core.params import Param


@pytest.fixture
def mseed(tmp_path):
    rng = np.random.default_rng(0)
    t0 = UTCDateTime("2026-11-17T10:00:00")
    traces = []
    for cha in ("FHZ", "FHN"):
        traces.append(Trace(rng.normal(0, 50, 20_000).astype(np.int32),
                            header={"network": "RD", "station": "SN270", "location": "00",
                                    "channel": cha, "sampling_rate": 200.0, "starttime": t0}))
    path = tmp_path / "acq.mseed"
    Stream(traces).write(str(path), format="MSEED")
    return path


@pytest.fixture
def console(tmp_path, monkeypatch, mseed):
    monkeypatch.chdir(tmp_path)
    con = OnTheSignalConsole(files=[str(mseed)], config=Config(), ask=lambda label, d: "",
                             forms=False)
    con.display.console.record = True
    return con


def output(con) -> str:
    return con.display.console.export_text()


def test_parse():
    assert commands.parse("/noise S1 fmax=50 --defaults") == ("noise", ["S1"], {"fmax": "50"},
                                                              {"defaults"})
    assert commands.parse("/exit")[0] == "quit"


def test_load_with_title(console, mseed):
    console.execute(f'/load {mseed} title="Bench test, gain 1" name=B')
    assert console.session.signals["B_1"].title == "Bench test, gain 1"
    assert console.session.signals["S1"].title == mseed.stem


def test_files_loaded_and_python(console):
    assert list(console.session.signals) == ["S1", "S2"]
    console.execute("r = noise(S1, fmax=50)")
    assert console.session.results[-1].kind == "noise"
    assert console.ns["r"]["rms"] > 0
    console.execute("S3 = S1 + S2")
    assert "S3" in console.session.signals and console.session.signals["S3"].name == "S3"
    console.execute("del S3")
    assert "S3" not in console.session.signals
    console.execute("1 / 0")  # errors are displayed, never raised
    assert "ZeroDivisionError" in output(console)


def test_slash_commands(console):
    console.execute("/noise S1 fmax=20")
    assert console.session.results[-1]["band"] == [0.0, 20.0]
    console.execute("/rename S2 Z")
    assert "Z" in console.session.signals and "Z" in console.ns and "S2" not in console.ns
    console.execute("/info Z")
    assert "RD.SN270.00.FHN" in output(console)
    console.execute("/report title=Test")
    assert list(Path("reports").glob("*/report.qmd"))
    console.execute("/help noise")
    assert "Parameters:" in output(console)
    console.execute("/nonexistent")
    assert "Unknown command" in output(console)
    console.execute("/quit")
    assert not console.running


def test_form_uses_defaults_and_typed_values():
    params = [Param("fmax", float, 100.0, unit="Hz", help="Upper bound"),
              Param("remove_mains", bool, False, help="Remove mains"),
              Param("window", str, "hann", advanced=True, help="Window")]
    answers = iter(["50", "", "y", "flattop"])
    values = ask_params(params, {"fmax": 100.0}, lambda label, d: next(answers))
    assert values == {"fmax": 50.0, "window": "flattop"}


def test_form_in_console(tmp_path, monkeypatch, mseed):
    monkeypatch.chdir(tmp_path)
    answers = iter(["", "30", "true", ""])  # fmin (default), fmax, remove_mains, full_scale
    con = OnTheSignalConsole(files=[str(mseed)], config=Config(),
                             ask=lambda label, d: next(answers, ""), forms=True)
    con.execute("/noise S1")
    r = con.session.results[-1]
    assert r["band"] == [0.0, 30.0] and r.params["remove_mains"] is True


def test_completion(console):
    completer = ConsoleCompleter(console)
    names = [c.text for c in completer.get_completions(Document("/noi"), None)]
    assert names[:3] == ["noise", "noise_dsp", "noise_fft"]
    args = [c.text for c in completer.get_completions(Document("/noise S"), None)]
    assert "S1" in args
    params = [c.text for c in completer.get_completions(Document("/noise S1 fm"), None)]
    assert params == ["fmax=", "fmin="] or set(params) == {"fmax=", "fmin="}
    py = [c.text for c in completer.get_completions(Document("noi"), None)]
    assert "noise" in py
