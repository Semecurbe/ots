"""SeedLink acquisition with a fake client (no network needed)."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from obspy import Trace, UTCDateTime, read

from onthesignal.seedlink import Acquisition, filter_streams, parse_streams
from onthesignal.seedlink.client import selector

XML = """<?xml version="1.0"?><seedlink>
<station name="SN270" network="RD"><stream location="00" seedname="FHZ"/>
<stream location="00" seedname="FHN"/><stream location="" seedname="LOG"/></station>
<station name="OTHER" network="RD"><stream location="00" seedname="FHZ"/></station>
</seedlink>"""

T0 = UTCDateTime("2026-11-17T10:00:00")


def records(channel: str, n: int, gap_after: int | None = None, gap: float = 2.0):
    out, t = [], T0
    for i in range(n):
        tr = Trace(np.arange(100, dtype=np.int32) + i * 100,
                   header={"network": "RD", "station": "SN270", "location": "00",
                           "channel": channel, "sampling_rate": 100.0, "starttime": t})
        out.append(tr)
        t = t + 1.0 + (gap if gap_after is not None and i == gap_after else 0.0)
    return out


class FakeConn:
    def __init__(self) -> None:
        self.terminate_flag = False

    def terminate(self) -> None:
        self.terminate_flag = True


class FakeClient:
    instances = 0

    def __init__(self, url, on_data, traces, fail_first=False):
        FakeClient.instances += 1
        self.url, self.on_data, self.traces = url, on_data, traces
        self.conn = FakeConn()
        self.selected = []
        self.fail = fail_first and FakeClient.instances == 1

    def get_info(self, level):
        return XML

    def select_stream(self, net, sta, sel):
        self.selected.append((net, sta, sel))

    def run(self):
        if self.fail:
            raise ConnectionError("simulated network failure")
        for tr in self.traces:
            if self.conn.terminate_flag:
                return
            self.on_data(tr)
            time.sleep(0.001)
        while not self.conn.terminate_flag:
            time.sleep(0.005)

    def close(self):
        pass


def test_stream_discovery_and_selection():
    streams = parse_streams(XML, "RD", "SN270")
    assert streams == [("RD", "SN270", "", "LOG"), ("RD", "SN270", "00", "FHN"),
                       ("RD", "SN270", "00", "FHZ")]
    assert filter_streams(streams, ["FH?"]) == streams[1:]
    assert filter_streams(streams, ["00.FHZ"]) == [streams[2]]
    assert selector(streams[2]) == "00FHZ"


def test_acquisition_writes_files_and_reports_gaps(tmp_path):
    traces = records("FHZ", 12) + records("FHN", 10, gap_after=4)
    streams = [("RD", "SN270", "00", "FHZ"), ("RD", "SN270", "00", "FHN")]
    progress = []
    acq = Acquisition(
        "server", streams, duration=9.0, data_time=True, outdir=tmp_path, poll_interval=0.02,
        client_factory=lambda url, on_data: FakeClient(url, on_data, traces),
        on_progress=progress.append,
    )
    result = acq.run()
    assert not result.interrupted
    assert {s.id for s in result.channels} == {"RD.SN270.00.FHZ", "RD.SN270.00.FHN"}
    fhn = next(s for s in result.channels if s.id.endswith("FHN"))
    assert len(fhn.gaps) == 1 and fhn.gaps[0]["duration"] == pytest.approx(2.01, abs=0.02)
    st = read(str(fhn.path))
    assert len(st) == 2  # the gap is kept, not interpolated
    assert not list(tmp_path.glob(".*.part"))
    assert acq.stats["RD.SN270.00.FHN"].gaps == 1
    assert progress[0].state == "connecting" and progress[-1].state == "stopped"


def test_acquisition_stop_and_single_file(tmp_path):
    traces = records("FHZ", 1000)
    acq = Acquisition(
        "server", [("RD", "SN270", "00", "FHZ")], duration=3600, outdir=tmp_path,
        output="acquisition.mseed", poll_interval=0.02,
        client_factory=lambda url, on_data: FakeClient(url, on_data, traces),
    )
    threading.Timer(0.3, acq.stop).start()
    result = acq.run()
    assert result.interrupted
    assert result.files == [tmp_path / "acquisition.mseed"]
    assert result.channels[0].npts > 0


def test_acquisition_reconnects(tmp_path):
    FakeClient.instances = 0
    traces = records("FHZ", 6)
    acq = Acquisition(
        "server", [("RD", "SN270", "00", "FHZ")], duration=5.0, data_time=True,
        outdir=tmp_path, reconnect_delay=0.01, poll_interval=0.02,
        client_factory=lambda url, on_data: FakeClient(url, on_data, traces, fail_first=True),
    )
    result = acq.run()
    assert FakeClient.instances == 2
    assert result.channels[0].npts == 600


def test_realtime_monitor_statistics_and_spectra(tmp_path):
    from onthesignal.seedlink.realtime import RealtimeMonitor, RingBuffer

    buf = RingBuffer(5)
    buf.extend(np.arange(3))
    buf.extend(np.arange(3, 8))
    assert buf.last(5).tolist() == [3, 4, 5, 6, 7]

    rng = np.random.default_rng(0)
    traces = []
    for i in range(30):
        tr = Trace((rng.normal(0, 10, 100) + 5).astype(np.int32),
                   header={"network": "RD", "station": "SN270", "location": "00",
                           "channel": "FHZ", "sampling_rate": 100.0, "starttime": T0 + i})
        traces.append(tr)
    monitor = RealtimeMonitor(
        "server", [("RD", "SN270", "00", "FHZ")], window=10, spectral_window=20, mode="dsp",
        record_dir=tmp_path, client_factory=lambda url, on_data: FakeClient(url, on_data, traces),
    )
    updates = []
    monitor.run(updates.append, refresh=0.05, duration=0.5)
    snap = updates[-1][0]
    assert snap.samples == 3000
    assert snap.std == pytest.approx(10, rel=0.15)
    assert snap.mean == pytest.approx(5, abs=1.5)
    assert snap.spectrum is not None
    assert read(str(tmp_path / "RD.SN270.00.FHZ.mseed"))[0].stats.npts == 3000
