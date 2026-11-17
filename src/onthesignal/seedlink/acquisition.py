"""SeedLink acquisition to miniSEED — rework of ``acq_mseed.py`` (specification §13.1).

Improvements over the original script:

* command-line arguments and configuration defaults instead of hard-coded values;
* records are written to disk as they arrive (``.part`` files), so an abrupt stop loses
  nothing; final files are consolidated at the end;
* gaps are detected, logged and reported — never filled silently (the final file keeps them);
* progress per channel: samples, last sample time, latency, gaps, effective rate;
* stop on wall-clock duration, on received data duration, or on a start/end window;
* clean stop (end of duration or Ctrl+C), automatic reconnection;
* importable module (:class:`Acquisition`) used by the console (``/acq``) and, later, the web.
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from obspy import Stream as ObsStream
from obspy import UTCDateTime, read

from ..core.errors import OnTheSignalError, ParameterError
from . import client as sl

log = logging.getLogger("onthesignal.acquisition")


@dataclass
class ChannelStats:
    """Live statistics of one channel."""

    id: str
    sampling_rate: float = 0.0
    samples: int = 0
    records: int = 0
    first_time: UTCDateTime | None = None
    last_time: UTCDateTime | None = None
    gaps: int = 0
    gap_duration: float = 0.0
    received_at: float = 0.0

    def latency(self) -> float | None:
        """Seconds between now and the last received sample."""
        if self.last_time is None:
            return None
        return UTCDateTime().timestamp - self.last_time.timestamp

    def data_duration(self) -> float:
        if self.first_time is None or self.last_time is None or not self.sampling_rate:
            return 0.0
        return self.last_time - self.first_time + 1.0 / self.sampling_rate

    def effective_rate(self) -> float | None:
        span = self.data_duration()
        return self.samples / span if span > 0 else None


@dataclass
class Progress:
    """Snapshot passed to the progress callback."""

    state: str
    elapsed: float
    fraction: float
    channels: dict[str, ChannelStats]
    bytes_written: int
    message: str = ""


@dataclass
class ChannelSummary:
    id: str
    path: Path
    npts: int
    mean: float
    std: float
    pp: float
    gaps: list[dict] = field(default_factory=list)


@dataclass
class AcquisitionResult:
    files: list[Path]
    channels: list[ChannelSummary]
    interrupted: bool
    elapsed: float


class Acquisition:
    """SeedLink acquisition of selected streams into miniSEED files.

    Parameters
    ----------
    server, port : str, int
        SeedLink server (``host`` or ``host:port``) and port (default 18000).
    streams : sequence of (net, sta, loc, cha)
        Streams to acquire.
    duration : float, optional
        Acquisition length in seconds (wall clock, or received data with ``data_time``).
    start, end : UTCDateTime, optional
        Data window: the acquisition stops once every channel has passed ``end`` and the files
        are trimmed to ``[start, end]``.
    outdir : str or Path
        Output folder.
    output : str
        File name template. ``{net} {sta} {loc} {cha} {start}`` are replaced; without
        ``{cha}`` all channels go to a single file.
    on_progress : callable, optional
        Called about twice per second with a :class:`Progress`.
    """

    def __init__(
        self,
        server: str,
        streams: Sequence[sl.Stream],
        port: int | None = None,
        duration: float | None = None,
        start: Any = None,
        end: Any = None,
        data_time: bool = False,
        outdir: str | Path = ".",
        output: str = "{net}.{sta}.{loc}.{cha}_{start}.mseed",
        reconnect_attempts: int = 5,
        reconnect_delay: float = 5.0,
        on_progress: Callable[[Progress], None] | None = None,
        client_factory: Callable | None = None,
        poll_interval: float = 0.5,
    ) -> None:
        if not streams:
            raise ParameterError("No stream selected")
        if duration is None and end is None:
            raise ParameterError("Give a duration or an end time")
        self.server, self.port = server, port
        self.streams = list(streams)
        self.duration = duration
        self.start = UTCDateTime(start) if start is not None else None
        self.end = UTCDateTime(end) if end is not None else None
        self.data_time = data_time
        self.outdir = Path(outdir)
        self.output = output
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.on_progress = on_progress
        self.client_factory = client_factory
        self.poll_interval = poll_interval
        self.stats = {sl.stream_id(s): ChannelStats(sl.stream_id(s)) for s in self.streams}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._files: dict[str, Any] = {}
        self._bytes = 0
        self._client: Any = None
        self._thread: threading.Thread | None = None
        self._thread_error: BaseException | None = None
        self._terminating = False

    # ------------------------------------------------------------------ data reception
    def _part_path(self, trace_id: str) -> Path:
        return self.outdir / f".{trace_id}.mseed.part"

    def _on_data(self, trace: Any) -> None:
        tid = trace.id
        with self._lock:
            st = self.stats.get(tid)
            if st is None:
                return  # stream not requested
            fh = self._files.get(tid)
            if fh is None:
                fh = self._files[tid] = open(self._part_path(tid), "ab")  # noqa: SIM115
            before = fh.tell()
            trace.write(fh, format="MSEED")
            fh.flush()
            self._bytes += fh.tell() - before
            delta = trace.stats.delta
            if st.last_time is not None:
                jump = trace.stats.starttime - (st.last_time + delta)
                if jump > 0.5 * delta:
                    st.gaps += 1
                    st.gap_duration += jump
                    log.warning("Gap of %.3f s on %s at %s", jump, tid, st.last_time + delta)
            if st.first_time is None:
                st.first_time = trace.stats.starttime
            if st.last_time is None or trace.stats.endtime > st.last_time:
                st.last_time = trace.stats.endtime
            st.sampling_rate = trace.stats.sampling_rate
            st.samples += trace.stats.npts
            st.records += 1
            st.received_at = time.time()

    # ------------------------------------------------------------------ connection
    def _connect(self) -> None:
        self._client = sl.create(self.server, self.port, self._on_data, self.client_factory)
        for s in self.streams:
            self._client.select_stream(s[0], s[1], sl.selector(s))
        self._thread_error = None

        def target() -> None:
            try:
                self._client.run()
            except BaseException as exc:  # noqa: BLE001 - reported to the main loop
                self._thread_error = exc

        self._thread = threading.Thread(target=target, daemon=True, name="seedlink")
        self._thread.start()

    def _disconnect(self) -> None:
        if self._client is None:
            return
        self._terminating = True
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

    # ------------------------------------------------------------------ control
    def stop(self) -> None:
        """Request a clean stop (thread-safe)."""
        self._stop.set()

    def _done(self, elapsed: float) -> tuple[bool, float]:
        stats = list(self.stats.values())
        if self.end is not None:
            passed = [s.last_time is not None and s.last_time >= self.end for s in stats]
            reference = self.start or min((s.first_time for s in stats if s.first_time),
                                          default=None)
            total = (self.end - reference) if reference is not None else None
            current = min((s.last_time for s in stats if s.last_time), default=None)
            frac = 0.0
            if total and current is not None and reference is not None:
                frac = float(np.clip((current - reference) / total, 0, 1))
            return all(passed), frac
        assert self.duration is not None
        if self.data_time:
            span = min(s.data_duration() for s in stats)
            return span >= self.duration, min(span / self.duration, 1.0)
        return elapsed >= self.duration, min(elapsed / self.duration, 1.0)

    def _progress(self, state: str, elapsed: float, fraction: float, message: str = "") -> None:
        if self.on_progress is not None:
            with self._lock:
                snapshot = {k: ChannelStats(**vars(v)) for k, v in self.stats.items()}
            self.on_progress(Progress(state, elapsed, fraction, snapshot, self._bytes, message))

    def run(self) -> AcquisitionResult:
        """Acquire until the end condition, a stop request or Ctrl+C; returns the summary."""
        self.outdir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        interrupted = False
        attempts = 0
        self._progress("connecting", 0.0, 0.0, f"connecting to {self.server}")
        self._connect()
        try:
            while not self._stop.is_set():
                elapsed = time.time() - t0
                done, fraction = self._done(elapsed)
                if done:
                    break
                alive = self._thread is not None and self._thread.is_alive()
                if not alive and not self._terminating:
                    attempts += 1
                    reason = self._thread_error or "connection closed by the server"
                    if attempts > self.reconnect_attempts:
                        raise OnTheSignalError(f"SeedLink connection lost: {reason}")
                    msg = (f"connection lost ({reason}); reconnection {attempts}/"
                           f"{self.reconnect_attempts} in {self.reconnect_delay:g} s")
                    log.warning(msg)
                    self._progress("reconnecting", elapsed, fraction, msg)
                    if self._stop.wait(self.reconnect_delay):
                        break
                    self._connect()
                    continue
                self._progress("streaming", elapsed, fraction)
                self._stop.wait(self.poll_interval)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            self._disconnect()
            with self._lock:
                for fh in self._files.values():
                    fh.close()
        interrupted = interrupted or self._stop.is_set()
        elapsed = time.time() - t0
        self._progress("finishing", elapsed, 1.0, "writing the final files")
        result = self._finalize(interrupted, elapsed)
        self._progress("stopped", elapsed, 1.0, "acquisition finished")
        return result

    # ------------------------------------------------------------------ final files
    def _name(self, net: str, sta: str, loc: str, cha: str, start: UTCDateTime) -> Path:
        name = self.output.format(net=net, sta=sta, loc=loc, cha=cha,
                                  start=start.strftime("%Y%m%dT%H%M%S"))
        return self.outdir / name

    def _finalize(self, interrupted: bool, elapsed: float) -> AcquisitionResult:
        per_channel = "{cha}" in self.output or "{loc}" in self.output
        combined = ObsStream()
        summaries: list[ChannelSummary] = []
        files: list[Path] = []
        for tid in self.stats:
            part = self._part_path(tid)
            if not part.exists() or part.stat().st_size == 0:
                log.warning("No data received for %s", tid)
                continue
            st = read(str(part), format="MSEED")
            if self.start is not None or self.end is not None:
                st.trim(self.start, self.end)
            st.sort(["starttime"])
            gaps = [{"start": str(g[4]), "end": str(g[5]), "duration": float(g[6])}
                    for g in st.get_gaps() if g[6] > 0]
            st.merge(method=1, fill_value=None)
            data = np.ma.concatenate([tr.data for tr in st]) if len(st) else np.array([])
            values = np.asarray(np.ma.compressed(np.ma.asarray(data)), dtype=float)
            st = st.split()  # gaps are kept, never interpolated
            net, sta, loc, cha = tid.split(".")
            start = min(tr.stats.starttime for tr in st)
            if per_channel:
                path = self._name(net, sta, loc, cha, start)
                st.write(str(path), format="MSEED")
                files.append(path)
            else:
                combined += st
                path = self._name(net, sta, loc, "", start)
            part.unlink()
            summaries.append(ChannelSummary(
                tid, path, int(values.size), float(np.mean(values)) if values.size else 0.0,
                float(np.std(values)) if values.size else 0.0,
                float(np.ptp(values)) if values.size else 0.0, gaps,
            ))
        if not per_channel and len(combined):
            start = min(tr.stats.starttime for tr in combined)
            path = self._name("", "", "", "", start)
            combined.write(str(path), format="MSEED")
            files.append(path)
            for s in summaries:
                s.path = path
        return AcquisitionResult(files, summaries, interrupted, elapsed)


# ---------------------------------------------------------------------------------- CLI
def _choose(streams: list[sl.Stream], ask: Callable[[str], str]) -> list[sl.Stream]:
    if not streams:
        raise OnTheSignalError("No stream available for this network/station on the server")
    print("\nAvailable streams:")
    for i, s in enumerate(streams, start=1):
        print(f"  {i:2d}) {s[0]}.{s[1]}.{s[2] or '--'}.{s[3]}")
    raw = ask("\nStreams to acquire (e.g. 1,3 or 'all'): ").strip().lower()
    if raw == "all":
        return streams
    chosen = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(streams):
            chosen.append(streams[int(part) - 1])
    if not chosen:
        raise OnTheSignalError("No valid selection")
    return chosen


def _live_table(progress: Progress, title: str) -> Any:
    from rich.table import Table

    bar_width = 30
    filled = int(progress.fraction * bar_width)
    bar = "█" * filled + "·" * (bar_width - filled)
    table = Table(title=(f"{title} — {progress.state} — {bar} "
                         f"{100 * progress.fraction:5.1f} % — {progress.elapsed:6.0f} s — "
                         f"{progress.bytes_written / 1e6:.2f} MB"),
                  title_justify="left", caption=progress.message or None)
    for col in ("Channel", "Samples", "Last sample (UTC)", "Latency (s)", "Gaps", "Rate (Hz)"):
        table.add_column(col, justify="right" if col != "Channel" else "left")
    for st in progress.channels.values():
        latency = st.latency()
        rate = st.effective_rate()
        table.add_row(
            st.id, str(st.samples), str(st.last_time)[:23] if st.last_time else "—",
            f"{latency:.1f}" if latency is not None else "—",
            f"{st.gaps} ({st.gap_duration:.2f} s)" if st.gaps else "0",
            f"{rate:.2f}" if rate else "—",
        )
    return table


def main(argv: Sequence[str] | None = None, session: Any = None) -> int:
    """``onthesignal acq`` / ``/acq``: SeedLink acquisition with live progress."""
    from rich.console import Console
    from rich.live import Live

    from ..core.config import Config

    config = session.config if session is not None else Config.load()
    parser = argparse.ArgumentParser(prog="onthesignal acq",
                                     description="SeedLink acquisition to miniSEED files.")
    parser.add_argument("--server", default=config.get("seedlink.server") or None,
                        help="SeedLink server (host or host:port)")
    parser.add_argument("--port", type=int, default=config.get("seedlink.port", 18000))
    parser.add_argument("--network", default=config.get("seedlink.network") or None)
    parser.add_argument("--station", default=config.get("seedlink.station") or None)
    parser.add_argument("--channels", nargs="+", help="Channel patterns (e.g. 'FH?' or 00.FHZ); "
                        "interactive selection when omitted")
    parser.add_argument("--duration", type=float, help="Duration in seconds")
    parser.add_argument("--data-time", action="store_true",
                        help="Count the duration on received data instead of the wall clock")
    parser.add_argument("--start", help="Data window start (UTC)")
    parser.add_argument("--end", help="Data window end (UTC)")
    parser.add_argument("--outdir", default=".", help="Output folder")
    parser.add_argument("--output", default="{net}.{sta}.{loc}.{cha}_{start}.mseed",
                        help="File name template; without {cha}, one file for all channels")
    parser.add_argument("--load", action="store_true", help="Load the files into the session")
    parser.add_argument("--log", default=None, help="Log file (default: <outdir>/acquisition.log)")
    args = parser.parse_args(list(argv or []))
    if not args.server or not args.network or not args.station:
        parser.error("--server, --network and --station are required (or set [seedlink] in "
                     "the configuration)")
    if args.duration is None and args.end is None:
        parser.error("give --duration or --end")

    os.makedirs(args.outdir, exist_ok=True)
    handler = logging.FileHandler(args.log or os.path.join(args.outdir, "acquisition.log"))
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    console = Console()
    try:
        console.print(f"Connecting to {sl.server_url(args.server, args.port)} (INFO STREAMS)…")
        available = sl.list_streams(args.server, args.port, args.network, args.station)
        streams = (sl.filter_streams(available, args.channels) if args.channels
                   else _choose(available, input))
        if not streams:
            raise OnTheSignalError(f"No stream matches {' '.join(args.channels or [])}")
        log.info("Acquisition of %s", ", ".join(sl.stream_id(s) for s in streams))
        title = f"Acquisition {args.network}.{args.station}"
        with Live(console=console, refresh_per_second=4) as live:
            acq = Acquisition(
                args.server, streams, port=args.port, duration=args.duration, start=args.start,
                end=args.end, data_time=args.data_time, outdir=args.outdir, output=args.output,
                reconnect_attempts=int(config.get("seedlink.reconnect_attempts", 5)),
                reconnect_delay=float(config.get("seedlink.reconnect_delay", 5.0)),
                on_progress=lambda p: live.update(_live_table(p, title)),
            )
            result = acq.run()
    except OnTheSignalError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    finally:
        log.removeHandler(handler)
        handler.close()
    if result.interrupted:
        console.print("[yellow]Interrupted: the data received so far has been saved.[/yellow]")
    for s in result.channels:
        gaps = f"{len(s.gaps)} gap(s), {sum(g['duration'] for g in s.gaps):.3f} s" if s.gaps \
            else "no gap"
        console.print(f"  {s.id}: N={s.npts}  mean={s.mean:.6g}  std={s.std:.6g}  "
                      f"p-p={s.pp:.6g}  {gaps}")
    for path in result.files:
        console.print(f"Written: {path}")
    if args.load and session is not None:
        from ..api import load
        from ..core.session import set_session

        set_session(session)
        for path in result.files:
            load(path)
    return 0
