"""Auto-completion: the ``/`` command menu, signal names, parameters, files, scripts."""

from __future__ import annotations

import builtins
from collections.abc import Iterable
from typing import TYPE_CHECKING

from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document

from ..core.errors import ParameterError
from ..core.registry import get_command
from ..core.signal import Signal
from . import commands

if TYPE_CHECKING:
    from .console import OnTheSignalConsole


def fuzzy_match(word: str, candidate: str) -> bool:
    """True when the letters of ``word`` appear in order in ``candidate``."""
    it = iter(candidate.lower())
    return all(ch in it for ch in word.lower())


class ConsoleCompleter(Completer):
    def __init__(self, console: OnTheSignalConsole) -> None:
        self.console = console
        self.paths = PathCompleter(expanduser=True)

    def get_completions(self, document: Document, complete_event: object) -> Iterable[Completion]:
        text = document.text_before_cursor
        if text.startswith("/"):
            if " " not in text:
                yield from self._commands(text[1:])
            else:
                yield from self._arguments(text, document, complete_event)
            return
        yield from self._python(document)

    def _commands(self, word: str) -> Iterable[Completion]:
        items = commands.command_list()
        exact = [i for i in items if i[0].startswith(word)]
        fuzzy = [i for i in items if i not in exact and fuzzy_match(word, i[0])]
        for name, desc in exact + fuzzy:
            yield Completion(name, start_position=-len(word), display=f"/{name}",
                             display_meta=desc)

    def _arguments(self, text: str, document: Document, event: object) -> Iterable[Completion]:
        name = commands.ALIASES.get(text[1:].split()[0], text[1:].split()[0])
        word = document.get_word_before_cursor(WORD=True)
        kind = commands.SLASH[name].complete if name in commands.SLASH else "signal"
        if kind == "file" and (not text.rstrip().endswith(name) or word):
            sub = Document(word, len(word))
            yield from self.paths.get_completions(sub, event)  # type: ignore[arg-type]
        if kind == "command":
            yield from self._commands(word)
            return
        if kind == "script":
            from ..scripts import list_scripts

            for script, desc in list_scripts():
                if script.startswith(word):
                    yield Completion(script, start_position=-len(word), display_meta=desc)
        for sig in self.console.session.signals:
            if sig.startswith(word):
                yield Completion(sig, start_position=-len(word), display_meta="signal")
        try:
            cmd = get_command(name)
        except ParameterError:
            return
        for p in cmd.params:
            if p.name.startswith(word) and p.name not in cmd.signal_params:
                yield Completion(f"{p.name}=", start_position=-len(word),
                                 display_meta=f"default {p.describe_default()}")

    def _python(self, document: Document) -> Iterable[Completion]:
        word = document.get_word_before_cursor()
        if not word or not word.isidentifier():
            return
        names = set(self.console.ns) | set(dir(builtins))
        for name in sorted(n for n in names if n.startswith(word) and not n.startswith("_")):
            value = self.console.ns.get(name)
            meta = "signal" if isinstance(value, Signal) else (
                "function" if callable(value) else "")
            yield Completion(name, start_position=-len(word), display_meta=meta)
