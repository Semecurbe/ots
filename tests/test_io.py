"""File reading and writing (V-15, V-16)."""

from __future__ import annotations

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime

from onthesignal import load
from onthesignal.core.errors import FileFormatError, ParameterError
from onthesignal.io import read


def _write_mseed(path, gap: bool = False):
    t0 = UTCDateTime("2026-11-17T10:00:00")
    tr1 = Trace(np.arange(1000, dtype=np.int32),
                header={"network": "RD", "station": "SN270", "location": "00", "channel": "FHZ",
                        "sampling_rate": 100.0, "starttime": t0})
    traces = [tr1]
    if gap:
        tr2 = tr1.copy()
        tr2.data = np.arange(3000, dtype=np.int32)
        tr2.stats.starttime = t0 + 15.0  # 5 s gap after the first 10 s
        traces.append(tr2)
    other = tr1.copy()
    other.stats.channel = "FHN"
    traces.append(other)
    Stream(traces).write(str(path), format="MSEED")


def test_mseed_one_signal_per_channel(tmp_path, session):
    path = tmp_path / "a.mseed"
    _write_mseed(path)
    sigs = load(path, unit="V", sensitivity=2.384e-6)
    assert [s.channel for s in sigs] == ["FHN", "FHZ"]
    assert list(session.signals) == ["S1", "S2"]
    assert sigs[0].sha256 and sigs[0].unit == "V"
    assert sigs[1].data.dtype == np.float64 and sigs[1].metadata["dtype"] == "int32"


def test_mseed_gap_policies(tmp_path):
    """V-15: the gap is detected, the policy applied and the gap reported."""
    path = tmp_path / "gap.mseed"
    _write_mseed(path, gap=True)
    longest = read(path, select="*.*.*.FHZ")[0]
    assert longest.npts == 3000
    assert longest.gaps and longest.gaps[0]["duration"] == pytest.approx(5.01, abs=0.02)
    assert "longest" in longest.gaps[0]["action"]
    filled = read(path, select="*.*.*.FHZ", gaps="fill")[0]
    assert filled.npts == 4500  # 1000 + 500 interpolated + 3000
    assert "interpolation" in filled.gaps[0]["action"]
    split = read(path, select="*.*.*.FHZ", gaps="split")
    assert len(split) == 2
    with pytest.raises(FileFormatError, match="gap"):
        read(path, select="*.*.*.FHZ", gaps="error")


def test_text_with_time_column_and_decimal_comma(tmp_path):
    """V-16: decimal comma read correctly."""
    path = tmp_path / "mesure.txt"
    lines = ["# header comment", "time;ch1;ch2"]
    for i in range(100):
        lines.append(f"{i * 0.01:.2f};{i}.5;{-i}".replace(".", ","))
    path.write_text("\n".join(lines))
    sigs = read(path, n_channels=2, time_col=0, decimal=",")
    assert len(sigs) == 2
    assert sigs[0].sampling_rate == pytest.approx(100.0)
    assert sigs[0].data[3] == pytest.approx(3.5)
    assert sigs[1].channel == "C02"


def test_text_irregular_time_and_errors(tmp_path):
    """V-16: an irregular time column raises an explicit error (or is resampled on request)."""
    path = tmp_path / "irr.txt"
    t = np.cumsum(np.r_[0, np.full(50, 0.01), [0.02], np.full(50, 0.01)])
    path.write_text("\n".join(f"{ti:.4f} {i}" for i, ti in enumerate(t)))
    with pytest.raises(FileFormatError, match="Irregular"):
        read(path, n_channels=1, time_col=0)
    sig = read(path, n_channels=1, time_col=0, resample=True)[0]
    assert sig.sampling_rate == pytest.approx(100.0)
    with pytest.raises(FileFormatError, match="column"):
        read(path, n_channels=3, time_col=0)
    with pytest.raises(ParameterError, match="fs"):
        read(path, n_channels=2)


def test_export_roundtrip(tmp_path):
    path = tmp_path / "a.mseed"
    _write_mseed(path)
    sig = read(path, select="*.*.*.FHZ")[0]
    out = sig.save(tmp_path / "out.mseed")
    back = read(out)[0]
    assert np.array_equal(back.data, sig.data) and back.id == sig.id
    txt = sig.save(tmp_path / "out.csv")
    back_txt = read(txt, n_channels=1, time_col=0, starttime=sig.starttime)[0]
    assert np.allclose(back_txt.data, sig.data)
