"""Web interface without a browser: security, data sent to the charts, shared state, terminal.

The end-to-end tests with a real browser are in ``test_web_e2e.py`` (opt-in).
"""

from __future__ import annotations

import os
import threading
import time

import numpy as np
import pytest

pytest.importorskip("nicegui")

from obspy import UTCDateTime  # noqa: E402

from onthesignal.cli.console import OnTheSignalConsole  # noqa: E402
from onthesignal.core.config import Config  # noqa: E402
from onthesignal.core.result import Curve, Result  # noqa: E402
from onthesignal.core.session import Session, set_session  # noqa: E402
from onthesignal.plot.spec import Axis, Panel, Series  # noqa: E402
from onthesignal.synthetic import make_noise  # noqa: E402
from onthesignal.web.app import _socketio_origins, parse_args  # noqa: E402
from onthesignal.web.figures import (  # noqa: E402
    align,
    array_figure,
    panel_data,
    signal_figure,
    signal_payload,
)
from onthesignal.web.security import OriginGuard, confine, safe_name  # noqa: E402
from onthesignal.web.state import WebState, describe_variable  # noqa: E402


def wait(condition, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------------------------- security
@pytest.fixture
def guarded():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route, WebSocketRoute
    from starlette.testclient import TestClient

    async def home(request):
        return PlainTextResponse("ok")

    async def socket(ws):
        await ws.accept()
        await ws.send_text("hello")
        await ws.close()

    app = Starlette(routes=[Route("/", home), Route("/_ots/reports/r.html", home),
                            WebSocketRoute("/ws", socket)])
    app.add_middleware(OriginGuard, bind_host="127.0.0.1", allowed_hosts=["bench-pc"])
    return TestClient(app, base_url="http://127.0.0.1:8080")


def test_origin_guard_refuses_foreign_hosts_and_origins(guarded):
    ok = guarded.get("/")
    assert ok.status_code == 200
    assert "frame-ancestors 'self'" in ok.headers["content-security-policy"]
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert guarded.get("/", headers={"Host": "bench-pc:8080"}).status_code == 200
    assert guarded.get("/", headers={"Host": "evil.example"}).status_code == 403  # rebinding
    assert guarded.get("/", headers={"Origin": "http://evil.example"}).status_code == 403
    assert guarded.get("/", headers={"Origin": "http://127.0.0.1:8080"}).status_code == 200
    report = guarded.get("/_ots/reports/r.html")
    assert "data:" in report.headers["content-security-policy"]
    host = {"Host": "127.0.0.1:8080"}  # the test client sends "testserver" for WebSockets
    with guarded.websocket_connect("/ws", headers={**host, "Origin": "http://127.0.0.1:8080"}
                                   ) as ws:
        assert ws.receive_text() == "hello"
    from starlette.websockets import WebSocketDisconnect

    for headers in ({**host, "Origin": "http://evil.example"}, {"Host": "evil.example"}):
        with pytest.raises(WebSocketDisconnect):
            with guarded.websocket_connect("/ws", headers=headers) as ws:
                ws.receive_text()


def test_paths_are_confined_to_the_project(tmp_path):
    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("x")
    os.symlink(tmp_path / "secret.txt", project / "link.txt")
    assert confine("data", [project]) == (project / "data").resolve()
    for bad in ("../secret.txt", "../../etc/passwd", "link.txt", str(tmp_path / "secret.txt")):
        with pytest.raises(PermissionError):
            confine(bad, [project])
    assert safe_name("../../evil?.mseed") == "evil.mseed"
    assert safe_name("..") == "upload"


def test_launch_options_and_socketio_origins():
    args = parse_args(["a.mseed", "--port", "9000", "--no-browser"])
    assert args.files == ["a.mseed"] and args.port == 9000 and args.no_browser
    origins = _socketio_origins("127.0.0.1", 9000, [])
    assert "http://127.0.0.1:9000" in origins and "http://localhost:9000" in origins
    assert "http://[::1]:9000" in origins
    assert _socketio_origins("0.0.0.0", 9000, []) == "*"


# ---------------------------------------------------------------------------------- figures
def test_align_and_panel_data():
    out = align([(np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0, 30.0])),
                 (np.array([2.0, 4.0]), np.array([5.0, np.nan]))])
    assert out["x"] == [1.0, 2.0, 3.0, 4.0]
    assert out["series"] == [[10.0, 20.0, 30.0, None], [None, 5.0, None, None]]
    r = Result("x")
    r.curves["psd"] = Curve(np.array([0.0, 0.1, 1.0, 10.0]), np.array([1.0, 2.0, 3.0, 4.0]))
    period = Panel("p", Axis("Period", "s", "log", reciprocal=True), Axis(), [Series("psd")])
    data = panel_data(r, period)
    assert data["x"] == [0.1, 1.0, 10.0]  # 1/f, increasing, f = 0 dropped
    assert data["series"][0] == [4.0, 3.0, 2.0]


def test_signal_payload_windows_and_statistics():
    a = make_noise(1.0, bits=16, seed=1, duration=10, fs=100.0)
    b = make_noise(1.0, bits=16, seed=2, duration=10, fs=100.0)
    a.name, b.name = "A", "B"
    b.starttime = a.starttime + 2.0
    spec = signal_figure([a, b], units="counts", stacked=False)
    assert spec.panels[0].x.time_origin.startswith(str(a.starttime.year))
    data, stats = signal_payload([a, b], spec, "counts", t0=3.0, t1=4.0)
    assert stats["A"]["n"] == 101 and stats["B"]["n"] == 101
    assert stats["B"]["start"] == pytest.approx(3.0)
    x = [v for v in data["overlay"]["x"] if v is not None]
    assert min(x) >= 3.0 - 1e-9 and max(x) <= 4.0 + 1e-9
    full, _ = signal_payload([a], signal_figure([a]), "counts")
    assert len(full[a.name]["x"]) == a.npts  # 1000 samples: no decimation
    spec_array, arrays = array_figure("v", np.arange(5.0))
    assert arrays["array"]["series"][0] == [0.0, 1.0, 2.0, 3.0, 4.0]


# ---------------------------------------------------------------------------------- state
@pytest.fixture
def state(tmp_path, monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    monkeypatch.chdir(tmp_path)
    config = Config({"console": {"history_file": str(tmp_path / "history")}})
    session = Session(config=config, interactive=True)
    set_session(session, default=True)
    web = WebState(session, str(tmp_path))
    web.terminal.start()
    yield web
    web.terminal.stop()


def test_display_routes_results_to_the_requesting_tab(state):
    tab_a, tab_b = state.connect("a"), state.connect("b")
    sig = make_noise(1.0, bits=16, seed=1, duration=5)
    state.session.add_signal(sig)
    from onthesignal import api

    job = state.jobs.start("noise", lambda job: api.run("noise_dsp", "S1", show=True),
                           client="a")
    assert wait(lambda: job.state == "done")
    opened_a = [e for e in tab_a.drain() if e["type"] == "open"]
    assert opened_a == [{"type": "open", "what": "result", "name": "R1"}]
    assert not [e for e in tab_b.drain() if e["type"] == "open"]
    state.terminal.submit("noise(S1)")  # from the terminal: every tab opens it
    assert wait(lambda: len(state.session.results) == 2)
    assert wait(lambda: any(e.get("name") == "R2" for e in tab_b.drain()))


def test_requests_wait_for_the_browser_answer(state):
    tab = state.connect("a")
    answers = []
    thread = threading.Thread(target=lambda: answers.append(
        state.requests.ask({"type": "confirm", "question": "Allow?"}, client="a")))
    thread.start()
    assert wait(lambda: bool(tab.queue))
    event = tab.drain()[0]
    assert event["type"] == "confirm" and event["question"] == "Allow?"
    state.requests.answer(event["request"], True)
    thread.join(5)
    assert answers == [True]


def test_terminal_form_request_runs_the_analysis(state):
    tab = state.connect("a")
    state.session.add_signal(make_noise(1.0, bits=16, seed=1, duration=5))
    state.terminal.submit("/noise S1")
    assert wait(lambda: any(e["type"] == "form" for e in list(tab.queue)))
    form = next(e for e in tab.drain() if e["type"] == "form")
    assert form["command"] == "noise" and form["signals"] == ["S1"]
    state.requests.answer(form["request"], {"fmax": 20.0})
    assert wait(lambda: len(state.session.results) == 1)
    assert state.session.results[0].params["fmax"] == 20.0


def test_variables_figures_and_terminal_output(state, monkeypatch):
    import matplotlib.pyplot as plt

    monkeypatch.setattr(plt, "show", lambda *a, **k: state.capture_figures())  # as the app
    plt.close("all")  # figures left open by other tests
    out = []
    state.terminal.on_output.append(out.append)
    state.terminal.submit("import matplotlib.pyplot as plt\nv = np.arange(4.0)\nn = 3\n"
                          "plt.plot(v)\nplt.title('ramp')\nplt.show()\nprint('done', n)")
    assert wait(lambda: "done 3" in "".join(out))
    names = {v.name: v for v in state.variables}
    assert {"v", "n", "plt"} - {"plt"} <= set(names)
    assert names["v"].kind == "array1d" and "noise" not in names and "np" not in names
    assert [f.title for f in state.figures] == ["ramp"]
    assert state.figures[0].png[:4] == b"\x89PNG"
    assert describe_variable("_hidden", 1) is None
    assert describe_variable("d", {"a": 1}).kind == "mapping"


def test_terminal_engine_interrupts_and_names(state):
    out = []
    state.terminal.on_output.append(out.append)
    state.terminal.feed("S5 = make_noise(1.0, bits=16, seed=1, duration=2)\r")
    assert wait(lambda: "S5" in state.session.signals)
    state.terminal.feed("for i in range(2):\r")
    state.terminal.feed("print('loop', i)\r\r")
    assert wait(lambda: "loop 1" in "".join(out))
    state.terminal.feed("k = 0\r")
    state.terminal.feed("while True: k += 1\r")
    assert wait(lambda: state.terminal.busy, 5)
    time.sleep(0.2)
    state.terminal.feed("\x03")
    assert wait(lambda: not state.terminal.busy, 5)
    assert "Interrupted" in "".join(out)
    replay = state.terminal.scrollback()
    assert "loop 1" in replay


# ---------------------------------------------------------------------------------- console
def test_assigned_signals_take_the_variable_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    console = OnTheSignalConsole(config=Config(), ask=lambda label, d: "", forms=False)
    console.execute("S5 = make_noise(1.0, bits=16, seed=1, duration=1)")
    assert list(console.session.signals) == ["S5"]
    console.execute("x = S5")  # an alias keeps the name
    console.execute("make_sine(bits=16, duration=1)")
    assert list(console.session.signals) == ["S5", "S1"]
    assert UTCDateTime(0) is not None


def test_rename_and_remove_keep_the_terminal_in_step(state):
    state.session.add_signal(make_noise(1.0, bits=16, seed=1, duration=2))
    state.terminal.submit("x = 1")
    assert wait(lambda: "S1" in state.terminal.console.ns)
    state.rename_signal("S1", "noise1")
    assert list(state.session.signals) == ["noise1"]
    state.terminal.submit("y = noise1.npts")
    assert wait(lambda: state.terminal.console.ns.get("y") == 2000)
    state.remove_signal("noise1")
    state.terminal.submit("z = 2")
    assert wait(lambda: state.terminal.console.ns.get("z") == 2)
    assert state.session.signals == {}  # not brought back by the terminal namespace


def test_code_execution_can_be_disabled(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from onthesignal.web.state import Channel
    from onthesignal.web.ui.chat import ChatHost

    monkeypatch.chdir(tmp_path)
    config = Config({"web": {"code_execution": False},
                     "console": {"history_file": str(tmp_path / "history")}})
    session = Session(config=config, interactive=True)
    web = WebState(session, str(tmp_path))
    assert web.code_execution is False and web.terminal.thread_ident is None
    channel = Channel()
    host = ChatHost(SimpleNamespace(state=web, id="a", channel=channel))  # type: ignore[arg-type]
    assert host.confirm("The assistant wants to run run_script(...). Allow?") is False
    note = channel.drain()[0]
    assert note["kind"] == "note" and "code_execution" in note["text"]


def test_journal_and_recent_files(state, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="onthesignal.web"):
        state.log("files", "deleted data/old.mseed")
    assert "[files] deleted data/old.mseed" in caplog.text
    for name in ("a.mseed", "b.mseed", "a.mseed"):
        state.remember_file(name)
    assert state.recent_files == ["a.mseed", "b.mseed"]


# ---------------------------------------------------------------------------------- lot W8
def _levels(heat: dict) -> np.ndarray:
    import base64

    q = np.frombuffer(base64.b64decode(heat["values"]), dtype="<u2")
    q = q.reshape(heat["rows"], heat["cols"]).astype(float)
    return np.where(q == 65535, np.nan, heat["zmin"] + q / 65534 * (heat["zmax"] - heat["zmin"]))


def _row_centres(heat: dict) -> np.ndarray:
    if heat["log"]:
        edges = np.geomspace(heat["y0"], heat["y1"], heat["rows"] + 1)
        return np.sqrt(edges[:-1] * edges[1:])
    edges = np.linspace(heat["y0"], heat["y1"], heat["rows"] + 1)
    return (edges[:-1] + edges[1:]) / 2


@pytest.mark.parametrize("yscale", ["linear", "log"])
def test_spectrogram_heatmap_keeps_the_line_and_the_levels(state, yscale):
    from onthesignal import api
    from onthesignal.plot.layouts import figure_spec
    from onthesignal.web.figures import HEATMAP_MAX, figure_payload

    sig = api.make_sine(7.3, bits=24, seed=1, duration=60, fs=200.0)
    result = api.spectrogram(sig, show=False, yscale=yscale)
    payload = figure_payload(result, figure_spec(result))
    heat = payload["data"]["spectrogram"]["heatmap"]
    z = _levels(heat)
    assert heat["cols"] <= HEATMAP_MAX[0] and heat["rows"] <= HEATMAP_MAX[1]
    assert not np.isnan(z).any()
    line = _row_centres(heat)[np.argmax(z.mean(axis=1))]
    assert line == pytest.approx(7.3, abs=1.0)  # frequency resolution 1.56 Hz
    image = result.extra["image"]
    assert z.max() == pytest.approx(float(np.max(image["z"])), abs=0.01)
    assert heat["vmin"] == pytest.approx(image["vmin"]) and heat["log"] == (yscale == "log")


def test_comparison_payload_and_stable_signal_colors(state):
    from onthesignal import api
    from onthesignal.plot.layouts import comparison_spec
    from onthesignal.web.figures import figure_payload

    a = api.make_noise(1.0, bits=16, seed=1, duration=20)
    b = api.make_noise(2.0, bits=16, seed=2, duration=20)
    r1, r2 = api.noise_dsp(a, show=False), api.noise_dsp(b, show=False)
    assert state.color_of("S2") == "series:1" and state.color_of("S1") == "series:0"
    spec = comparison_spec([r2, r1], [state.result_color(r2), state.result_color(r1)])
    assert [s.color for s in spec.panels[0].series] == ["series:1", "series:0"]
    data = figure_payload([r2, r1], spec)["data"]["psd"]
    assert len(data["series"]) == 2 and len(data["x"]) > 100
    state.rename_signal("S1", "adc1")
    assert state.color_of("adc1") == "series:0"  # the color follows the renamed signal
    assert state.color_of("S9") == "series:2"


class _FakeConn:
    def __init__(self) -> None:
        self.terminate_flag = False

    def terminate(self) -> None:
        self.terminate_flag = True


class _FakeSeedLink:
    """SeedLink client of two channels sending one-second records of a 5 Hz sine plus noise:
    a backlog of 20 records, then one record every 20 ms until terminated."""

    XML = ('<?xml version="1.0"?><seedlink><station name="SN270" network="RD">'
           '<stream location="00" seedname="FHZ"/><stream location="00" seedname="FHN"/>'
           '</station></seedlink>')

    def __init__(self, url, on_data) -> None:
        self.on_data, self.conn = on_data, _FakeConn()

    def get_info(self, level):
        return self.XML

    def select_stream(self, *args) -> None:
        pass

    def run(self) -> None:
        from obspy import Trace

        t0 = UTCDateTime() - 20
        rng = np.random.default_rng(1)
        n = np.arange(100) / 100.0
        i = 0
        while not self.conn.terminate_flag:
            for channel in ("FHZ", "FHN"):
                data = rng.normal(0, 100, 100) + 5000 * np.sin(2 * np.pi * 5 * n)
                self.on_data(Trace(data.astype(np.int32), header={
                    "network": "RD", "station": "SN270", "location": "00", "channel": channel,
                    "sampling_rate": 100.0, "starttime": t0 + i}))
            i += 1
            time.sleep(0.002 if i < 20 else 0.02)

    def close(self) -> None:
        pass


def test_realtime_run_publishes_statistics_trace_and_spectra(state, tmp_path):
    from onthesignal.web.realtime import RealtimeSettings

    state.seedlink_factory = _FakeSeedLink
    tab = state.connect("a")
    streams = state.list_streams("fake", 18000, "RD", "SN270")
    assert [s[3] for s in streams] == ["FHN", "FHZ"]
    sensitivity = 40 / 2**24
    run = state.start_realtime(RealtimeSettings(
        "fake", streams, 18000, window=5, spectral_window=10, trace_seconds=8, refresh=0.1,
        spectra_refresh=0.2, sensitivity=sensitivity, unit="V"), client="a")
    with pytest.raises(Exception, match="already running"):
        state.start_realtime(RealtimeSettings("fake", streams))
    assert wait(lambda: run.view.spectra_version >= 2)
    view = run.view
    assert view.stats[0]["rate"] == "100 Hz" and "mV" in view.stats[0]["std"]
    trace = view.trace["ch0"]
    assert len(trace["x"]) == 800  # 8 s at 100 Hz, below the decimation threshold
    assert trace["x"][-1] - trace["x"][0] == pytest.approx(7.99)
    f = np.array(view.fft["spectrum"]["x"])
    a = np.array([np.nan if v is None else v for v in view.fft["spectrum"]["series"][0]])
    assert f[np.nanargmax(a)] == pytest.approx(5.0, abs=0.1)
    assert np.nanmax(a) == pytest.approx(5000 * sensitivity, rel=0.02)
    assert run.spectrum_figure("dsp").panels[0].y.unit == "dB re 1 V²/Hz"
    run.set_recording(tmp_path / "rec")
    assert wait(lambda: any((tmp_path / "rec").glob("*.mseed")), 5)
    run.set_recording(None)
    run.stop()
    assert wait(lambda: run.state == "stopped")
    assert any(e["type"] == "realtime" for e in tab.drain())


def test_batch_run_follows_files_and_keeps_errors(state, tmp_path):
    from onthesignal.web.batch import BatchSettings

    (tmp_path / "data").mkdir()
    for i in range(3):
        make_noise(1.0 + i, bits=16, seed=i, duration=5).save(tmp_path / "data" / f"n{i}.mseed")
    (tmp_path / "data" / "bad.mseed").write_bytes(b"not a miniSEED file")
    run = state.start_batch(BatchSettings("noise", ["data/*.mseed"], {"fmax": 20.0}, {},
                                          "results/batch.csv"))
    assert wait(lambda: not run.running, 30)
    assert (run.state, run.done, run.total, len(run.rows), run.failures) == ("done", 4, 4, 4, 1)
    assert run.out is not None and run.out.read_text().startswith("file,signal")
    columns, rows = run.table()
    assert columns[0]["name"] == "file" and rows[0]["file"] == "bad.mseed"
    assert "rms (counts)" in [c["label"] for c in columns]
    assert run.rows[1]["band"] == [0.0, 20.0]  # the parameters of the form are applied
    assert 0 < run.summary().tables["batch"][1]["rms [counts]"] < 1.0
    with pytest.raises(Exception, match="outside the project"):
        state.start_batch(BatchSettings("noise", ["/etc/pass*"]))


def test_acquisition_is_kept_by_the_server(state, tmp_path):
    state.seedlink_factory = _FakeSeedLink
    streams = state.list_streams("fake", 18000, "RD", "SN270")
    job = state.start_acquisition("fake", streams[:1], 18000, 1.0, tmp_path, load=True)
    assert state.acquisition is not None  # a reloaded page finds it in the state (W-12)
    with pytest.raises(Exception, match="already running"):
        state.start_acquisition("fake", streams, 18000, 1.0, tmp_path, load=False)
    assert wait(lambda: job.state != "running", 30)
    assert job.state == "done" and state.acquisition is None
    assert state.acquisition_progress is not None and state.session.signals


# ---------------------------------------------------------------------------------- overlays, PWA
def test_overlay_of_signals_in_different_units_warns():
    a = make_noise(1.0, bits=16, seed=1, duration=2)
    b = make_noise(1.0, bits=16, seed=2, duration=2)
    a.name, b.name = "S1", "S2"
    a.unit, a.sensitivity = "V", 1e-6
    spec = signal_figure([a, b], "physical", stacked=False, colors={"S1": "series:3"})
    (panel,) = spec.panels
    assert [s.color for s in panel.series] == ["series:3", "series:1"]
    assert panel.y.unit == "" and "different units" in spec.note
    assert "(V)" in panel.series[0].label
    counts = signal_figure([a, b], "counts", stacked=False)
    assert counts.note == "" and counts.panels[0].y.unit == "counts"


def test_pwa_manifest_service_worker_and_icons():
    from PIL import Image

    from onthesignal.web import pwa

    manifest = pwa.manifest()
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])
    for icon in manifest["icons"]:
        path = pwa.PWA_DIR / icon["src"].rsplit("/", 1)[1]
        assert Image.open(path).size == tuple(int(n) for n in icon["sizes"].split("x"))
    assert (pwa.PWA_DIR / "offline.html").is_file()
    assert f"{pwa.PWA_URL}/offline.html" in pwa.SERVICE_WORKER
    head = pwa.head_html()
    assert 'rel="manifest"' in head and 'serviceWorker.register("/sw.js")' in head


def test_desktop_launcher_helpers(tmp_path, monkeypatch):
    from onthesignal import desktop

    command = desktop.server_command(tmp_path, 8123, ["a.mseed"])
    assert command[1:4] == ["-m", "onthesignal.cli.main", "web"]
    assert "--no-browser" in command and command[-1] == "a.mseed"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert desktop.default_project(str(tmp_path)) == tmp_path.resolve()
    monkeypatch.chdir(tmp_path)
    assert desktop.default_project(None) == tmp_path.resolve()
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    assert desktop.default_project(None) is None  # launched from the menu: ask
    port = desktop.free_port()
    assert desktop.wait_for(f"http://127.0.0.1:{port}/", timeout=5, alive=lambda: False) is False


# ---------------------------------------------------------------------------------- lot W9
def test_editor_help_from_jedi_and_ruff(tmp_path):
    from onthesignal.web import code

    namespace = {"S1": make_noise(1.0, bits=16, seed=1, duration=1)}
    labels = [i["label"] for i in code.complete("x = S1.", 1, 7, namespace)]
    assert "sensitivity" in labels and "lnm" in labels
    assert not any(label.startswith("_") for label in labels)  # private names when typed
    from onthesignal import api

    signature = code.signature("api.noise(S1, ", 1, 14, {**namespace, "api": api})
    assert signature["label"].startswith("noise(") and signature["active"] == 1
    assert "fmax" in " ".join(signature["parameters"])
    assert "noise" in (code.hover("api.noise", 1, 6, {"api": api}) or "")
    if code.ruff_binary() is None:
        pytest.skip("ruff is not installed")
    markers = code.ruff_markers("import os\nx = noise(S1)\n", tmp_path / "a.py")
    messages = " ".join(m["message"] for m in markers)
    assert "F401" in messages and "F821" in messages
    markers = code.ruff_markers("x = noise(S1)\n", tmp_path / "a.py", defined=["noise", "S1"])
    assert markers == []  # names of the terminal are defined
    assert code.ruff_markers("x = (\n", tmp_path / "a.py")[0]["severity"] == "error"


def test_chat_attachments_history_and_allow_for_this_chat(state, tmp_path):
    from types import SimpleNamespace

    from onthesignal import api
    from onthesignal.web.ui.chat import ChatHost, ChatPanel, chat_markdown

    sig = make_noise(1.0, bits=16, seed=1, duration=5)
    state.session.add_signal(sig)
    api.noise("S1", show=False)
    (tmp_path / "context.md").write_text("Bench 3, shorted input.\n")
    channel = state.connect("a")  # the browser tab that receives the questions
    wb = SimpleNamespace(state=state, id="a", channel=channel, root=tmp_path,
                         roots=[tmp_path])
    panel = ChatPanel(wb)  # type: ignore[arg-type]
    names, block = panel.attachments("Compare @S1 with @R1, see @context.md and @nothing")
    assert names == ["S1", "R1", "context.md"]
    assert "### S1" in block and "### Result R1" in block and "Bench 3" in block
    assert "samples" in block and "data" not in block.split("summaries")[0][-5:]
    record = {"title": "noise", "created": "2026-11-20", "provider": "ollama", "items": [
        {"kind": "user", "text": "noise of S1?"},
        {"kind": "tool", "name": "noise", "arguments": '{"signal": "S1"}', "ok": True,
         "summary": "rms 1.0"},
        {"kind": "assistant", "text": "The RMS is 1 count."}]}
    text = chat_markdown(record)
    assert "**You:** noise of S1?" in text and "`noise(" in text and "1 count" in text

    host = ChatHost(wb)  # type: ignore[arg-type]
    answers = []
    thread = threading.Thread(target=lambda: answers.append(
        host.confirm("Run the script?", key="run_script")), daemon=True)
    thread.start()
    assert wait(lambda: bool(channel.queue))
    event = channel.drain()[0]
    assert event["key"] == "run_script"
    state.requests.answer(event["request"], "chat")  # "Allow for this chat"
    thread.join(5)
    assert answers == [True]
    assert host.confirm("Run the script again?", key="run_script") is True  # not asked
    notes = [e.get("text", "") for e in channel.drain() if e.get("kind") == "note"]
    assert notes and notes[-1].startswith("Allowed for this chat")


def test_full_scale_levels_plot_function_and_variable_tree(state):
    from onthesignal.synthetic import make_sine
    from onthesignal.web.figures import full_scale_lines
    from onthesignal.web.ui.tabs import _tree_nodes

    loud = make_sine(5.0, ratio=0.9, bits=16, duration=2)  # 90 % of the full scale
    quiet = make_noise(1.0, bits=16, seed=1, duration=2)
    lines = full_scale_lines(loud, "counts")
    assert [line.y for line in lines] == [2.0**15, -(2.0**15)] and lines[0].extend
    assert full_scale_lines(quiet, "counts") == []
    loud.unit, loud.sensitivity = "V", 1e-6
    assert full_scale_lines(loud, "physical")[0].y == pytest.approx(2.0**15 * 1e-6)
    spec = signal_figure([loud], "counts")
    assert spec.panels[0].hlines and spec.panels[0].hlines[0].label == "± full scale / 2"

    tab = state.connect("a")
    x = np.linspace(0, 1, 5000)
    state.plot(x, np.sin(x), np.cos(x), title="trig", labels=["sin", "cos"])
    record = state.figures[-1]
    assert record.spec["title"] == "trig" and record.png == b""
    assert [s["label"] for s in record.spec["panels"][0]["series"]] == ["sin", "cos"]
    assert len(record.data["plot"]["series"]) == 2 and len(record.data["plot"]["x"]) <= 4802
    with pytest.raises(Exception, match="x has 5000 values"):
        state.plot(x, np.zeros(3))
    state.session.add_signal(quiet)
    state.plot(state.session.signals["S1"])
    opened = [e for e in tab.drain() if e["type"] == "open"]
    assert opened[0]["what"] == "figure" and opened[-1] == {
        "type": "open", "what": "signals", "names": ["S1"], "overlay": True}
    state.terminal.submit("plot(np.arange(10.0), title='ramp')")  # from the terminal
    assert wait(lambda: state.figures[-1].title == "ramp")

    nodes = _tree_nodes({"a": [1, 2, {"b": 3}], "c": "text"})
    assert nodes[0]["label"] == "a: list (3)" and nodes[0]["children"][2]["children"][0][
        "label"] == "b: 3"
    assert nodes[1]["label"] == "c: 'text'"


def test_desktop_server_stops_its_whole_process_group(tmp_path, monkeypatch):
    """In the AppImage, python is a shell script running the interpreter as a child: stopping
    the direct child alone left the server running."""
    import sys

    from onthesignal import desktop

    wrapper = tmp_path / "python-wrapper"
    wrapper.write_text(f'#!/bin/bash\n"{sys.executable}" "$@"\n')  # no exec, as python-appimage
    wrapper.chmod(0o755)
    monkeypatch.setattr(desktop, "server_command", lambda project, port, files: [
        str(wrapper), "-m", "http.server", str(port), "--bind", "127.0.0.1"])
    server = desktop.Server(tmp_path, [])
    assert desktop.wait_for(server.url, timeout=20, alive=server.alive)
    group = server.process.pid
    server.stop(timeout=5)
    with pytest.raises(ProcessLookupError):
        os.killpg(group, 0)  # nothing left of the group: the wrapper and the server are gone


def test_ai_script_is_reviewed_in_the_browser_before_it_is_written(state, tmp_path):
    """/ai_script of the web terminal: the proposal opens in a diff view (§9.6); the file is
    written with the accepted text, and not at all when the proposal is refused."""
    from onthesignal.ai import get_assistant
    from onthesignal.ai.providers import Reply

    class Provider:
        name, model, supports_tools = "fake", "fake-1", False

        def chat(self, system, transcript, tools):
            return Reply("```python\nprint('proposal')\n```", [])

    tab = state.connect("a")
    console = state.terminal.console
    console.assistant = get_assistant(console, provider=Provider())
    opened = []
    console.edit_handler = opened.append
    state.terminal.submit('/ai_script demo "print a word"')
    assert wait(lambda: any(e["type"] == "review" for e in list(tab.queue)))
    review = next(e for e in tab.drain() if e["type"] == "review")
    assert review["path"].endswith("demo.py") and review["original"] == ""
    assert "print('proposal')" in review["proposed"] and "Generated by AI" in review["proposed"]
    script = tmp_path / "scripts" / "demo.py"
    assert not script.exists()  # nothing written before the answer
    state.requests.answer(review["request"], "print('edited')\n")
    assert wait(lambda: script.exists())
    assert script.read_text() == "print('edited')\n"
    assert [path.resolve() for path in opened] == [script.resolve()]  # opened in the editor

    state.terminal.submit('/ai_script demo "again"')  # refused: the file is kept
    assert wait(lambda: any(e["type"] == "review" for e in list(tab.queue)))
    review = next(e for e in tab.drain() if e["type"] == "review")
    assert review["original"] == "print('edited')\n"
    state.requests.answer(review["request"], None)
    assert wait(lambda: not state.terminal.busy)
    assert script.read_text() == "print('edited')\n" and len(opened) == 1


def test_chat_formulas_are_drawn_in_mathml():
    from onthesignal.web.mathtext import render, split_math

    html = render("ENOB: $N = (S - 1.76)/6.02$ and\n\n$$\\frac{a}{b}$$\n\nwith \\(x^2\\)")
    assert html.count("<math") == 3 and 'display="block"' in html and "<mfrac>" in html
    text, found = split_math("costs $5 and $10, code `$x$` and ```\n$y$\n```")
    assert not found and "$5" in text and "`$x$`" in text


def test_noise_trace_zoom_and_linked_rows(state):
    from onthesignal.analysis.measures import compute_frequency
    from onthesignal.analysis.noise import compute_noise
    from onthesignal.plot.layouts import figure_refs, figure_spec, results_view
    from onthesignal.synthetic import make_sine

    sig = make_noise(5.0, bits=24, seed=2, duration=120, fs=200.0)
    result = compute_noise(sig)
    spec = figure_spec(result)
    panel = spec.panels[0]
    full = panel_data(result, panel)
    zoomed = panel_data(result, panel, 1200, (50.0, 52.0), 1.0)
    assert full["x"][0] == 0.0 and full["x"][-1] == pytest.approx(119.995)  # ends kept
    assert len(zoomed["x"]) >= 1200 and 47.9 <= zoomed["x"][0] <= 48.0  # full resolution
    view = results_view(result, spec.results)
    refs = {row["key"]: row["ref"] for g in view["groups"] for row in g["rows"]}
    assert refs["rms"] == "rms" and refs["pp"] == "pp" and refs["mean"] == ""
    assert figure_refs(spec) >= {"rms", "pp"}

    freq = compute_frequency(make_sine(7.3, ratio=0.5, bits=16, duration=5, fs=1000.0))
    spec = figure_spec(freq)
    assert [p.id for p in spec.panels] == ["frequencies"]
    (table,) = results_view(freq, spec.results)["tables"]
    assert table["columns"] == ["period", "start_s", "duration_s", "frequency_hz"]
    assert isinstance(table["values"][0][3], float) and len(table["rows"]) == freq["n_periods"]
    assert freq.to_text().count("\n") < 100  # the console shows the first rows only
