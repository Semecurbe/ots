"""Real-time dashboard of SeedLink streams in the web interface (web specification §8.2).

A :class:`RealtimeRun` lives in the server, so it survives page reloads. Its job thread
starts a :class:`~onthesignal.seedlink.realtime.RealtimeMonitor`. At every refresh it computes
the statistics and the decimated trace of the last seconds, and at a slower pace the FFT and
the Welch PSD over the spectral window. It publishes them as JSON-ready payloads with a
version number. The browser tabs only read the latest payload: reception, computation and
display are decoupled, and the browser receives decimated curves only (rules R7, R12, R16).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from obspy import UTCDateTime

from ..core.errors import OnTheSignalError
from ..core.units import fmt_num, format_quantity, pretty_unit
from ..plot.spec import Axis, FigureSpec, Panel, Series
from ..processing.display import decimate_xy, envelope_indices
from ..seedlink.client import Stream, stream_id
from ..seedlink.realtime import ChannelSnapshot, RealtimeMonitor
from .figures import DEFAULT_BINS, align

log = logging.getLogger("onthesignal.web")


@dataclass
class RealtimeSettings:
    """Choices of the ``Real time`` view."""

    server: str
    streams: Sequence[Stream]
    port: int | None = None
    #: Statistics window (s).
    window: float = 10.0
    #: FFT and PSD window (s).
    spectral_window: float = 60.0
    #: Duration of the trace shown (s).
    trace_seconds: float = 30.0
    #: Refresh period of the statistics and the trace (s).
    refresh: float = 1.0
    #: Refresh period of the FFT and the PSD (s).
    spectra_refresh: float = 2.0
    #: Physical unit per count; ``None`` shows counts only.
    sensitivity: float | None = None
    unit: str = "V"
    #: Folder where the received records are appended (miniSEED), ``None`` not to record.
    record_dir: str | Path | None = None


@dataclass
class RealtimeView:
    """Latest payload of a run, read by the browser tabs."""

    version: int = 0
    spectra_version: int = 0
    stats: list[dict[str, str]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    fft: dict[str, Any] = field(default_factory=dict)
    dsp: dict[str, Any] = field(default_factory=dict)
    updated: float = 0.0


class RealtimeRun:
    """One real-time session: monitor, payloads and state (one at a time per server)."""

    def __init__(self, settings: RealtimeSettings, client_factory: Callable | None = None
                 ) -> None:
        self.settings = settings
        self.ids = [stream_id(s) for s in settings.streams]
        self.monitor = RealtimeMonitor(
            settings.server, list(settings.streams), port=settings.port,
            window=settings.window, spectral_window=settings.spectral_window, mode="stats",
            record_dir=settings.record_dir, client_factory=client_factory)
        self.origin = UTCDateTime()
        self.state = "starting"  # starting, running, stopping, stopped, failed
        self.error = ""
        self.recording = settings.record_dir is not None
        self.view = RealtimeView()
        self._stop = threading.Event()

    # ------------------------------------------------------------------ units
    @property
    def physical(self) -> bool:
        return self.settings.sensitivity is not None

    @property
    def unit(self) -> str:
        return pretty_unit(self.settings.unit) if self.physical else "counts"

    @property
    def sensitivity(self) -> float:
        """Physical unit per count (1 when the values are shown in counts)."""
        s = self.settings.sensitivity
        return 1.0 if s is None else float(s)

    @staticmethod
    def color(index: int) -> str:
        return f"series:{index % 8}"

    # ------------------------------------------------------------------ figures
    def trace_figure(self) -> FigureSpec:
        """Last seconds of every channel, stacked, on a common time axis."""
        iso = self.origin.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        panels = [Panel(f"ch{i}", Axis("Time", "s", time_origin=iso), Axis(cid, self.unit),
                        [Series(cid, cid, width=0.8, color=self.color(i))], sync="t",
                        legend=False)
                  for i, cid in enumerate(self.ids)]
        return FigureSpec(f"Last {fmt_num(self.settings.trace_seconds)} s", panels)

    def spectrum_figure(self, kind: str) -> FigureSpec:
        """FFT amplitude (log-log) or Welch PSD (dB) of every channel, one series each."""
        unit = self.unit
        if kind == "fft":
            y = Axis("Amplitude (peak)", unit, "log")
            title = f"FFT amplitude · {fmt_num(self.settings.spectral_window)} s window"
        else:
            y = Axis("PSD", f"dB re 1 {unit}²/Hz")
            title = f"Welch PSD · {fmt_num(self.settings.spectral_window)} s window"
        series = [Series(cid, cid, width=1.0, color=self.color(i))
                  for i, cid in enumerate(self.ids)]
        return FigureSpec(title, [Panel("spectrum", Axis("Frequency", "Hz", "log"), y, series)])

    # ------------------------------------------------------------------ payloads
    def _stat_row(self, snap: ChannelSnapshot) -> dict[str, str]:
        def cell(v: float | None, signed: bool = False) -> str:
            if v is None:
                return "—"
            text = f"{fmt_num(v)} counts"
            if self.physical:
                s = self.sensitivity if signed else abs(self.sensitivity)
                text += f" ({format_quantity(v * s, self.settings.unit)})"
            return text

        state = self.monitor.channels.get(snap.id)
        rate = state.sampling_rate if state is not None else 0.0
        return {"channel": snap.id, "samples": str(snap.samples),
                "rate": f"{fmt_num(rate)} Hz" if rate else "—",
                "latency": "—" if snap.latency is None else f"{snap.latency:.1f} s",
                "gaps": str(snap.gaps), "mean": cell(snap.mean, True), "std": cell(snap.std),
                "pp": cell(snap.pp), "note": snap.note}

    def _trace(self, bins: int) -> dict[str, Any]:
        factor = self.sensitivity
        data = {}
        latest = self.monitor.latest(self.settings.trace_seconds)
        for i, cid in enumerate(self.ids):
            last, fs, values = latest.get(cid, (None, 0.0, np.empty(0)))
            if last is None or not fs or values.size == 0:
                data[f"ch{i}"] = align([(np.empty(0), np.empty(0))])
                continue
            n = values.size
            t = float(last - self.origin) - (n - 1 - np.arange(n)) / fs
            idx = envelope_indices(n, values, bins)
            data[f"ch{i}"] = align([(t[idx], values[idx] * factor)])
        return data

    def _spectra(self, kind: str, bins: int) -> dict[str, Any]:
        # Amplitude spectra scale with |sensitivity|, power spectra with its square.
        factor = abs(self.sensitivity) if kind == "fft" else self.sensitivity ** 2
        curves = []
        by_id = {s.id: s for s in self.monitor.snapshot(kind)}
        for cid in self.ids:
            snap = by_id.get(cid)
            if snap is None or snap.spectrum is None:
                curves.append((np.empty(0), np.empty(0)))
                continue
            f, a = snap.spectrum
            a = np.asarray(a, float) * factor
            if kind == "dsp":
                a = 10.0 * np.log10(np.maximum(a, 1e-300))
            curves.append(decimate_xy(f, a, bins, "log"))
        return {"spectrum": align(curves)}

    def update(self, spectra: bool, bins: int = DEFAULT_BINS) -> None:
        """Compute a new payload (job thread); ``spectra`` also refreshes FFT and PSD."""
        stats = [self._stat_row(s) for s in self.monitor.snapshot("stats")]
        trace = self._trace(bins)
        view = RealtimeView(self.view.version + 1, self.view.spectra_version, stats, trace,
                            self.view.fft, self.view.dsp, time.time())
        if spectra:
            view.fft = self._spectra("fft", bins)
            view.dsp = self._spectra("dsp", bins)
            view.spectra_version += 1
        self.view = view  # one assignment: readers see a complete payload

    # ------------------------------------------------------------------ control
    def run(self, job: Any = None) -> None:
        """Job thread: receive, compute and publish until stopped."""
        s = self.settings
        self.monitor.start()
        if self.state == "starting":
            self.state = "running"
        last_spectra = 0.0
        try:
            while not self._stop.is_set():
                thread = self.monitor._thread
                if thread is not None and not thread.is_alive():
                    raise OnTheSignalError("SeedLink connection closed")
                now = time.monotonic()
                spectra = now - last_spectra >= s.spectra_refresh
                if spectra:
                    last_spectra = now
                self.update(spectra)
                if job is not None:
                    job.message = f"{len(self.ids)} channel(s)"
                self._stop.wait(s.refresh)
        except Exception as exc:
            self.state, self.error = "failed", str(exc)
            raise
        finally:
            self.monitor.stop()
            if self.state != "failed":
                self.state = "stopped"

    def stop(self) -> None:
        """Ask the job to stop; the state is ``stopping`` until the connection is closed."""
        if self.state in ("starting", "running"):
            self.state = "stopping"
        self._stop.set()

    def set_recording(self, folder: str | Path | None) -> None:
        """Start or stop appending the received records to ``<folder>/<id>.mseed``."""
        self.monitor.set_record_dir(folder)
        self.recording = folder is not None
        log.info("[realtime] recording %s", f"in {folder}" if folder else "stopped")

    @property
    def running(self) -> bool:
        """True until the connection is closed (a new run cannot start before)."""
        return self.state in ("starting", "running", "stopping")


__all__ = ["RealtimeRun", "RealtimeSettings", "RealtimeView"]
