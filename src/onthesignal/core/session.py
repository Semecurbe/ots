"""Session: loaded signals, results, configuration and history (rule R6).

There is no global state in the computation core: a :class:`Session` carries everything.
The console and the web interface each use one session. The public API works on the
*current* session, held in a context variable; :func:`set_session` can also make a session
the default of the process, for threads that do not inherit the context (web workers).

The session is observable: every change increments :attr:`Session.version` and is sent to
the listeners registered with :meth:`Session.subscribe` (rule R13 of the web specification).
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from .config import Config
from .errors import ParameterError
from .result import Result
from .signal import Signal
from .units import COUNTS, pretty_unit


def format_duration(seconds: float) -> str:
    """``HH:MM:SS`` (with milliseconds when needed); short durations in seconds."""
    if seconds < 1:
        return f"{seconds:.3f} s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    text = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
    frac = s - int(s)
    if frac > 5e-4:
        text += f".{int(round(frac * 1000)):03d}"
    return text


class Session:
    """Working session.

    Parameters
    ----------
    config : Config, optional
        Configuration (loaded from the configuration files by default).
    interactive : bool
        True in the console: analyses then display their results automatically.
    """

    def __init__(self, config: Config | None = None, interactive: bool = False) -> None:
        self.config = config or Config.load()
        self.interactive = interactive
        self.signals: dict[str, Signal] = {}
        self.results: list[Result] = []
        self.history: list[str] = []
        #: Callable ``handler(obj, show, save)`` installed by the user interface to display
        #: results and signals; ``None`` falls back to plain text and matplotlib.
        self.display_handler: Any = None
        #: Incremented at every change (signals, results, attributes, history).
        self.version = 0
        self._result_counter = 0
        self._listeners: list[Callable[[str, dict], None]] = []
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ events
    def subscribe(self, callback: Callable[[str, dict], None]) -> Callable[[], None]:
        """Call ``callback(event, data)`` after every change; returns the unsubscribe function.

        Callbacks may run in any thread: a user interface must hand the event over to its own
        event loop instead of updating widgets directly.
        """
        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def notify(self, event: str = "changed", **data: Any) -> None:
        """Signal a change: ``signal_added``, ``result_added``, ``changed``..."""
        with self.lock:
            self.version += 1
        for callback in list(self._listeners):
            try:
                callback(event, data)
            except Exception:  # a faulty listener must not break the computation
                logging.getLogger(__name__).exception("Session listener failed")

    def touch(self) -> None:
        """Signal a change that cannot be detected otherwise (``S1.unit = "V"``)."""
        self.notify("changed")

    # ------------------------------------------------------------------ signals
    def next_name(self) -> str:
        """First free automatic name (``S1``, ``S2``...)."""
        n = 1
        while f"S{n}" in self.signals:
            n += 1
        return f"S{n}"

    def add_signal(self, signal: Signal, name: str | None = None) -> str:
        """Register ``signal`` under ``name`` (automatic name by default) and return the name."""
        name = name or self.next_name()
        if not name.isidentifier():
            raise ParameterError(f"Invalid signal name {name!r} (must be a Python identifier)")
        signal.name = name
        with self.lock:
            self.signals[name] = signal
        self.notify("signal_added", name=name)
        return name

    def get_signal(self, ref: Signal | str) -> Signal:
        """Signal from an object or a name."""
        if isinstance(ref, Signal):
            return ref
        if isinstance(ref, str) and ref in self.signals:
            return self.signals[ref]
        known = ", ".join(self.signals) or "none loaded"
        raise ParameterError(f"Unknown signal {ref!r} (signals: {known})")

    def remove_signal(self, name: str) -> None:
        self.get_signal(name)
        with self.lock:
            del self.signals[name]
        self.notify("signal_removed", name=name)

    def rename_signal(self, old: str, new: str) -> None:
        signal = self.get_signal(old)
        if not new.isidentifier():
            raise ParameterError(f"Invalid signal name {new!r}")
        if new in self.signals and self.signals[new] is not signal:
            raise ParameterError(f"A signal named {new} already exists")
        with self.lock:
            del self.signals[old]
        self.add_signal(signal, new)

    def sync_namespace(self, namespace: dict[str, Any]) -> None:
        """Keep the session in step with the console variables.

        Signals assigned to new variables are registered under the variable name
        (``S3 = S1 + S2`` creates ``S3``); deleted variables are removed from the session.
        A second variable pointing to an already registered signal is treated as an alias.
        """
        current = {
            k: v for k, v in namespace.items() if isinstance(v, Signal) and not k.startswith("_")
        }
        by_id = {id(s): n for n, s in self.signals.items()}
        changed = False
        with self.lock:
            for name, sig in current.items():
                if self.signals.get(name) is sig:
                    continue
                owner = by_id.get(id(sig))
                if owner is not None and owner in current and owner != name:
                    continue
                if owner is not None:
                    del self.signals[owner]
                if not name.isidentifier():
                    continue
                sig.name = name
                self.signals[name] = sig
                changed = True
            for name in list(self.signals):
                if name not in current:
                    del self.signals[name]
                    changed = True
        if changed:
            self.notify("signals_changed")

    def list_rows(self) -> list[dict[str, str]]:
        """One row per signal, as displayed by ``list_sig()``."""
        rows = []
        for name, s in self.signals.items():
            sens = "—" if s.unit == COUNTS else f"{s.sensitivity:.4g} {pretty_unit(s.unit)}/c"
            rows.append(
                {
                    "Name": name,
                    "Title": s.title or "—",
                    "NSLC": s.id,
                    "fs (Hz)": f"{s.sampling_rate:.1f}",
                    "Start (UTC)": str(s.starttime),
                    "Duration": format_duration(s.duration),
                    "N": str(s.npts),
                    "Unit": pretty_unit(s.unit),
                    "Sensitivity": sens,
                    "Source": os.path.basename(s.source) or "—",
                }
            )
        return rows

    def list_text(self) -> str:
        """Plain-text table of the signals."""
        rows = self.list_rows()
        if not rows:
            return "No signal loaded. Use load('file.mseed') or /load."
        keys = list(rows[0])
        widths = {k: max(len(k), *(len(r[k]) for r in rows)) + 2 for k in keys}
        lines = [" " + "".join(k.ljust(widths[k]) for k in keys).rstrip()]
        for r in rows:
            lines.append(" " + "".join(r[k].ljust(widths[k]) for k in keys).rstrip())
        return "\n".join(lines)

    # ------------------------------------------------------------------ results
    def add_result(self, result: Result) -> str:
        """Register ``result`` under a stable session name (``R1``, ``R2``...) and return it."""
        with self.lock:
            if not result.name:
                self._result_counter += 1
                result.name = f"R{self._result_counter}"
            self.results.append(result)
        self.notify("result_added", name=result.name)
        return result.name

    def get_result(self, ref: Result | str) -> Result:
        """Result from an object or a session name (``R3``)."""
        if isinstance(ref, Result):
            return ref
        for r in self.results:
            if r.name == ref:
                return r
        known = ", ".join(r.name for r in self.results) or "none"
        raise ParameterError(f"Unknown result {ref!r} (results: {known})")

    def remove_result(self, ref: Result | str) -> None:
        result = self.get_result(ref)
        with self.lock:
            self.results = [r for r in self.results if r is not result]
        self.notify("result_removed", name=result.name)

    def last_results(self, n: int | None = None) -> list[Result]:
        return self.results[-n:] if n else list(self.results)


_current: ContextVar[Session | None] = ContextVar("onthesignal_session", default=None)
_default: Session | None = None


def get_session() -> Session:
    """Current session: the context one, else the process default, else a new session."""
    session = _current.get()
    if session is None:
        if _default is not None:
            return _default
        session = Session()
        _current.set(session)
    return session


def set_session(session: Session, *, default: bool = False) -> None:
    """Make ``session`` the current session.

    ``default=True`` also makes it the session of the threads that do not inherit the
    context, such as the worker threads of the web interface.
    """
    global _default
    _current.set(session)
    if default:
        _default = session
