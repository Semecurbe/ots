"""Browser end-to-end tests of the web interface (web specification §15.2, P2).

Opt-in: ``ONTHESIGNAL_E2E=1 pytest tests/test_web_e2e.py``. They start ``onthesignal web`` on a
free port in a temporary project and drive the Google Chrome of the machine with Playwright
(``pip install -e ".[e2e]"``; no browser download is needed).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

if os.environ.get("ONTHESIGNAL_E2E") != "1":
    pytest.skip("browser tests are opt-in (ONTHESIGNAL_E2E=1)", allow_module_level=True)
playwright = pytest.importorskip("playwright.sync_api")
if shutil.which("google-chrome") is None and shutil.which("chrome") is None:
    pytest.skip("Google Chrome is needed", allow_module_level=True)

DATA = Path(__file__).resolve().parents[1] / "data" / "adc_noise_shorted.mseed"
#: Project folder of the server of this module (set by the ``server`` fixture).
PROJECT: dict[str, Path] = {}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    project = tmp_path_factory.mktemp("webproject")
    PROJECT["path"] = project
    (project / "data").mkdir()
    shutil.copy(DATA, project / "data" / DATA.name)
    # The history of this test stays in the project, not in the user's history file.
    (project / "onthesignal.toml").write_text(
        f'[console]\nhistory_file = "{project / "history"}"\n', encoding="utf-8")
    port = _free_port()
    log = (project / "server.log").open("w")
    # NiceGUI switches to its own test mode when it sees pytest's variable: hide it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "onthesignal.cli.main", "web", "--project", str(project),
         "--port", str(port), "--no-browser", str(project / "data" / DATA.name)],
        stdout=log, stderr=subprocess.STDOUT, env=env)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(240):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.25)
    else:
        proc.kill()
    if proc.poll() is not None or proc.returncode is not None:
        log.close()
        pytest.fail("the server did not start:\n" + (project / "server.log").read_text()[-3000:])
    yield url
    proc.terminate()
    proc.wait(10)
    log.close()


@pytest.fixture
def page(server):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.errors = []  # type: ignore[attr-defined]
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
        page.goto(server, wait_until="networkidle")
        page.wait_for_selector("text=OBJECTS", timeout=15000)
        yield page
        browser.close()


def _type_in_terminal(page, text: str) -> None:
    page.locator(".ots-term .xterm-helper-textarea").focus()
    page.keyboard.type(text, delay=3)


def test_signal_plot_analysis_and_terminal(page):
    page.get_by_text("S1", exact=True).first.click()
    page.wait_for_selector(".ots-chart canvas", timeout=15000)
    _type_in_terminal(page, "S2 = make_sine(7.3, bits=24, seed=1, duration=20)\n")
    page.wait_for_selector("text=S2", timeout=15000)
    _type_in_terminal(page, "sinad(S2)\n")
    page.wait_for_selector("text=ENOB (full scale)", timeout=20000)
    _type_in_terminal(page, "noise_dsp(S1)\n")
    page.wait_for_selector("text=RMS from PSD integration", timeout=20000)
    assert page.locator(".ots-chart canvas").count() >= 1  # inactive tabs leave the DOM
    assert page.errors == []  # type: ignore[attr-defined]


def test_editor_and_palette(page):
    _type_in_terminal(page, "/edit_script e2e_demo\n")
    page.wait_for_selector(".monaco-editor", timeout=20000)
    page.locator(".monaco-editor .view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type("\ny = 1 +* 2", delay=5)
    page.keyboard.press("Control+s")
    page.wait_for_selector("text=Syntax error", timeout=8000)
    page.locator("header").click()
    page.keyboard.press("/")
    page.wait_for_selector("input[placeholder^='Type a command']", timeout=5000)
    assert page.errors == []  # type: ignore[attr-defined]


def test_online_provider_needs_consent(page):
    page.locator("button:has(i:has-text('tune'))").first.click()
    page.wait_for_selector("text=AI provider for this session", timeout=5000)
    page.get_by_label("Provider").click()
    page.get_by_role("option", name="anthropic").click()
    page.get_by_role("button", name="Apply").click()
    box = page.get_by_placeholder("Ask the assistant", exact=False)
    box.fill("What is the RMS of S1?")
    box.press("Enter")
    page.wait_for_selector("text=Send the session summaries to anthropic?", timeout=5000)
    page.get_by_role("button", name="Cancel").click()
    page.wait_for_selector("text=Not sent: no consent for the online provider", timeout=5000)
    assert page.errors == []  # type: ignore[attr-defined]


def test_spectrogram_map_and_wheel_zoom(page):
    _type_in_terminal(page, "S7 = make_sine(7.3, bits=24, seed=1, duration=60, fs=200.0)\n")
    page.wait_for_selector("text=S7", timeout=15000)
    _type_in_terminal(page, "spectrogram(S7, yscale='log')\n")
    page.wait_for_selector(".ots-readout", timeout=20000)
    over = page.locator(".ots-chart .u-over").nth(1)  # the map, under the time series
    over.scroll_into_view_if_needed()
    box = over.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + 40)
    page.wait_for_selector(".ots-readout:has-text('Hz · ')", timeout=5000)
    assert "dB re 1 counts²/Hz" in page.locator(".ots-readout").first.inner_text()
    page.get_by_text("S1", exact=True).first.click()  # Ctrl + wheel reloads the window
    cell = page.locator("td:right-of(:text('Window (UTC)'))").first
    page.wait_for_selector("td:has-text('Window (UTC)')", timeout=10000)
    before = cell.inner_text()
    box = page.locator(".ots-chart .u-over").first.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.keyboard.down("Control")
    for _ in range(3):
        page.mouse.wheel(0, -200)
    page.keyboard.up("Control")
    page.wait_for_function("(b) => !document.body.innerText.includes(b)", arg=before,
                           timeout=5000)
    assert page.errors == []  # type: ignore[attr-defined]


def test_comparison_and_batch(page):
    _type_in_terminal(page, "S8 = make_noise(1.0, bits=24, seed=8, duration=20)\n")
    _type_in_terminal(page, "S9 = make_noise(3.0, bits=24, seed=9, duration=20)\n")
    page.wait_for_selector("text=S9", timeout=15000)
    _type_in_terminal(page, "a = noise_dsp(S8); b = noise_dsp(S9)\n")
    page.wait_for_selector(".q-item:has-text('noise_dsp S9')", timeout=20000)
    page.locator(".q-item:has-text('noise_dsp S8')").first.click(modifiers=["Control"])
    page.locator(".q-item:has-text('noise_dsp S9')").first.click(modifiers=["Control"])
    page.get_by_role("button", name="Compare", exact=True).click()
    page.wait_for_selector("text=Comparison of 2 noise_dsp results", timeout=15000)
    page.wait_for_selector("th:has-text('· S9')", timeout=5000)
    page.locator(".ots-activity button:has(i:has-text('code'))").first.click()
    page.get_by_role("button", name="New batch…").click()
    page.wait_for_selector("text=1 file(s) match", timeout=10000)
    page.get_by_role("button", name="Run the batch").click()
    page.wait_for_selector("text=table written to results/", timeout=30000)
    page.wait_for_selector("td:has-text('adc_noise_shorted.mseed')", timeout=5000)
    assert page.errors == []  # type: ignore[attr-defined]


def test_chart_toolbar_zoom_pan_back_and_home(page):
    page.get_by_text("S1", exact=True).first.click()
    page.wait_for_selector("td:has-text('Window (UTC)')", timeout=15000)
    cell = page.locator("td:right-of(:text('Window (UTC)'))").first
    box = page.locator(".ots-chart .u-over").first.bounding_box()
    y = box["y"] + box["height"] / 2

    def at(fraction: float) -> float:
        return box["x"] + box["width"] * fraction

    def changed(previous: str) -> str:
        page.wait_for_function("(b) => !document.body.innerText.includes(b)", arg=previous,
                               timeout=8000)
        return cell.inner_text()

    def tool(icon: str):
        return page.locator(f".ots-tool:has(i:has-text('{icon}'))").first

    full = cell.inner_text()
    assert tool("arrow_back").is_disabled()
    page.mouse.move(at(0.4), y)  # zoom mode: drag a range
    page.mouse.down()
    page.mouse.move(at(0.6), y, steps=6)
    page.mouse.up()
    zoomed = changed(full)
    tool("open_with").click()  # pan mode: drag to move
    page.mouse.move(at(0.5), y)
    page.mouse.down()
    page.mouse.move(at(0.3), y, steps=6)
    page.mouse.up()
    moved = changed(zoomed)
    assert moved[-12:] > zoomed[-12:]  # dragged to the left: later times
    tool("arrow_back").click()
    assert changed(moved) == zoomed
    tool("arrow_back").click()
    assert changed(zoomed) == full
    tool("arrow_forward").click()
    assert changed(full) == zoomed
    tool("home").click()
    assert changed(zoomed) == full
    assert page.errors == []  # type: ignore[attr-defined]


SCALES = """() => { const u = getElement(document.querySelector('.ots-chart')).plots[0].u;
    return {x: [u.scales.x.min, u.scales.x.max], y: [u.scales.y.min, u.scales.y.max]}; }"""


def test_overlay_by_check_boxes_and_rectangle_zoom(page):
    _type_in_terminal(page, "S10 = make_sine(2.0, bits=16, seed=1, duration=10, fs=200.0)\n")
    _type_in_terminal(page, "S11 = make_noise(300.0, bits=16, seed=2, duration=10, fs=200.0)\n")
    page.wait_for_selector(".q-item:has(.q-item__label:text-is('S11'))", timeout=15000)

    def row(name: str):
        return page.locator(f".q-item:has(.q-item__label:text-is('{name}'))").first

    row("S10").locator(".q-checkbox").click()
    row("S11").locator(".q-checkbox").click()
    page.get_by_role("button", name="Overlay").click()
    page.wait_for_selector(".q-chip:has-text('S11')", timeout=10000)
    assert page.locator(".ots-chart .u-over").count() == 1  # one panel, two signals
    legend = page.locator(".ots-chart .u-legend").first.inner_text()
    assert "S10 ·" in legend and "S11 ·" in legend
    page.wait_for_timeout(500)
    full = page.evaluate(SCALES)
    box = page.locator(".ots-chart .u-over").first.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.5, steps=8)
    page.mouse.up()
    page.wait_for_timeout(800)
    zoomed = page.evaluate(SCALES)
    assert zoomed["x"][1] - zoomed["x"][0] < 0.5 * (full["x"][1] - full["x"][0])
    assert zoomed["y"][1] - zoomed["y"][0] < 0.5 * (full["y"][1] - full["y"][0])  # rectangle
    _type_in_terminal(page, "S11.data = S11.data + 1000\n")  # the plot follows the samples
    page.wait_for_function("() => [...document.querySelectorAll('tr')].some((r) => "
                           "r.innerText.startsWith('Mean') && r.innerText.includes('1'))",
                           timeout=8000)
    assert page.errors == []  # type: ignore[attr-defined]


def test_installable_as_an_application(server, tmp_path):
    with playwright.sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(tmp_path / "profile"),
                                                       channel="chrome", headless=True)
        page = context.new_page()
        page.goto(server, wait_until="networkidle")
        page.wait_for_selector("text=OBJECTS", timeout=15000)
        assert page.evaluate("async () => (await navigator.serviceWorker.ready).active.state"
                             ) == "activated"
        cdp = context.new_cdp_session(page)
        manifest = cdp.send("Page.getAppManifest")
        assert manifest["errors"] == [] and manifest["url"].endswith("/manifest.webmanifest")
        assert cdp.send("Page.getInstallabilityErrors")["installabilityErrors"] == []
        context.close()


def test_dark_theme_settings_origins_and_editor_completion(page):
    page.locator("button:has(i:has-text('contrast'))").first.click()
    page.locator(".q-menu .q-item:has-text('Dark')").first.click()
    page.wait_for_function("() => document.body.classList.contains('body--dark')",
                           timeout=5000)
    page.wait_for_function("() => getElement(document.querySelector('.ots-term'))"
                           ".terminal.options.theme.background === '#1a1a19'", timeout=5000)
    page.locator(".ots-activity button:has(i:has-text('settings'))").first.click()
    page.locator(".q-expansion-item:has-text('[console]')").first.click()
    page.wait_for_selector(".q-badge:has-text('project')", timeout=5000)  # onthesignal.toml
    _type_in_terminal(page, "/edit_script e2e_completion\n")
    page.wait_for_selector(".monaco-editor", timeout=20000)
    page.wait_for_timeout(1000)
    page.locator(".monaco-editor .view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type("\nx = S1.sens", delay=40)
    page.wait_for_selector(".suggest-widget.visible .monaco-list-row:has-text('sensitivity')",
                           timeout=10000)
    page.keyboard.press("Escape")
    page.locator("button:has(i:has-text('contrast'))").first.click()
    page.locator(".q-menu .q-item:has-text('Light')").first.click()
    page.wait_for_function("() => !document.body.classList.contains('body--dark')",
                           timeout=5000)
    assert page.errors == []  # type: ignore[attr-defined]


def _chart(page, title: str) -> str:
    """JavaScript expression of the chart component whose figure title starts with ``title``."""
    return ("[...document.querySelectorAll('.ots-chart')].map((el) => getElement(el))"
            f".find((c) => c && c.figure && c.figure.title.startsWith({title!r}))")


def test_noise_trace_linked_rows_zoom_and_split(page):
    _type_in_terminal(page, "Nz = make_noise(5.0, bits=24, seed=2, duration=120, fs=200.0)\n")
    page.wait_for_selector(".q-item__label:text-is('Nz')", timeout=15000)
    _type_in_terminal(page, "noise(Nz)\n")
    page.wait_for_selector(".q-tab:has-text('noise Nz')", timeout=20000)
    chart = _chart(page, "Noise — Nz")
    page.wait_for_function(f"() => {{ const c = {chart}; return c && c.plots.length === 1; }}",
                           timeout=10000)
    # A row of the results highlights its element of the chart, and the other way round
    page.locator(".q-card[data-ots-ref='rms']").first.hover()
    page.wait_for_function(f"() => {chart}.highlightRef === 'rms'", timeout=5000)
    assert page.locator(".ots-linked").count() >= 4  # the key figure and its detail row
    page.mouse.move(5, 500)
    page.wait_for_function(f"() => {chart}.highlightRef === ''", timeout=5000)
    # Ctrl + wheel: the visible window comes back at full resolution
    before = page.evaluate(f"{chart}.plots[0].u.data[0].length")
    box = page.evaluate(f"(() => {{ const r = {chart}.plots[0].u.over.getBoundingClientRect(); "
                        "return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    page.mouse.move(*box)
    page.keyboard.down("Control")
    for _ in range(12):
        page.mouse.wheel(0, -120)
        time.sleep(0.05)
    page.keyboard.up("Control")
    page.wait_for_function(f"() => {chart}.plots[0].u.data[0].length > {before + 1000}",
                           timeout=10000)
    # Split: the next tab opens on the right side, and moves back with its menu
    page.locator("button:has-text('vertical_split')").click()
    page.locator(".q-item:has(.q-item__label:text-is('Nz'))").first.click()
    right = page.locator(".ots-side").nth(1)
    right.locator(".q-tab:has-text('Nz')").first.wait_for(timeout=10000)
    right.locator(".q-tab:has-text('Nz')").first.click(button="right")
    page.get_by_text("Move to the other side").click()
    playwright.expect(right.locator(".q-tab")).to_have_count(0, timeout=10000)
    playwright.expect(page.locator(".ots-side").nth(0).locator(".q-tab")).to_have_count(2)
    right.locator("button:has-text('close')").click()  # one side again
    page.wait_for_selector(".ots-work.ots-unsplit", timeout=5000)
    assert page.errors == []  # type: ignore[attr-defined]


def test_chat_formulas_and_edit_of_the_last_question(page):
    import json

    chats = PROJECT["path"] / ".onthesignal" / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    text = ("The ENOB follows from the SINAD:\n\n$$\\mathrm{ENOB} = "
            "\\frac{\\mathrm{SINAD} - 1.76}{6.02}$$\n\nwith \\(\\sigma\\) in counts.")
    record = {"id": "20261121_070000_000001", "title": "ENOB formula", "created": "2026-11-21",
              "provider": "test", "items": [
                  {"kind": "user", "text": "How is the ENOB computed?", "attachments": []},
                  {"kind": "assistant", "text": text, "thinking": ""}],
              "transcript": [{"role": "user", "content": "How is the ENOB computed?"},
                             {"role": "assistant", "content": text, "tool_calls": []}]}
    (chats / f"{record['id']}.json").write_text(json.dumps(record), encoding="utf-8")
    page.locator("button:has-text('history')").first.click()
    page.locator(".q-item:has-text('ENOB formula') button:has-text('open_in_browser')").first \
        .click()
    page.wait_for_selector(".nicegui-markdown math", timeout=8000)
    assert page.locator(".nicegui-markdown math").count() == 2  # display and inline
    page.locator("button:has-text('edit_note')").click()
    page.wait_for_selector("text=Editing the last question", timeout=5000)
    box = page.get_by_placeholder("Ask the assistant", exact=False)
    assert box.input_value() == "How is the ENOB computed?"
    assert page.errors == []  # type: ignore[attr-defined]


def test_sds_day_file_is_loaded_from_the_files_view(page):
    """A file named as in an SDS archive (no .mseed extension) is loaded, not edited."""
    shutil.copy(DATA, PROJECT["path"] / "data" / "XX.SDS.00.HHZ.D.2026.264")
    page.locator(".q-item:has-text('data')").first.click()
    page.locator(".q-item:has-text('XX.SDS.00.HHZ.D.2026.264')").first.click()
    page.wait_for_selector(".q-item__label:has-text('XX.SDS.00.HHZ.D.2026.264')", timeout=20000)
    assert page.locator("text=larger than the editor limit").count() == 0
    assert page.errors == []  # type: ignore[attr-defined]
