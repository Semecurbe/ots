"""Session: loaded signals, results, configuration and history (rule R6).

There is no global state in the computation core: a :class:`Session` carries everything.
The console uses one session; the future web interface will create one per user. The public
API works on the *current* session, held in a context variable.
"""

from __future__ import annotations

import os
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
        self.signals[name] = signal
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
        del self.signals[name]

    def rename_signal(self, old: str, new: str) -> None:
        signal = self.get_signal(old)
        if not new.isidentifier():
            raise ParameterError(f"Invalid signal name {new!r}")
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
        for name, sig in current.items():
            if self.signals.get(name) is sig:
                continue
            owner = by_id.get(id(sig))
            if owner is not None and owner in current and owner != name:
                continue
            if owner is not None:
                del self.signals[owner]
            self.add_signal(sig, name)
        for name in list(self.signals):
            if name not in current:
                del self.signals[name]

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
    def add_result(self, result: Result) -> None:
        self.results.append(result)

    def last_results(self, n: int | None = None) -> list[Result]:
        return self.results[-n:] if n else list(self.results)


_current: ContextVar[Session | None] = ContextVar("onthesignal_session", default=None)


def get_session() -> Session:
    """Current session (created on first use)."""
    session = _current.get()
    if session is None:
        session = Session()
        _current.set(session)
    return session


def set_session(session: Session) -> None:
    """Make ``session`` the current session."""
    _current.set(session)
