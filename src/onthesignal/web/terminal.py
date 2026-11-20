"""Python terminal of the web interface (web specification §10).

The terminal is the console of the command-line version (same namespace, same ``/`` commands,
same synchronization with the session) running in a dedicated thread of the server. Its input
comes from the browser terminals (xterm.js) through a pipe; its output is a VT100 stream sent
back to them. prompt_toolkit edits the input line exactly as in a real terminal.
"""

from __future__ import annotations

import asyncio
import codeop
import ctypes
import logging
import os
import queue
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TextIO, cast

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from ..cli.console import PROMPT, OnTheSignalConsole
from ..cli.display import ConsoleDisplay
from ..core.session import Session

log = logging.getLogger(__name__)
CONTINUATION = "...  "
_PENDING = object()


# ---------------------------------------------------------------------------------- output
class TerminalWriter:
    """File-like object: everything written goes to the browser terminals."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit

    def write(self, text: str) -> int:
        if text:
            self._emit(text)
        return len(text)

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True


class ThreadRoutedStream:
    """``sys.stdout`` / ``sys.stderr`` replacement: the terminal thread writes to the terminal.

    Other threads (server, workers) keep writing to the original stream.
    """

    def __init__(self, original: Any) -> None:
        self.original = original
        self.routes: dict[int, TerminalWriter] = {}

    def _target(self) -> Any:
        return self.routes.get(threading.get_ident(), self.original)

    def write(self, text: str) -> int:
        return self._target().write(text)

    def flush(self) -> None:
        target = self._target()
        if hasattr(target, "flush"):
            target.flush()

    def isatty(self) -> bool:
        return threading.get_ident() in self.routes

    def __getattr__(self, name: str) -> Any:
        return getattr(self.original, name)


def install_stream_routing() -> tuple[ThreadRoutedStream, ThreadRoutedStream]:
    """Route ``print`` of the terminal thread to the terminal (idempotent)."""
    if not isinstance(sys.stdout, ThreadRoutedStream):
        sys.stdout = ThreadRoutedStream(sys.stdout)  # type: ignore[assignment]
    if not isinstance(sys.stderr, ThreadRoutedStream):
        sys.stderr = ThreadRoutedStream(sys.stderr)  # type: ignore[assignment]
    return sys.stdout, sys.stderr  # type: ignore[return-value]


class TerminalDisplay(ConsoleDisplay):
    """Text output of the console in the terminal; figures go to the work area instead."""

    def figure(self, result: Any, show: bool, save: str | None) -> None:
        if save:
            from ..plot import plot_result

            fig = plot_result(result)
            if fig is not None:
                fig.savefig(save, dpi=150)
                self.info(f"Figure saved to {save}")


# ---------------------------------------------------------------------------------- completion
class TerminalCompleter(Completer):
    """``/`` commands from the console completer, Python code from Jedi on the live objects."""

    def __init__(self, console: OnTheSignalConsole) -> None:
        from ..cli.completion import ConsoleCompleter

        self.console = console
        self.commands = ConsoleCompleter(console)

    def get_completions(self, document: Document, complete_event: object
                        ) -> Iterable[Completion]:
        if document.text.lstrip().startswith("/"):
            yield from self.commands.get_completions(document, complete_event)
            return
        try:
            import jedi
        except ImportError:  # jedi is part of the [web] extra
            yield from self.commands.get_completions(document, complete_event)
            return
        line, column = document.cursor_position_row + 1, document.cursor_position_col
        try:
            items = jedi.Interpreter(document.text, [self.console.ns]).complete(line, column)
        except Exception:  # completion must never break the input line
            return
        for item in items[:200]:
            typed = len(item.name) - len(item.complete or "")
            yield Completion(item.name, start_position=-typed, display_meta=item.type)


# ---------------------------------------------------------------------------------- terminal
class PythonTerminal:
    """The shared Python terminal: one per server, attached to every browser tab.

    Parameters
    ----------
    session : Session
        Session of the web interface (shared with the terminal namespace).
    history_file : str or Path
        Persistent input history (the one of the console).
    scrollback : int
        Characters of output kept to redraw the terminal when a browser tab (re)connects.
    """

    def __init__(self, session: Session, history_file: str | Path | None = None,
                 scrollback: int = 400_000) -> None:
        self.session = session
        self.history_file = Path(os.path.expanduser(str(history_file or session.config.get(
            "console.history_file", "~/.local/state/onthesignal/history"))))
        self.cols, self.rows = 120, 20
        self.busy = False
        self.ready = threading.Event()
        self.on_executed: list[Callable[[], None]] = []
        self.on_output: list[Callable[[str], None]] = []
        self._scrollback: deque[str] = deque()
        self._scrollback_size = 0
        self._scrollback_max = scrollback
        self._out_lock = threading.Lock()
        self._writer = TerminalWriter(self._emit)
        from rich.console import Console

        self.rich = Console(file=cast(TextIO, self._writer), force_terminal=True,
                            color_system="truecolor",
                            width=self.cols, highlight=False, soft_wrap=False)
        self.display = TerminalDisplay(session, console=self.rich)
        self.console = OnTheSignalConsole(session=session, display=self.display,
                                          install_display=False, forms=True,
                                          ask=self._ask)
        self._input: Any = None
        self._prompt: Any = None
        self._pending: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stopped = False

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Start the terminal thread (once)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="ots-terminal", daemon=True)
        self._thread.start()
        self.ready.wait(10)

    @property
    def thread_ident(self) -> int | None:
        return self._thread.ident if self._thread is not None else None

    def in_terminal_thread(self) -> bool:
        return self._thread is not None and threading.get_ident() == self._thread.ident

    def stop(self) -> None:
        self._stopped = True
        self._exit_prompt()

    # ------------------------------------------------------------------ output
    def _emit(self, text: str) -> None:
        with self._out_lock:
            self._scrollback.append(text)
            self._scrollback_size += len(text)
            while self._scrollback_size > self._scrollback_max and len(self._scrollback) > 1:
                self._scrollback_size -= len(self._scrollback.popleft())
        for callback in list(self.on_output):
            try:
                callback(text)
            except Exception:
                log.exception("Terminal output listener failed")

    def scrollback(self) -> str:
        with self._out_lock:
            return "".join(self._scrollback)

    def write(self, text: str) -> None:
        """Write to the terminal from any thread (messages of the interface)."""
        self._emit(text.replace("\n", "\r\n"))

    # ------------------------------------------------------------------ input
    def feed(self, data: str) -> None:
        """Keystrokes typed in a browser terminal."""
        if "\x03" in data and self.busy:
            self.interrupt()
            data = data.replace("\x03", "")
        if data and self._input is not None:
            self._input.send_text(data)

    def interrupt(self) -> bool:
        """Raise ``KeyboardInterrupt`` in the code being executed (Ctrl+C)."""
        ident = self.thread_ident
        if not self.busy or ident is None:
            return False
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident),
                                                   ctypes.py_object(KeyboardInterrupt))
        return True

    def submit(self, code: str) -> None:
        """Run ``code`` as if it had been typed (editor selection, palette, chat)."""
        self._pending.put(code)
        if not self.busy:
            self._exit_prompt()

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = max(20, int(cols)), max(4, int(rows))
        self.rich.width = self.cols
        app = getattr(self._prompt, "app", None)
        loop = getattr(app, "loop", None)
        if app is not None and app.is_running and loop is not None:
            loop.call_soon_threadsafe(app._on_resize)

    def _exit_prompt(self) -> None:
        app = getattr(self._prompt, "app", None)
        loop = getattr(app, "loop", None)
        if app is not None and app.is_running and loop is not None:
            def leave() -> None:
                if app.is_running and not app.future.done():
                    app.exit(result=_PENDING)

            loop.call_soon_threadsafe(leave)

    def _ask(self, label: str, default: str) -> str:
        """Text questions of the console forms (when no graphical form is installed)."""
        from prompt_toolkit import prompt

        suffix = f" [{default}]" if default else ""
        return prompt(f"  {label}{suffix}: ")

    # ------------------------------------------------------------------ thread
    def _key_bindings(self) -> Any:
        from prompt_toolkit.key_binding import KeyBindings

        kb = KeyBindings()

        @kb.add("enter")
        def _(event: Any) -> None:
            buffer = event.current_buffer
            text = buffer.text
            blank_last_line = "\n" in text and not buffer.document.current_line.strip()
            if self._complete(text) or (buffer.document.is_cursor_at_the_end and blank_last_line):
                buffer.validate_and_handle()
                return
            line = buffer.document.current_line
            indent = line[: len(line) - len(line.lstrip())]
            if line.rstrip().endswith(":"):
                indent += "    "
            buffer.insert_text("\n" + indent)

        return kb

    @staticmethod
    def _complete(text: str) -> bool:
        stripped = text.strip()
        if not stripped or stripped.startswith("/") or stripped.endswith("?"):
            return True
        try:
            return codeop.compile_command(text, "<console>", "exec") is not None
        except (SyntaxError, ValueError, OverflowError):
            return True  # let the console report the error

    def _run(self) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.application import create_app_session
        from prompt_toolkit.data_structures import Size
        from prompt_toolkit.history import FileHistory, InMemoryHistory
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.lexers import PygmentsLexer
        from prompt_toolkit.output.color_depth import ColorDepth
        from prompt_toolkit.output.vt100 import Vt100_Output
        from pygments.lexers.python import PythonLexer

        asyncio.set_event_loop(asyncio.new_event_loop())
        self._route_output()
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            history: Any = FileHistory(str(self.history_file))
        except OSError:
            history = InMemoryHistory()
        with create_pipe_input() as pipe:
            self._input = pipe
            output = Vt100_Output(cast(TextIO, self._writer),
                                  lambda: Size(rows=self.rows, columns=self.cols),
                                  term="xterm-256color", default_color_depth=ColorDepth.TRUE_COLOR,
                                  enable_cpr=False)
            with create_app_session(input=pipe, output=output):
                self._prompt = PromptSession(
                    history=history, completer=TerminalCompleter(self.console),
                    lexer=PygmentsLexer(PythonLexer), multiline=True,
                    key_bindings=self._key_bindings(), complete_while_typing=False,
                    prompt_continuation=lambda width, n, soft: CONTINUATION,
                    enable_history_search=True)
                n = len(self.session.signals)
                loaded = f" — {n} signal(s): {', '.join(self.session.signals)}" if n else ""
                self.console.display.info(
                    f"Python terminal of the session{loaded}. Signals are variables (S1, S2…), "
                    "results R1, R2…; / for commands, name? for help, Ctrl+C to interrupt.")
                self.ready.set()
                while not self._stopped:
                    code = self._next_pending()
                    if code is None:
                        try:
                            answer = self._prompt.prompt(PROMPT, pre_run=self._check_pending)
                        except KeyboardInterrupt:
                            continue
                        except EOFError:
                            continue
                        if answer is _PENDING:
                            continue
                        code = str(answer)
                    else:
                        self._echo(code)
                    self._execute(code)

    def _check_pending(self) -> None:
        """Code submitted while the prompt was starting: leave the prompt to run it."""
        if not self._pending.empty():
            self._prompt.app.exit(result=_PENDING)

    def _next_pending(self) -> str | None:
        try:
            return self._pending.get_nowait()
        except queue.Empty:
            return None

    def _echo(self, code: str) -> None:
        lines = code.rstrip("\n").split("\n")
        text = PROMPT + lines[0] + "".join("\n" + CONTINUATION + line for line in lines[1:])
        self._writer.write(text.replace("\n", "\r\n") + "\r\n")

    def _route_output(self) -> None:
        """(Re)install the routing of ``print``: other code may have replaced sys.stdout."""
        stdout, stderr = install_stream_routing()
        ident = threading.get_ident()
        stdout.routes[ident] = self._writer
        stderr.routes[ident] = self._writer

    def _execute(self, code: str) -> None:
        self.busy = True
        started = time.perf_counter()
        self._route_output()
        try:
            self.console.execute(code)
        except KeyboardInterrupt:  # interrupt arriving between two statements
            self.console.display.error("Interrupted")
        except BaseException as exc:  # noqa: BLE001 - the terminal thread must survive
            self.console.display.error(f"{type(exc).__name__}: {exc}")
        finally:
            self.busy = False
            log.debug("terminal command ran in %.3f s", time.perf_counter() - started)
            for callback in list(self.on_executed):
                try:
                    callback()
                except Exception:
                    log.exception("Terminal listener failed")


__all__ = ["PythonTerminal", "TerminalDisplay", "TerminalWriter", "ThreadRoutedStream",
           "install_stream_routing"]
