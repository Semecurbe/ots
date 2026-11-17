"""Real-time analysis of SeedLink streams (specification §13.2).

Measurements are limited to the mean, standard deviation and peak-to-peak over a sliding
window, and to an FFT amplitude spectrum or a Welch PSD over a (longer) sliding window.
Reception (thread), computation and display are decoupled: :class:`RealtimeMonitor` only
computes; the command-line front end renders a live table and a refreshed matplotlib figure.
"""

from __future__ import annotations

import argparse
import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from obspy import UTCDateTime

from ..core.errors import OnTheSignalError, ParameterError
from ..processing.spectral import amplitude_spectrum, welch_psd
from . import client as sl


class RingBuffer:
    """Fixed-capacity sample buffer; gaps are stored as NaN so statistics ignore them."""

    def __init__(self, capacity: int) -> None:
        self.data = np.full(capacity, np.nan)
        self.size = 0
        self.pos = 0

    def extend(self, values: np.ndarray) -> None:
        values = np.asarray(values, dtype=np.float64)[-self.data.size:]
        n = values.size
        end = self.pos + n
        if end <= self.data.size:
            self.data[self.pos:end] = values
        else:
            first = self.data.size - self.pos
            self.data[self.pos:] = values[:first]
            self.data[: n - first] = values[first:]
        self.pos = end % self.data.size
        self.size = min(self.size + n, self.data.size)

    def last(self, n: int) -> np.ndarray:
        n = min(n, self.size)
        idx = (self.pos - n + np.arange(n)) % self.data.size
        return self.data[idx]


@dataclass
class ChannelState:
    id: str
    sampling_rate: float = 0.0
    buffer: RingBuffer | None = None
    last_time: UTCDateTime | None = None
    gaps: int = 0
    samples: int = 0

    def latency(self) -> float | None:
        if self.last_time is None:
            return None
        return UTCDateTime().timestamp - self.last_time.timestamp


@dataclass
class ChannelSnapshot:
    id: str
    samples: int
    latency: float | None
    gaps: int
    mean: float | None
    std: float | None
    pp: float | None
    spectrum: tuple[np.ndarray, np.ndarray] | None = None
    note: str = ""


class RealtimeMonitor:
    """Sliding-window statistics and spectra of SeedLink streams.

    Parameters
    ----------
    window : float
        Statistics window in seconds (default 10 s).
    spectral_window : float
        FFT / PSD window in seconds (default 60 s).
    mode : {"stats", "fft", "dsp"}
        Spectrum computed in addition to the statistics.
    record_dir : str or Path, optional
        Also append every received record to ``<record_dir>/<id>.mseed``.
    """

    def __init__(self, server: str, streams: Sequence[sl.Stream], port: int | None = None,
                 window: float = 10.0, spectral_window: float = 60.0, mode: str = "stats",
                 record_dir: str | Path | None = None, client_factory: Callable | None = None
                 ) -> None:
        if mode not in ("stats", "fft", "dsp"):
            raise ParameterError("mode must be 'stats', 'fft' or 'dsp'")
        self.server, self.port, self.streams = server, port, list(streams)
        self.window, self.spectral_window, self.mode = window, spectral_window, mode
        self.record_dir = Path(record_dir) if record_dir else None
        self.client_factory = client_factory
        self.channels = {sl.stream_id(s): ChannelState(sl.stream_id(s)) for s in self.streams}
        self._lock = threading.Lock()
        self._files: dict[str, Any] = {}
        self._client: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _on_data(self, trace: Any) -> None:
        with self._lock:
            ch = self.channels.get(trace.id)
            if ch is None:
                return
            fs = trace.stats.sampling_rate
            if ch.buffer is None or ch.sampling_rate != fs:
                ch.sampling_rate = fs
                capacity = int(math.ceil(max(self.window, self.spectral_window) * fs)) + 1
                ch.buffer = RingBuffer(capacity)
            if ch.last_time is not None:
                jump = trace.stats.starttime - (ch.last_time + trace.stats.delta)
                if jump > 0.5 * trace.stats.delta:
                    ch.gaps += 1
                    ch.buffer.extend(np.full(min(int(round(jump * fs)), ch.buffer.data.size),
                                             np.nan))
            ch.buffer.extend(trace.data)
            ch.samples += trace.stats.npts
            if ch.last_time is None or trace.stats.endtime > ch.last_time:
                ch.last_time = trace.stats.endtime
            if self.record_dir is not None:
                fh = self._files.get(trace.id)
                if fh is None:
                    self.record_dir.mkdir(parents=True, exist_ok=True)
                    fh = self._files[trace.id] = open(self.record_dir / f"{trace.id}.mseed", "ab")  # noqa: SIM115
                trace.write(fh, format="MSEED")

    def start(self) -> None:
        self._client = sl.create(self.server, self.port, self._on_data, self.client_factory)
        for s in self.streams:
            self._client.select_stream(s[0], s[1], sl.selector(s))
        self._thread = threading.Thread(target=self._client.run, daemon=True, name="seedlink-rt")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._client is not None:
            try:
                self._client.conn.terminate()
            except Exception:  # noqa: BLE001
                pass
            if self._thread is not None:
                self._thread.join(timeout=5.0)
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        with self._lock:
            for fh in self._files.values():
                fh.close()
            self._files.clear()

    def snapshot(self) -> list[ChannelSnapshot]:
        """Current statistics (counts) and spectrum of every channel."""
        out = []
        with self._lock:
            states = [(ch.id, ch.sampling_rate, ch.samples, ch.latency(), ch.gaps,
                       None if ch.buffer is None else ch.buffer.last(
                           int(max(self.window, self.spectral_window) * ch.sampling_rate)))
                      for ch in self.channels.values()]
        for cid, fs, samples, latency, gaps, data in states:
            if data is None or data.size == 0:
                out.append(ChannelSnapshot(cid, samples, latency, gaps, None, None, None))
                continue
            stats_part = data[-int(self.window * fs):]
            valid = stats_part[np.isfinite(stats_part)]
            snap = ChannelSnapshot(
                cid, samples, latency, gaps,
                float(np.mean(valid)) if valid.size else None,
                float(np.std(valid)) if valid.size else None,
                float(np.ptp(valid)) if valid.size else None,
            )
            if self.mode != "stats":
                spec = data[-int(self.spectral_window * fs):]
                if np.isnan(spec).any():
                    snap.note = "gap in the spectral window"
                elif spec.size >= 64:
                    spec = spec - np.mean(spec)
                    if self.mode == "fft":
                        f, a, _ = amplitude_spectrum(spec, fs, "hann", "amplitude")
                    else:
                        f, a, _ = welch_psd(spec, fs)
                    snap.spectrum = (f[1:], a[1:])
            out.append(snap)
        return out

    def run(self, on_update: Callable[[list[ChannelSnapshot]], None], refresh: float = 1.0,
            duration: float | None = None) -> None:
        """Start, call ``on_update`` every ``refresh`` seconds until stopped (or Ctrl+C)."""
        self.start()
        t0 = time.time()
        try:
            while not self._stop.is_set():
                if duration is not None and time.time() - t0 >= duration:
                    break
                if self._thread is not None and not self._thread.is_alive():
                    raise OnTheSignalError("SeedLink connection closed")
                on_update(self.snapshot())
                self._stop.wait(refresh)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def _table(snaps: list[ChannelSnapshot], sensitivity: float | None, unit: str, title: str
           ) -> Any:
    from rich.table import Table

    from ..core.units import fmt_num, format_quantity

    table = Table(title=title, title_justify="left", caption="q or Ctrl+C to stop")
    for col in ("Channel", "Samples", "Latency (s)", "Gaps", "Mean", "Std", "P-P"):
        table.add_column(col, justify="left" if col == "Channel" else "right")
    for s in snaps:
        def cell(v: float | None) -> str:
            if v is None:
                return "—"
            text = f"{fmt_num(v)} c"
            if sensitivity:
                text += f" ({format_quantity(v * abs(sensitivity), unit)})"
            return text

        table.add_row(s.id, str(s.samples), f"{s.latency:.1f}" if s.latency is not None else "—",
                      str(s.gaps), cell(s.mean), cell(s.std), cell(s.pp))
    return table


def main(argv: Sequence[str] | None = None, session: Any = None) -> int:
    """``/rt`` and ``onthesignal rt``: live statistics and spectra of SeedLink streams."""
    from rich.console import Console
    from rich.live import Live

    from ..core.config import Config

    config = session.config if session is not None else Config.load()
    parser = argparse.ArgumentParser(prog="onthesignal rt",
                                     description="Real-time analysis of SeedLink streams.")
    parser.add_argument("--server", default=config.get("seedlink.server") or None)
    parser.add_argument("--port", type=int, default=config.get("seedlink.port", 18000))
    parser.add_argument("--network", default=config.get("seedlink.network") or None)
    parser.add_argument("--station", default=config.get("seedlink.station") or None)
    parser.add_argument("--channels", nargs="+", required=True, help="Channel patterns")
    parser.add_argument("--mode", choices=("stats", "fft", "dsp"), default="stats")
    parser.add_argument("--window", type=float, default=10.0, help="Statistics window (s)")
    parser.add_argument("--spectral-window", type=float, default=60.0, help="FFT/PSD window (s)")
    parser.add_argument("--refresh", type=float, default=1.0, help="Table refresh period (s)")
    parser.add_argument("--plot-refresh", type=float, default=2.0, help="Figure refresh (s)")
    parser.add_argument("--sensitivity", type=float, help="Physical unit per count")
    parser.add_argument("--unit", default="V", help="Physical unit")
    parser.add_argument("--record", help="Also record the streams in this folder")
    parser.add_argument("--duration", type=float, help="Stop after this many seconds")
    args = parser.parse_args(list(argv or []))
    if not args.server or not args.network or not args.station:
        parser.error("--server, --network and --station are required")
    console = Console()
    try:
        available = sl.list_streams(args.server, args.port, args.network, args.station)
        streams = sl.filter_streams(available, args.channels)
        if not streams:
            raise OnTheSignalError(f"No stream matches {' '.join(args.channels)}")
        monitor = RealtimeMonitor(args.server, streams, port=args.port, window=args.window,
                                  spectral_window=args.spectral_window, mode=args.mode,
                                  record_dir=args.record)
        figure: dict[str, Any] = {}
        last_plot = [0.0]
        title = f"Real time {args.network}.{args.station} — {args.mode}"

        def update(snaps: list[ChannelSnapshot]) -> None:
            live.update(_table(snaps, args.sensitivity, args.unit, title))
            if args.mode != "stats" and time.time() - last_plot[0] >= args.plot_refresh:
                last_plot[0] = time.time()
                _update_figure(figure, snaps, args.mode, args.sensitivity)

        with Live(console=console, refresh_per_second=4) as live:
            monitor.run(update, refresh=args.refresh, duration=args.duration)
    except OnTheSignalError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    return 0


def _update_figure(state: dict, snaps: list[ChannelSnapshot], mode: str,
                   sensitivity: float | None) -> None:
    import matplotlib.pyplot as plt

    from ..plot.style import LINE_W, SERIES, legend, style_axes

    if "fig" not in state:
        plt.ion()
        state["fig"], state["ax"] = plt.subplots(figsize=(9, 5))
        state["lines"] = {}
        ax = state["ax"]
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Amplitude (peak)" if mode == "fft" else "PSD (unit²/Hz)")
        style_axes(ax)
    ax = state["ax"]
    factor = (abs(sensitivity) if mode == "fft" else sensitivity**2) if sensitivity else 1.0
    for i, s in enumerate(snaps):
        if s.spectrum is None:
            continue
        f, a = s.spectrum
        line = state["lines"].get(s.id)
        if line is None:
            (line,) = ax.plot(f, a * factor, color=SERIES[i % len(SERIES)], lw=LINE_W, label=s.id)
            state["lines"][s.id] = line
            legend(ax, loc="lower left")
        else:
            line.set_data(f, a * factor)
    ax.relim()
    ax.autoscale_view()
    state["fig"].canvas.draw_idle()
    plt.pause(0.001)
