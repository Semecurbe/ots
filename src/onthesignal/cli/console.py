"""Interactive console: Python expressions, ``/`` commands and the AI mode (spec §15)."""

from __future__ import annotations

import ast
import os
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
    """

    def __init__(self, files: Sequence[str] = (), config: Config | None = None,
                 ask: Callable[[str, str], str] | None = None, forms: bool = True) -> None:
        self.session = Session(config=config or Config.load(), interactive=True)
        set_session(self.session)
        self.display = ConsoleDisplay(self.session)
        self.session.display_handler = self.display
        self.ask = ask or prompt_ask
        self.forms = forms
        self.debug = False
        self.running = True
        self.mode = "python"
        self.assistant: Any = None
        self.known: set[str] = set()
        self.ns: dict[str, Any] = self._namespace()
        warnings.showwarning = self._show_warning
        for path in files:
            self.execute(f"/load {shlex.quote(path)} --defaults")

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
        """Synchronize console variables and session signals (both directions)."""
        for name, sig in list(self.session.signals.items()):
            if self.ns.get(name) is not sig and not (name in self.known and name not in self.ns):
                self.ns[name] = sig
        self.session.sync_namespace(self.ns)
        self.known = set(self.session.signals)

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
        try:
            if text.startswith("/"):
                commands.execute(self, text)
            elif self.mode == "ai":
                self.ask_ai(text)
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

    def run_python(self, source: str) -> None:
        tree = ast.parse(source, mode="exec")
        last = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            node = tree.body.pop()
            assert isinstance(node, ast.Expr)
            last = ast.Expression(node.value)
        if tree.body:
            exec(compile(tree, "<console>", "exec"), self.ns)  # noqa: S102 (user console)
        if last is not None:
            value = eval(compile(last, "<console>", "eval"), self.ns)  # noqa: S307
            if value is not None and id(value) not in self.display.displayed:
                self.display.info(repr(value))

    def ask_ai(self, text: str) -> None:
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
