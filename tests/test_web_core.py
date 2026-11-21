"""Core support of the web interface: observable session, result names, layouts, decimation.

None of these tests needs NiceGUI or a browser.
"""

from __future__ import annotations

import threading
import warnings

import numpy as np
import pytest

from onthesignal.cli.console import OnTheSignalConsole
from onthesignal.core.config import Config
from onthesignal.core.errors import ParameterError
from onthesignal.core.params import Param, param_origins
from onthesignal.core.registry import commands, get_command
from onthesignal.core.session import Session, get_session, set_session
from onthesignal.core.signal import Signal
from onthesignal.plot.layouts import (
    comparison_spec,
    comparison_view,
    figure_refs,
    figure_spec,
    figure_specs,
    result_curve,
    results_view,
)
from onthesignal.processing.display import decimate_xy, envelope_indices, window_stats
from onthesignal.synthetic import make_noise, make_sine


def _signals() -> dict[str, Signal]:
    warnings.simplefilter("ignore")
    sine = make_sine(7.3, ratio=0.9, bits=24, harmonics="2:-100,3:-110", noise_rms=2, seed=1,
                     duration=30, mains_dbfs=-110)
    noise = make_noise(5.0, bits=24, seed=2, duration=60, mains_dbfs=-120)
    noise.unit, noise.sensitivity = "V", 2.384e-6
    vel = make_noise(5.0, bits=24, seed=3, duration=1200, fs=100.0)
    vel.unit, vel.sensitivity = "m/s", 1.59e-9
    fs = 1000.0
    t = np.arange(20000) / fs
    square = np.where((t % 1.0) < 0.5, 1000.0, -1000.0)
    a = Signal(square, fs, network="XX", station="A", channel="C01")
    b = Signal(np.roll(square, 3), fs, network="XX", station="B", channel="C01")
    return {"sine": sine, "noise": noise, "vel": vel, "a": a, "b": b}


def _run_all() -> dict[str, object]:
    s = _signals()
    inputs = {"noise": [s["noise"]], "noise_fft": [s["noise"]], "noise_dsp": [s["noise"]],
              "lnm": [s["vel"]], "sinefit": [s["sine"]], "sinad": [s["sine"]],
              "sfdr": [s["sine"]], "thd": [s["sine"]], "dynamic": [s["sine"]],
              "frequency": [s["sine"]], "period": [s["sine"]], "delay50": [s["a"], s["b"]],
              "coherence": [s["noise"], s["vel"]], "spectrogram": [s["noise"]]}
    out = {}
    for cmd in commands():
        args = inputs[cmd.name]
        params = {"remove_mains": True} if cmd.name in ("sinad", "sfdr", "thd", "noise_dsp") \
            else {}
        if cmd.name == "coherence":
            args = [s["noise"], make_noise(5.0, bits=24, seed=9, duration=60)]
        out[cmd.name] = cmd.func(*args, **params)
    return out


@pytest.fixture(scope="module")
def results():
    return _run_all()


# ---------------------------------------------------------------------------------- session
def test_session_events_versions_and_result_names():
    session = Session(config=Config())
    events = []
    unsubscribe = session.subscribe(lambda event, data: events.append((event, data)))
    v0 = session.version
    sig = make_noise(1.0, bits=16, seed=1, duration=1)
    session.add_signal(sig)
    from onthesignal.core.result import Result

    r1, r2 = Result("noise"), Result("lnm")
    assert session.add_result(r1) == "R1" and session.add_result(r2) == "R2"
    assert session.get_result("R2") is r2
    session.remove_result("R1")
    assert [r.name for r in session.results] == ["R2"]
    r3 = Result("sinad")
    session.add_result(r3)
    assert r3.name == "R3"  # names are never reused
    session.rename_signal("S1", "noise1")
    session.touch()
    assert session.version > v0
    kinds = [e for e, _ in events]
    assert kinds[:3] == ["signal_added", "result_added", "result_added"]
    assert "result_removed" in kinds and "changed" in kinds
    with pytest.raises(ParameterError, match="Unknown result"):
        session.get_result("R9")
    unsubscribe()
    n = len(events)
    session.touch()
    assert len(events) == n


def test_default_session_reaches_worker_threads():
    session = Session(config=Config())
    set_session(session, default=True)
    seen = []
    thread = threading.Thread(target=lambda: seen.append(get_session()))
    thread.start()
    thread.join()
    assert seen == [session]


def test_param_origins_follow_the_precedence():
    decl = [Param("fmax", float, 100.0), Param("full_scale", float, 2**24,
                                               from_signal="full_scale"),
            Param("mains_freq", float, 50.0), Param("window", str, "hann")]
    sig = make_noise(1.0, bits=16, seed=1, duration=1)
    config = Config({"analysis": {"mains_freq": 60.0}})
    origins = param_origins(decl, {"fmax": 20}, sig, config)
    assert origins == {"fmax": "call", "full_scale": "signal", "mains_freq": "config",
                       "window": "default"}


# ---------------------------------------------------------------------------------- display
def test_decimation_keeps_spikes_and_narrow_lines():
    rng = np.random.default_rng(0)
    y = rng.normal(0.0, 1.0, 1_000_000)
    y[123_457] = 40.0
    idx = envelope_indices(y.size, y, 500)
    assert idx.size <= 1002 and 123_457 in idx
    assert idx[0] == 0 and idx[-1] == y.size - 1  # the curve spans the whole record
    f = np.linspace(0.0, 500.0, 200_001)
    p = rng.normal(-140.0, 3.0, f.size)
    p[77_777] = -60.0
    x, yd = decimate_xy(f, p, 800, "log")
    assert x.size <= 1600 and np.all(x > 0) and yd.max() == -60.0
    assert x[np.argmax(yd)] == f[77_777]
    small_x, small_y = decimate_xy(np.arange(1.0, 11.0), np.arange(10.0), 100, "log")
    assert small_x.size == 10
    assert window_stats(np.array([1.0, 3.0]))["pp"] == 2.0


# ---------------------------------------------------------------------------------- console
@pytest.fixture
def console(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    con = OnTheSignalConsole(config=Config(), ask=lambda label, d: "", forms=False)
    con.execute("S1 = make_noise(2.0, bits=16, seed=1, duration=10)")
    return con


def test_console_names_results_and_answers_help_queries(console, capsys):
    console.execute("noise(S1, show=False)")
    assert "R1" in console.ns and console.ns["R1"] is console.session.results[0]
    console.execute("x = R1['rms'] * 2")
    assert console.ns["x"] == pytest.approx(2 * console.session.results[0]["rms"])
    console.execute("noise?")
    out = capsys.readouterr().out
    assert "noise(" in out and "fmax" in out


def test_console_hooks_for_the_web(console):
    questions, forms = [], []
    console.ai_handler = questions.append
    console.execute("/ai is S1 below the NLNM?")
    assert questions == ["is S1 below the NLNM?"]
    console.forms = True

    def form(cmd, signals, defaults):
        forms.append((cmd.name, [s.name for s in signals], defaults["fmax"]))
        return {"fmax": 25.0}

    console.param_form = form
    console.execute("/noise S1")
    assert forms == [("noise", ["S1"], 100.0)]
    assert console.session.results[-1].params["fmax"] == 25.0
    console.param_form = lambda *a: None
    n = len(console.session.results)
    console.execute("/noise S1")  # cancelled form: no result
    assert len(console.session.results) == n


def test_config_display_tolerates_keys_outside_sections(console, capsys):
    console.session.config.data["theme"] = "light"  # key of another program
    console.execute("/config")
    assert "theme = 'light'" in capsys.readouterr().out


# ---------------------------------------------------------------------------------- layouts
def test_every_layout_refers_to_existing_curves_and_values(results):
    optional = {"dynamic": {"dr"}}  # dynamic range only with a noise record (§7.5)
    for kind, result in results.items():
        for title, spec in figure_specs(result):
            for key in spec.curve_keys():  # a curve, or a trace kept in Result.extra
                assert len(result_curve(result, key).x), (kind, title, key)
            for key in spec.results.headline:
                assert key in result.values or key in optional.get(kind, ()), (kind, key)
            view = results_view(result, spec.results)
            shown = [r["key"] for g in view["groups"] for r in g["rows"]]
            assert len(shown) == len(set(shown)), (kind, "duplicated rows")
            expected = {k for k in result.values
                        if not (k.endswith("_phys") and k[:-5] in result.values)}
            assert set(shown) == expected, (kind, expected - set(shown))
            spec.to_dict()  # serializable


def test_sine_layouts_carry_conditions_and_removed_mains(results):
    sinad = figure_spec(results["sinad"])
    spectrum = sinad.panels[-1]
    assert spectrum.x.scale == "log"
    assert any("removed" in line for line in spectrum.conditions)
    assert [m.x for m in spectrum.markers if m.kind == "removed_mains"] == [50.0, 100.0]
    assert sinad.panels[0].sync == sinad.panels[1].sync == "t" and spectrum.sync == ""
    sfdr = figure_spec(results["sfdr"])
    assert any("spur search" in line for line in sfdr.panels[0].conditions)
    assert {m.kind for m in sfdr.panels[0].markers} >= {"fundamental", "spur"}
    thd = figure_spec(results["thd"])
    labels = [m.label for m in thd.panels[0].markers if m.kind == "harmonic"]
    assert labels[:2] == ["H2", "H3"]
    assert results_view(results["thd"])["tables"][0]["name"] == "harmonics"
    tabs = [t for t, _ in figure_specs(results["dynamic"])]
    assert tabs == ["Summary", "SINAD", "SFDR", "THD"]
    sfdr_tab = figure_specs(results["dynamic"])[2][1]
    assert any("spur search" in line for line in sfdr_tab.panels[0].conditions)


def test_lnm_and_noise_layouts(results):
    lnm = figure_spec(results["lnm"])
    assert [p.id for p in lnm.panels] == ["psd", "diff"]
    assert lnm.panels[0].x.label == "Frequency" and not lnm.panels[0].x.reciprocal
    assert "nhnm" not in lnm.curve_keys()
    assert lnm.panels[1].series[0].fill_negative
    assert lnm.results.headline == ["diff_max", "freq_max", "below_nlnm"]
    dsp = results_view(results["noise_dsp"])
    assert [h["key"] for h in dsp["headline"]] == ["rms", "rms_psd", "dr", "enob"]
    assert dsp["headline"][0]["physical"].endswith("V")
    # noise: the band-limited noise above the results (§7.4), kept out of the JSON
    noise = results["noise"]
    spec = figure_spec(noise)
    (trace,) = spec.panels
    assert trace.id == "trace" and trace.y.unit == "V" and trace.x.time_origin.endswith("Z")
    rms = noise["rms_phys"]
    assert sorted(h.y for h in trace.hlines) == pytest.approx([-rms, rms])
    assert figure_refs(spec) == {"rms", "pp"}
    curve = result_curve(noise, "trace")
    assert curve.x.size == noise["npts"] and np.std(curve.y) == pytest.approx(rms, rel=1e-4)
    assert "trace" not in noise.to_json() and len(noise.to_json()) < 20_000


def test_spectrogram_layout_is_an_interactive_heatmap(results):
    spec = figure_spec(results["spectrogram"])
    assert not spec.static
    signal, image = spec.panels
    assert (signal.id, image.id) == ("signal", "spectrogram")
    assert signal.sync == image.sync == "t" and image.heatmap is not None
    heat = image.heatmap
    assert heat.label.startswith("dB re 1") and heat.vmin < heat.vmax
    assert image.x.factor == 86400.0 and image.x.time_origin.endswith("Z")
    assert heat.x0 < heat.x1 and image.x.min <= heat.x0 and image.x.max >= heat.x1
    assert image.y.min == 0.0 and heat.y0 < 0.0  # cells keep their edges, the axis starts at 0
    assert signal.x.min == image.x.min and signal.x.max == image.x.max


def test_comparison_overlays_results_with_the_colors_of_their_signals(results):
    s = _signals()
    lnm = get_command("lnm").func
    vel2 = make_noise(8.0, bits=24, seed=4, duration=1200, fs=100.0)
    vel2.unit, vel2.sensitivity = "m/s", 1.59e-9
    a, b = lnm(s["vel"]), lnm(vel2)
    a.name, b.name = "R1", "R2"
    spec = comparison_spec([a, b], ["series:0", "series:3"])
    top, diff = spec.panels
    assert [x.curve for x in top.series] == ["0/psd_smooth", "1/psd_smooth", "0/nlnm"]
    assert [x.color for x in top.series[:2]] == ["series:0", "series:3"]
    assert [x.curve for x in diff.series] == ["0/diff", "1/diff"]
    assert not any(x.fill_negative for x in diff.series)
    assert top.series[0].label.startswith("R1 · ")
    view = comparison_view([a, b], spec.results)
    assert view["groups"][0]["title"] == "Key figures"
    assert all(len(r["values"]) == 2 for g in view["groups"] for r in g["rows"])
    keys = [r["key"] for g in view["groups"] for r in g["rows"]]
    assert len(keys) == len(set(keys))
    sinad = comparison_spec([results["sinad"], results["sinad"]], ["series:0", "series:1"])
    assert [p.id for p in sinad.panels] == ["residual_spectrum"]
    assert any("removed" in line for line in sinad.panels[0].conditions)
    with pytest.raises(ParameterError, match="same analysis"):
        comparison_spec([a, results["noise_dsp"]], ["series:0", "series:1"])
    with pytest.raises(ParameterError, match="side by side"):
        comparison_spec([results["spectrogram"]] * 2, ["series:0", "series:1"])
    counts = get_command("noise_dsp").func(s["sine"])
    with pytest.raises(ParameterError, match="different units"):
        comparison_spec([results["noise_dsp"], counts], ["series:0", "series:1"])
    table_only = comparison_spec([results["noise"], get_command("noise").func(s["sine"])],
                                 ["series:0", "series:1"])
    assert table_only.panels == []


def test_generic_layout_for_script_results():
    from onthesignal.core.result import Curve, Result

    r = Result("my_script", title="Custom")
    r.curves["a"] = Curve(np.arange(5.0), np.arange(5.0), "a", "Time", "Amplitude", "s", "V")
    r.curves["b"] = Curve(np.arange(5.0), np.ones(5), "b", "Time", "Amplitude", "s", "V")
    r.curves["c"] = Curve(np.arange(5.0), np.ones(5), "c", "Time", "Ratio", "s", "")
    r.add("value", 1.5, "V", "Value")
    spec = figure_spec(r)
    assert [len(p.series) for p in spec.panels] == [2, 1]
    assert results_view(r)["groups"][0]["title"] == "Values"
    assert get_command("noise").name == "noise"


def test_console_records_changes_of_the_samples(console):
    sig = console.session.signals["S1"]
    version = sig.data_version
    console.execute("S1.data[:10] = 0")  # in place: found by comparing checksums
    assert sig.data_version == version + 1 and sig.history[-1] == "samples modified"
    console.execute("S1.data = S1.data + 5")
    assert sig.data_version == version + 2
    console.execute("n = S1.npts")  # reading changes nothing
    assert sig.data_version == version + 2
    console.execute("S2 = S1 + 3")
    assert console.session.signals["S2"].history[-1] == "offset +3 counts"


def test_sds_day_files_are_recognized_by_their_content(tmp_path):
    """The day files of an SDS archive (NET.STA.LOC.CHA.D.YEAR.DAY) have no .mseed
    extension: they are loaded as signals, not opened as text."""
    from obspy import Stream, Trace, UTCDateTime

    from onthesignal.io import SDS_NAME, detect_format, is_miniseed, is_signal_file, read

    tr = Trace(np.arange(1000, dtype=np.int32),
               header={"network": "XX", "station": "LORA", "location": "HA", "channel": "BHE",
                       "sampling_rate": 250.0, "starttime": UTCDateTime(2026, 9, 21)})
    sds = tmp_path / "XX.LORA.HA.BHE.D.2026.264"
    Stream([tr]).write(str(sds), format="MSEED", encoding="INT32")
    notes = tmp_path / "notes.264"
    notes.write_text("Bench 3, shorted input\n", encoding="utf-8")
    assert SDS_NAME.match(sds.name) and not SDS_NAME.match(notes.name)
    assert is_miniseed(sds) and is_signal_file(sds) and detect_format(sds) == "mseed"
    assert not is_miniseed(notes) and not is_signal_file(notes)
    assert detect_format(notes) == "obspy" and not is_signal_file(tmp_path / "missing.264")
    assert is_signal_file(tmp_path / "a.mseed") and not is_signal_file(tmp_path / "s.py")
    (sig,) = read(sds)
    assert sig.npts == 1000 and sig.id == "XX.LORA.HA.BHE" and sig.sampling_rate == 250.0
    assert sig.title == "XX.LORA.HA.BHE.D.2026.264"  # the day of the year is not an extension
