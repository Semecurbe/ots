"""Shared state of the web server: session, terminal, background jobs, browser channels.

Rule R12 of the web specification: widgets are only touched from the event loop. Worker
threads (analyses, acquisition, the Python terminal, the assistant) never call NiceGUI: they
push events into the channel of each browser tab, which a timer of the page drains.
"""

from __future__ import annotations

import base64
import concurrent.futures
import io
import itertools
import logging
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..core.errors import OnTheSignalWarning, ParameterError
from ..core.result import Result
from ..core.session import Session
from ..core.signal import Signal
from .batch import BatchRun, BatchSettings
from .realtime import RealtimeRun, RealtimeSettings
from .terminal import PythonTerminal

log = logging.getLogger("onthesignal.web")


# ---------------------------------------------------------------------------------- jobs
@dataclass
class Job:
    """A background task (analysis, acquisition, report rendering, AI request, batch)."""

    id: int
    name: str
    kind: str = "task"
    state: str = "running"  # running, done, failed, cancelled
    progress: float | None = None
    message: str = ""
    started: float = field(default_factory=time.time)
    ended: float | None = None
    result: Any = None
    error: str = ""
    cancel: Callable[[], None] | None = None

    @property
    def duration(self) -> float:
        return (self.ended or time.time()) - self.started


class Jobs:
    """Background tasks run in daemon threads, independent of the browser tabs."""

    def __init__(self, state: WebState) -> None:
        self.state = state
        self._ids = itertools.count(1)
        self.items: list[Job] = []
        self._lock = threading.Lock()

    def start(self, name: str, func: Callable[[Job], Any], kind: str = "task",
              on_done: Callable[[Job], None] | None = None,
              cancel: Callable[[], None] | None = None, client: str | None = None) -> Job:
        """Run ``func(job)`` in a thread; ``client`` is the browser tab that asked for it."""
        job = Job(next(self._ids), name, kind, cancel=cancel)
        with self._lock:
            self.items.append(job)
            del self.items[:-50]

        def target() -> None:
            self.state._origin.client = client
            try:
                job.result = func(job)
                if job.state == "running":
                    job.state = "done"
            except Exception as exc:
                job.state, job.error = "failed", f"{type(exc).__name__}: {exc}"
                log.debug("job %s failed\n%s", name, traceback.format_exc())
            finally:
                job.ended = time.time()
                self.state.log(kind, f"{name}: {job.state} ({job.duration:.1f} s)"
                               + (f" — {job.error}" if job.error else ""))
                if on_done is not None:
                    try:
                        on_done(job)
                    except Exception:
                        log.exception("job callback failed")
                self.state.broadcast({"type": "job", "id": job.id})

        threading.Thread(target=target, name=f"ots-job-{job.id}", daemon=True).start()
        self.state.broadcast({"type": "job", "id": job.id})
        return job

    def running(self) -> list[Job]:
        return [j for j in self.items if j.state == "running"]


# ---------------------------------------------------------------------------------- objects
@dataclass
class FigureRecord:
    """A figure of the terminal or a script (``Figures`` group): a matplotlib image, or an
    interactive chart of ``plot()`` (``spec`` and ``data`` of the µPlot component)."""

    name: str
    title: str
    png: bytes
    spec: dict | None = None
    data: dict | None = None

    def data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png).decode("ascii")


@dataclass
class VariableInfo:
    """A variable of the terminal namespace (``Variables`` group)."""

    name: str
    type: str
    summary: str
    kind: str  # number, text, array1d, array, sequence, mapping, other


def describe_variable(name: str, value: Any) -> VariableInfo | None:
    """Description of a terminal variable, ``None`` for what the panel does not list."""
    import types

    if name.startswith("_") or isinstance(value, (Signal, Result, types.ModuleType, type)):
        return None
    if callable(value):
        return None
    if isinstance(value, (bool, int, float, complex, np.number, np.bool_)):
        return VariableInfo(name, type(value).__name__, repr(value)[:60], "number")
    if isinstance(value, str):
        return VariableInfo(name, "str", repr(value)[:60], "text")
    if isinstance(value, np.ndarray):
        kind = "array1d" if value.ndim == 1 and np.issubdtype(value.dtype, np.number) \
            else "array"
        shape = "×".join(str(n) for n in value.shape)
        return VariableInfo(name, f"ndarray {value.dtype}", f"({shape})", kind)
    if isinstance(value, (list, tuple, set)):
        return VariableInfo(name, type(value).__name__, f"{len(value)} items", "sequence")
    if isinstance(value, dict):
        return VariableInfo(name, "dict", f"{len(value)} keys", "mapping")
    return VariableInfo(name, type(value).__name__, repr(value)[:60], "other")


# ---------------------------------------------------------------------------------- channels
class Channel:
    """Events for one browser tab, drained by a timer of its page."""

    def __init__(self) -> None:
        self.queue: deque[dict] = deque()

    def push(self, event: dict) -> None:
        self.queue.append(event)

    def drain(self) -> list[dict]:
        out = []
        while self.queue:
            out.append(self.queue.popleft())
        return out


class Requests:
    """Questions asked from a worker thread and answered in a browser (confirmations, forms)."""

    def __init__(self, state: WebState) -> None:
        self.state = state
        self._ids = itertools.count(1)
        self.pending: dict[int, concurrent.futures.Future] = {}

    def ask(self, event: dict, timeout: float | None = None, client: str | None = None) -> Any:
        request_id = next(self._ids)
        future: concurrent.futures.Future = concurrent.futures.Future()
        self.pending[request_id] = future
        event = {**event, "request": request_id}
        if client is not None and client in self.state.channels:
            self.state.channels[client].push(event)
        else:
            self.state.broadcast(event)
        deadline = None if timeout is None else time.monotonic() + timeout
        try:
            while True:  # short waits keep Ctrl+C of the terminal effective
                try:
                    return future.result(timeout=0.2)
                except concurrent.futures.TimeoutError:
                    if deadline is not None and time.monotonic() > deadline:
                        return None
        finally:
            self.pending.pop(request_id, None)
            self.state.broadcast({"type": "request_done", "request": request_id})

    def answer(self, request_id: int, value: Any) -> None:
        future = self.pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(value)


# ---------------------------------------------------------------------------------- state
class WebState:
    """Everything the browser tabs share: one instance per server (web specification §3.4)."""

    def __init__(self, session: Session, project: str = ".") -> None:
        self.session = session
        self.project = project
        self.config = session.config
        self.channels: dict[str, Channel] = {}
        self.jobs = Jobs(self)
        self.requests = Requests(self)
        self.figures: list[FigureRecord] = []
        self.variables: list[VariableInfo] = []
        self.logs: deque[tuple[float, str, str]] = deque(maxlen=2000)
        self.problems: deque[tuple[float, str, str]] = deque(maxlen=500)
        self.report_basket: list[str] = []
        #: Online AI providers the user agreed to send summaries to (§11.5), for this server.
        self.ai_consent: set[str] = set()
        #: Files loaded recently, most recent first (§6.3).
        self.recent_files: list[str] = []
        #: ``[web] code_execution``: Python terminal, scripts and code of the AI allowed.
        self.code_execution = bool(self.config.get("web.code_execution", True))
        self.root = Path(project).resolve()
        self.roots = [(self.root / r).resolve() for r in self.config.get("web.roots", ["."])]
        if self.root not in self.roots:
            self.roots.insert(0, self.root)
        #: Categorical slot of each signal name: a signal keeps its color in every view (§7.6).
        self.signal_colors: dict[str, int] = {}
        #: Background work that outlives the browser tabs (§3.4): acquisition, real time,
        #: batches. ``seedlink_factory`` replaces the SeedLink client (tests).
        self.seedlink_factory: Callable | None = None
        self.acquisition: Any = None
        self.acquisition_progress: Any = None
        self.realtime: RealtimeRun | None = None
        self.batches: list[BatchRun] = []
        self.version = 0
        self._origin = threading.local()
        self._figure_counter = itertools.count(1)
        self.terminal = PythonTerminal(
            session, scrollback=int(self.config.get("web.scrollback", 10000)) * 80)
        self._initial_ns = dict(self.terminal.console.ns)
        self.terminal.on_executed.append(self.refresh_variables)
        self.terminal.console.param_form = self.request_form
        self.terminal.console.review_handler = self.request_review
        self.terminal.console.ai_handler = self.ask_ai_from_terminal
        self.terminal.console.edit_handler = self.open_in_editor
        self.terminal.console.quit_handler = lambda: self.terminal.write(
            "The Python terminal cannot quit the server: use Ctrl+C where `onthesignal web` "
            "runs.\n")
        self.terminal.console.ns["plot"] = self.plot
        self._initial_ns["plot"] = self.plot
        session.display_handler = self.display

    # ------------------------------------------------------------------ channels
    def connect(self, client_id: str) -> Channel:
        channel = Channel()
        self.channels[client_id] = channel
        return channel

    def disconnect(self, client_id: str) -> None:
        self.channels.pop(client_id, None)

    def broadcast(self, event: dict) -> None:
        for channel in list(self.channels.values()):
            channel.push(event)

    def origin(self) -> str | None:
        """Browser tab that started the work running in this thread (None: terminal, AI)."""
        return getattr(self._origin, "client", None)

    def to_origin(self, event: dict) -> None:
        """Send to the tab that started the work, or to every tab."""
        client = self.origin()
        if client is not None and client in self.channels:
            self.channels[client].push(event)
        else:
            self.broadcast(event)

    def bump(self) -> None:
        self.version += 1
        self.session.touch()

    # ------------------------------------------------------------------ log, problems
    def log(self, source: str, text: str) -> None:
        """Output panel of every tab, and the journal ``.onthesignal/logs/web.log`` (§12.2)."""
        self.logs.append((time.time(), source, text))
        log.info("[%s] %s", source, text)
        self.broadcast({"type": "log"})

    def remember_file(self, path: Any) -> None:
        name = str(path)
        if name in self.recent_files:
            self.recent_files.remove(name)
        self.recent_files.insert(0, name)
        del self.recent_files[10:]

    def problem(self, level: str, text: str) -> None:
        self.problems.append((time.time(), level, text))
        self.broadcast({"type": "problem", "level": level, "text": text})

    def notify(self, text: str, level: str = "info") -> None:
        self.broadcast({"type": "notify", "text": text, "level": level})

    # ------------------------------------------------------------------ display
    def display(self, obj: Any, show: bool, save: str | None) -> None:
        """``session.display_handler``: open the result in a tab, print it in the terminal."""
        in_terminal = self.terminal.in_terminal_thread()
        if in_terminal:
            self.terminal.display(obj, show, save)
        elif save and isinstance(obj, Result):
            self.terminal.display.figure(obj, False, save)
        if isinstance(obj, Signal):
            self.to_origin({"type": "open", "what": "signal", "name": obj.name})
        elif isinstance(obj, Result):
            for w in obj.warnings:
                self.problem("warning", f"{obj.name or obj.kind}: {w}")
            if obj.kind == "signal":
                name = obj.signals[0].get("name") if obj.signals else ""
                if name:
                    self.to_origin({"type": "open", "what": "signal", "name": name})
            elif show and obj.name:
                self.to_origin({"type": "open", "what": "result", "name": obj.name})

    def capture_figures(self) -> list[FigureRecord]:
        """``plt.show()`` of the web interface: open figures become ``Figures`` objects."""
        import matplotlib.pyplot as plt

        records = []
        for num in plt.get_fignums():
            fig = plt.figure(num)
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
            title = fig.get_suptitle()
            if not title and fig.axes:
                title = fig.axes[0].get_title()
            record = FigureRecord(f"Figure {next(self._figure_counter)}", title, buffer.getvalue())
            self.figures.append(record)
            records.append(record)
            plt.close(fig)
        for record in records:
            self.broadcast({"type": "open", "what": "figure", "name": record.name})
        if records:
            self.bump()
        return records

    def plot(self, *items: Any, title: str = "", labels: list[str] | None = None,
             x_label: str = "x", y_label: str = "y") -> None:
        """Interactive chart in a tab (web specification §10.3).

        ``plot(y)``, ``plot(x, y)`` and ``plot(x, y1, y2, …)`` draw numpy arrays (``labels``
        names the curves); ``plot(S1, S2)`` overlays signals of the session in one panel.
        """
        from .figures import arrays_figure

        if items and all(isinstance(i, Signal) for i in items):
            names = [s.name for s in items if s.name in self.session.signals]
            if len(names) != len(items):
                raise ParameterError("plot(): the signals must be in the session "
                                     "(assign them to a variable first)")
            self.to_origin({"type": "open", "what": "signals", "names": names,
                            "overlay": True})
            return
        x = items[0] if len(items) > 1 else None
        ys = list(items[1:] if len(items) > 1 else items)
        spec, data = arrays_figure(title, x, ys, labels, x_label, y_label)
        record = FigureRecord(f"Plot {next(self._figure_counter)}", title, b"",
                              spec.to_dict(), data)
        self.figures.append(record)
        self.to_origin({"type": "open", "what": "figure", "name": record.name})
        self.bump()

    def refresh_variables(self) -> None:
        """Inventory of the terminal namespace for the ``Variables`` group."""
        ns = self.terminal.console.ns
        out = []
        for name, value in list(ns.items()):
            if name in self._initial_ns and self._initial_ns[name] is value:
                continue  # API functions, np, session: not user variables
            info = describe_variable(name, value)
            if info is not None:
                out.append(info)
        self.variables = sorted(out, key=lambda v: v.name)
        self.bump()

    # ------------------------------------------------------------------ questions
    def request_form(self, cmd: Any, signals: list[Signal], defaults: dict) -> dict | None:
        """Graphical form for a ``/command`` typed without parameters in the terminal."""
        self.terminal.write(f"Form of /{cmd.name} opened in the browser…\n")
        return self.requests.ask({"type": "form", "command": cmd.name,
                                  "signals": [s.name for s in signals], "defaults": defaults})

    def request_review(self, path: Path, original: str, proposed: str) -> str | None:
        """Diff view of a file proposed by the AI (``/ai_script``, §9.6): the accepted text,
        or ``None`` when the user refuses it."""
        self.terminal.write(f"Proposal for {Path(path).name} opened in the browser: accept or "
                            "reject it there…\n")
        answer = self.requests.ask({"type": "review", "path": str(path), "original": original,
                                    "proposed": proposed})
        return None if answer is None else str(answer)

    # ------------------------------------------------------------------ signals
    def color_of(self, name: str) -> str:
        """Color token of a signal; slots are given in the order of the session (§7.6)."""
        for known in [*self.session.signals, name]:
            if known not in self.signal_colors:
                self.signal_colors[known] = len(self.signal_colors) % 8
        return f"series:{self.signal_colors[name]}"

    def colors(self, names: Sequence[str]) -> dict[str, str]:
        return {n: self.color_of(n) for n in names}

    def result_color(self, result: Result) -> str:
        """Color of a result in a comparison: the color of its (first) signal."""
        name = str(result.signals[0].get("name") or "") if result.signals else ""
        return self.color_of(name or str(result.name))

    def rename_signal(self, old: str, new: str) -> None:
        """Rename a signal in the session and in the terminal namespace."""
        from .. import api

        ns = self.terminal.console.ns
        ns.pop(old, None)
        api.rename_sig(old, new)
        ns[new] = self.session.signals[new]
        if old in self.signal_colors and new not in self.signal_colors:
            self.signal_colors[new] = self.signal_colors.pop(old)
        self.session.history.append(f"rename_sig({old!r}, {new!r})")

    def remove_signal(self, name: str) -> None:
        """Remove a signal from the session and from the terminal namespace."""
        from .. import api

        api.rm_sig(name)
        self.terminal.console.ns.pop(name, None)
        self.session.history.append(f"rm_sig({name!r})")

    def open_in_editor(self, path: Any) -> None:
        self.to_origin({"type": "open", "what": "file", "name": str(path)})

    def ask_ai_from_terminal(self, question: str) -> None:
        self.terminal.write("Question sent to the AI chat (right-hand panel).\n")
        self.broadcast({"type": "chat_question", "text": question})

    def warn(self, message: str, category: type = OnTheSignalWarning) -> None:
        """Warnings raised outside the terminal (forms, jobs) are shown as problems."""
        self.problem("warning", message)
        self.notify(message, "warning")

    # ------------------------------------------------------------------ files
    def confined_files(self, patterns: Sequence[str]) -> list[Path]:
        """Files matching glob patterns of the project; files outside its roots are refused."""
        from ..scripts import expand_files
        from .security import confine

        files = []
        for path in expand_files([str(p) for p in patterns]):
            try:
                files.append(confine(path, self.roots))
            except PermissionError as exc:
                raise ParameterError(str(exc)) from exc
        return [f for f in files if f.is_file()]

    # ------------------------------------------------------------------ SeedLink
    def list_streams(self, server: str, port: int | None, network: str | None,
                     station: str | None) -> list:
        from ..seedlink.client import list_streams

        return list_streams(server, port, network, station, factory=self.seedlink_factory)

    def start_acquisition(self, server: str, streams: Sequence, port: int | None,
                          duration: float, outdir: Path, load: bool,
                          client: str | None = None) -> Job:
        """SeedLink acquisition as a server job: it goes on when the browser is closed (§8.1)."""
        from ..seedlink.acquisition import Acquisition

        if self.acquisition is not None:
            raise ParameterError("An acquisition is already running: stop it first")
        acq = Acquisition(server, list(streams), port=port, duration=duration, outdir=outdir,
                          on_progress=lambda p: setattr(self, "acquisition_progress", p),
                          client_factory=self.seedlink_factory)
        self.acquisition, self.acquisition_progress = acq, None

        def work(job: Job) -> Any:
            result = acq.run()
            if load:
                from .. import api

                for path in result.files:
                    api.load(path)
            return result

        def done(job: Job) -> None:
            self.acquisition = None
            if job.state == "done":
                files = ", ".join(p.name for p in job.result.files) or "no file"
                self.notify(f"Acquisition finished: {files}", "positive")
            elif job.state == "failed":
                self.notify(f"Acquisition failed: {job.error}", "negative")
            self.broadcast({"type": "acquisition"})

        job = self.jobs.start("acquisition", work, kind="acquisition", client=client,
                              on_done=done, cancel=acq.stop)
        self.broadcast({"type": "acquisition"})
        return job

    def start_realtime(self, settings: RealtimeSettings, client: str | None = None
                       ) -> RealtimeRun:
        """Real-time dashboard (§8.2), one at a time."""
        if self.realtime is not None and self.realtime.running:
            raise ParameterError("A real-time session is already running: stop it first")
        run = RealtimeRun(settings, self.seedlink_factory)
        self.realtime = run

        def done(job: Job) -> None:
            if job.state == "failed":
                self.notify(f"Real time stopped: {job.error}", "negative")
            self.broadcast({"type": "realtime"})

        self.jobs.start("real time", run.run, kind="realtime", client=client, on_done=done,
                        cancel=run.stop)
        self.broadcast({"type": "realtime"})
        return run

    # ------------------------------------------------------------------ batches
    def start_batch(self, settings: BatchSettings, client: str | None = None) -> BatchRun:
        """Batch processing (§8.5): one row per file and signal, errors kept in the table."""
        from .security import confine

        files = self.confined_files(settings.patterns)
        if not files:
            raise ParameterError(f"No file matches {' '.join(settings.patterns)}")
        if settings.out:
            target = confine(settings.out, self.roots)
            target.parent.mkdir(parents=True, exist_ok=True)
            settings.out = str(target)
        run = BatchRun(settings, files)
        self.batches.append(run)
        del self.batches[:-20]

        def done(job: Job) -> None:
            text = (f"{run.title}: {len(run.rows)} signal(s), {run.failures} failure(s)"
                    + (f", table written to {run.out.name}" if run.out else ""))
            self.notify(text, "positive" if job.state == "done" and not run.failures
                        else "warning")
            self.broadcast({"type": "batch", "id": run.id})

        self.jobs.start(f"batch {settings.target}", run.run, kind="batch", client=client,
                        on_done=done, cancel=run.stop)
        return run

    def batch(self, run_id: int) -> BatchRun | None:
        return next((b for b in self.batches if b.id == run_id), None)


__all__ = ["Channel", "FigureRecord", "Job", "Jobs", "Requests", "VariableInfo", "WebState",
           "describe_variable"]
