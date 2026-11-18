"""Standardized scripts, batches and Quarto reports."""

from __future__ import annotations

import shutil

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime

from onthesignal import Signal
from onthesignal.analysis import compute_noise, compute_sinad
from onthesignal.report import generate_report
from onthesignal.scripts import batch, create_script, list_scripts, load_script, main, run_script


@pytest.fixture
def files(tmp_path):
    rng = np.random.default_rng(3)
    paths = []
    for i in range(2):
        tr = Trace(rng.normal(0, 10 * (i + 1), 10_000).astype(np.int32),
                   header={"network": "RD", "station": f"ST{i}", "channel": "HHZ",
                           "sampling_rate": 100.0, "starttime": UTCDateTime(0)})
        path = tmp_path / f"f{i}.mseed"
        Stream([tr]).write(str(path), format="MSEED")
        paths.append(str(path))
    return paths


def test_script_from_template(tmp_path, monkeypatch, session):
    monkeypatch.chdir(tmp_path)
    path = create_script("rms_band")
    assert path.exists() and "rms_band" in path.read_text()
    assert list_scripts()[0][0] == "rms_band"
    script = load_script("rms_band")
    assert [p.name for p in script.params] == ["fmax", "remove_mains"]
    s = Signal(np.random.default_rng(0).normal(0, 5, 20_000), 200.0)
    session.add_signal(s)
    result = run_script("rms_band", "S1", fmax=100.0)
    assert result["rms"] == pytest.approx(5.0, rel=0.03)
    assert result.plot() is not None  # the script's plot() is used


def test_batch_analysis_and_standalone_main(tmp_path, monkeypatch, files):
    monkeypatch.chdir(tmp_path)
    rows = batch("noise", files, out=tmp_path / "out.csv")
    assert [round(r["rms"], -1) for r in rows] == [10, 20]
    header = (tmp_path / "out.csv").read_text().splitlines()[0]
    assert "rms [counts]" in header
    create_script("rms_band")
    script = load_script("rms_band")
    code = main(script.run, script.params,
                argv=["--files", *files, "--param", "fmax=10", "--out", str(tmp_path / "s.json")])
    assert code == 0 and (tmp_path / "s.json").exists()


def test_batch_records_errors(tmp_path, files):
    bad = tmp_path / "bad.mseed"
    bad.write_text("not a miniseed file")
    rows = batch("noise", [*files, str(bad)])
    assert sum("error" in r for r in rows) == 1


def test_report_generation(tmp_path, white_noise):
    fs, n = 1000.0, 100_000
    s2 = Signal(1e6 * np.sin(2 * np.pi * 7.3 * np.arange(n) / fs), fs, name="S2",
                title="sine_7Hz")
    results = [compute_noise(white_noise), compute_sinad(s2)]
    assert "S2 · sine_7Hz (" in results[1].title
    qmd = generate_report(results, title="Bench | test", output_dir=tmp_path, formats=["html"])
    text = qmd.read_text()
    assert "Bench \\| test" not in text.splitlines()[1]  # title stays in YAML
    assert "## Analysed signals" in text and "figures/02_sinad.png" in text
    assert "| S2 | sine_7Hz |" in text
    assert (qmd.parent / "figures" / "02_sinad.png").exists()
    if shutil.which("quarto"):
        from onthesignal.report import render_report

        produced = render_report(qmd, ["html"])
        assert produced[0].exists()
