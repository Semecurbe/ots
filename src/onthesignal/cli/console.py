"""Interactive console: Python expressions, ``/`` commands and the AI mode (spec §15)."""

from __future__ import annotations

import ast
import inspect
import os
import re
import shlex
import sys
import time
import traceback
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .. import api
from .._version import __version__
from ..core.config import Config
from ..core.errors import OnTheSignalError, OnTheSignalWarning
from ..core.result import Result
from ..core.session import Session, set_session
from ..core.signal import Signal
from . import commands
from .display import ConsoleDisplay
from .forms import prompt_ask

PROMPT = "ots> "
AI_PROMPT = "ai> "
_HELP_QUERY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\?$")


def _matplotlib_inputhook(context: Any) -> None:
    """Keep matplotlib windows responsive while the console waits for input."""
    while not context.input_is_ready():
        if "matplotlib.pyplot" not in sys.modules:
            time.sleep(0.05)
            continue
        from matplotlib import _pylab_helpers

        manager = _pylab_helpers.Gcf.get_active()
        if manager is None:
            time.sleep(0.05)
        else:
            manager.canvas.start_event_loop(0.05)


def _checksum(data: np.ndarray) -> tuple:
    """Cheap fingerprint of samples: identity, size and sum (NaN-safe)."""
    total = float(np.sum(data))
    return (id(data), data.size, total if total == total else "nan",
            int(np.count_nonzero(np.isnan(data))) if total != total else 0)


class OnTheSignalConsole:
    """The onthesignal terminal console.

    Parameters
    ----------
    files : sequence of str
        Files loaded at start-up.
    config : Config, optional
        Configuration (configuration files by default).
    ask : callable, optional
        ``ask(label, default) -> str`` used by forms (prompt_toolkit by default; tests inject
        their own).
    forms : bool
        Open parameter forms when a command is typed without parameters.
    session : Session, optional
        Existing session to work on (the web interface shares its session with its terminal).
    display : ConsoleDisplay, optional
        Text output (the web terminal writes to the browser instead of the standard output).
    install_display : bool
        Install the console display as ``session.display_handler`` (False when another user
        interface already displays the results).

    Attributes
    ----------
    param_form : callable, optional
        ``param_form(command, signals, defaults) -> dict | None`` replaces the text forms
        (graphical form of the web interface); ``None`` cancels the command.
    ai_handler : callable, optional
        ``ai_handler(question)`` receives ``/ai`` questions (chat of the web interface).
    edit_handler : callable, optional
        ``edit_handler(path)`` opens a file for ``/edit_script`` and ``/context`` instead of
        the terminal editor (editor of the web interface).
    quit_handler : callable, optional
        Replaces ``/quit`` (the web terminal cannot quit the server).
    """

    def __init__(self, files: Sequence[str] = (), config: Config | None = None,
                 ask: Callable[[str, str], str] | None = None, forms: bool = True,
                 session: Session | None = None, display: ConsoleDisplay | None = None,
                 install_display: bool = True) -> None:
        self.session = session or Session(config=config or Config.load(), interactive=True)
        if session is None:
            set_session(self.session)
        self.display = display or ConsoleDisplay(self.session)
        if install_display:
            self.session.display_handler = self.display
        self.ask = ask or prompt_ask
        self.forms = forms
        self.param_form: Callable[..., dict | None] | None = None
        self.ai_handler: Callable[[str], None] | None = None
        self.edit_handler: Callable[[Path], None] | None = None
        self.quit_handler: Callable[[], None] | None = None
        self.debug = False
        self.running = True
        self.mode = "python"
        self.assistant: Any = None
        self.known: set[str] = set()
        self.ns: dict[str, Any] = self._namespace()
        self.sync()
        if install_display:
            warnings.showwarning = self._show_warning
        for path in files:
            self.execute(f"/load {shlex.quote(path)} --defaults")

    # ------------------------------------------------------------------ user dialogue
    # These methods make the console a "user host" for the assistant (UserHost protocol).
    def info(self, text: str) -> None:
        self.display.info(text)

    def warning(self, text: str) -> None:
        self.display.warning(text)

    def error(self, text: str) -> None:
        self.display.error(text)

    def markdown(self, text: str) -> None:
        from rich.markdown import Markdown

        self.display.console.print(Markdown(text))

    def confirm(self, question: str, details: str = "", key: str | None = None) -> bool:
        if details:
            self.display.info(details)
        answer = self.ask(f"{question} (y/N)", "n")
        return answer.strip().lower() in ("y", "yes", "o", "oui")

    # ------------------------------------------------------------------ namespace
    def _namespace(self) -> dict[str, Any]:
        from .. import scripts

        ns: dict[str, Any] = {"__name__": "__onthesignal__", "np": np, "Signal": Signal,
                              "Result": Result, "session": self.session}
        for name in api.__all__:
            ns[name] = getattr(api, name)
        ns.update({"run_script": scripts.run_script, "batch": scripts.batch})
        from ..core.registry import commands as registered

        for cmd in registered():
            if cmd.name not in ns:
                ns[cmd.name] = api._make(cmd.name)
            for alias in cmd.aliases:
                ns.setdefault(alias, ns[cmd.name])
        return ns

    def sync(self) -> None:
        """Synchronize console variables and session signals and results (both directions).

        Results are available under their session names (``R1``, ``R2``...) unless a user
        variable already holds that name.
        """
        bound = {id(v) for k, v in self.ns.items() if isinstance(v, Signal) and k[:1] != "_"}
        for name, sig in list(self.session.signals.items()):
            if self.ns.get(name) is sig:
                continue
            if name in self.known and name not in self.ns:
                continue  # deleted by the user (del S3): removed from the session below
            if name not in self.known and id(sig) in bound:
                continue  # S5 = make_noise(...): the variable name wins over S3
            self.ns[name] = sig
        self.session.sync_namespace(self.ns)
        self.known = set(self.session.signals)
        names = {r.name: r for r in self.session.results if r.name}
        for name, result in names.items():
            current = self.ns.get(name)
            if current is None or (isinstance(current, Result) and current is not result):
                self.ns[name] = result
        for name in [k for k, v in self.ns.items() if isinstance(v, Result)]:
            if re.fullmatch(r"R\d+", name) and name not in names:
                del self.ns[name]

    def _show_warning(self, message: Any, category: type, filename: str, lineno: int,
                      file: Any = None, line: str | None = None) -> None:
        if issubclass(category, OnTheSignalWarning) or not self.debug:
            if issubclass(category, (OnTheSignalWarning, UserWarning)):
                self.display.warning(str(message))
            return
        self.display.warning(f"{category.__name__}: {message} ({filename}:{lineno})")

    # ------------------------------------------------------------------ execution
    def execute(self, text: str) -> None:
        """Run one console input: ``/command``, AI question or Python code."""
        text = text.strip()
        if not text:
            return
        self.sync()  # signals loaded by another interface (web) become variables first
        try:
            if text.startswith("/"):
                commands.execute(self, text)
            elif self.mode == "ai":
                self.ask_ai(text)
            elif _HELP_QUERY.match(text):
                self.show_help(_HELP_QUERY.match(text).group(1))  # type: ignore[union-attr]
            else:
                self.run_python(text)
        except KeyboardInterrupt:
            self.display.error("Interrupted")
        except OnTheSignalError as exc:
            self.display.error(str(exc))
        except Exception as exc:  # the console must never die on a user error
            self.display.error(f"{type(exc).__name__}: {exc}")
            if self.debug:
                self.display.info(traceback.format_exc())
        finally:
            self.sync()
            self.session.touch()

    def show_help(self, expression: str) -> None:
        """``noise?`` or ``S1.slice?``: signature and documentation of an object."""
        obj = eval(compile(expression, "<help>", "eval"), self.ns)  # noqa: S307 (user console)
        try:
            signature = f"{expression}{inspect.signature(obj)}"
        except (TypeError, ValueError):
            signature = f"{expression}: {type(obj).__name__}"
        doc = inspect.getdoc(obj) or "No documentation."
        self.display.info(f"{signature}\n\n{doc}")

    def _fingerprints(self, source: str) -> dict[str, tuple]:
        """Checksums of the signals named in ``source`` (in-place changes of their samples)."""
        out = {}
        for name, sig in self.session.signals.items():
            if re.search(rf"\b{re.escape(name)}\b", source):
                out[name] = (sig, sig.data_version, _checksum(sig.data))
        return out

    def run_python(self, source: str) -> None:
        tree = ast.parse(source, mode="exec")
        last = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            node = tree.body.pop()
            assert isinstance(node, ast.Expr)
            last = ast.Expression(node.value)
        before = self._fingerprints(source)
        try:
            if tree.body:
                exec(compile(tree, "<console>", "exec"), self.ns)  # noqa: S102 (user console)
            if last is not None:
                value = eval(compile(last, "<console>", "eval"), self.ns)  # noqa: S307
                if value is not None and id(value) not in self.display.displayed:
                    self.display.info(repr(value))
        finally:
            # S4.data[:100] = 0 changes the samples without assigning them: record it too.
            for sig, version, checksum in before.values():
                if sig.data_version == version and _checksum(sig.data) != checksum:
                    sig.mark_modified()

    def ask_ai(self, text: str) -> None:
        if self.ai_handler is not None:
            self.ai_handler(text)
            return
        from ..ai import get_assistant

        if self.assistant is None:
            self.assistant = get_assistant(self)
        self.assistant.ask(text)

    # ------------------------------------------------------------------ prompt loop
    def toolbar(self) -> str:
        provider = self.session.config.get("ai.provider", "")
        model = self.session.config.get("ai.model", "") or "default model"
        mode = "AI" if self.mode == "ai" else "Python"
        n = len(self.session.signals)
        return (f" {mode} mode │ {n} signal{'s' if n != 1 else ''} │ AI: {provider} ({model}) │ "
                f"{Path.cwd()} │ / for commands")

    def run(self) -> int:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory

        from .completion import ConsoleCompleter

        history = Path(os.path.expanduser(self.session.config.get(
            "console.history_file", "~/.local/state/onthesignal/history")))
        history.parent.mkdir(parents=True, exist_ok=True)
        prompt: PromptSession[str] = PromptSession(history=FileHistory(str(history)),
                               completer=ConsoleCompleter(self), complete_while_typing=True,
                               bottom_toolbar=self.toolbar)
        n = len(self.session.signals)
        loaded = f" — {n} signal(s) loaded ({', '.join(self.session.signals)})" if n else ""
        self.display.info(f"onthesignal {__version__}{loaded}. Type / for the list of commands.")
        while self.running:
            try:
                text = prompt.prompt(AI_PROMPT if self.mode == "ai" else PROMPT,
                                     inputhook=_matplotlib_inputhook)
            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            self.execute(text)
        return 0
