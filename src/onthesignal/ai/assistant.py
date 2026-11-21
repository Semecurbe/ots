"""The assistant: conversation loop with tool calls, confirmation policy, script generation."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from ..core.errors import ParameterError
from ..core.registry import commands
from .context import system_prompt
from .providers import LLMProvider, Reply, RequestCancelled, ToolCall, make_provider
from .tools import Tool, build_tools

MAX_ROUNDS = 8
CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)

SCRIPT_SYSTEM = """You write onthesignal scripts. Reply with exactly one ```python code block
containing a complete script that follows the template below: same header docstring (Name,
Description, Author, Version, Inputs), a PARAMS list of Param, a pure run(signals, **params)
function returning a Result (no display, no file output), an optional plot(result, fig)
function, and the __main__ block. Use numpy, scipy and the onthesignal API only. Code,
comments and messages in English."""


def extract_code(text: str) -> str | None:
    match = CODE_BLOCK.search(text or "")
    return match.group(1).strip() + "\n" if match else None


class Assistant:
    """AI assistant bound to a user host: the console, or the chat of the web interface.

    Parameters
    ----------
    host : object
        User host (rule R14 of the web specification): a ``session`` attribute and the
        methods ``info``, ``warning``, ``error``, ``markdown(text)``,
        ``confirm(question, details="") -> bool`` and ``run_python(code)``. The console
        implements them.
    provider : LLMProvider, optional
        Model provider (from the ``[ai]`` configuration by default).
    on_event : callable, optional
        ``on_event(event, data)`` with ``event`` in ``"delta"`` (pieces of a streamed answer:
        ``kind`` ``text`` or ``thinking``, ``text``), ``"reply"`` (``text``, ``thinking``),
        ``"usage"`` (``input`` and ``output`` tokens), ``"tool_start"``, ``"tool_end"`` and
        ``"done"`` (web chat). With it, the providers that can stream do so.
    """

    def __init__(self, host: Any, provider: LLMProvider | None = None,
                 on_event: Callable[[str, dict], None] | None = None) -> None:
        self.host = host
        self.console = host  # former name of the host, kept for compatibility
        self.session = host.session
        self.provider = provider or make_provider(self.session.config)
        self.tools: dict[str, Tool] = build_tools(self.session)
        self.transcript: list[dict] = []
        self.on_event = on_event
        self.cancelled = False

    def cancel(self) -> None:
        """Stop the current request after the model call or tool in progress."""
        self.cancelled = True

    def _emit(self, event: str, **data: Any) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event, data)
        except Exception:  # the conversation must not fail because of the display
            logging.getLogger(__name__).exception("Assistant event handler failed")

    # ------------------------------------------------------------------ conversation
    def ask(self, text: str) -> str:
        """Send a question; run the requested tools; return the final answer text."""
        self.cancelled = False
        self.transcript.append({"role": "user", "content": text})
        system = system_prompt(self.session)
        specs = [t.spec for t in self.tools.values()] if self.provider.supports_tools else []
        answer = ""
        for _ in range(MAX_ROUNDS):
            try:
                reply: Reply = self._chat(system, specs)
            except RequestCancelled:
                self.cancelled = True
            if self.cancelled:
                if self.transcript and self.transcript[-1]["role"] == "user":
                    self.transcript.pop()  # the unanswered question is withdrawn
                self.host.warning("Request stopped")
                break
            if reply.usage:
                self._emit("usage", **reply.usage)
            self.transcript.append({"role": "assistant", "content": reply.text,
                                    "tool_calls": reply.tool_calls})
            if reply.text or reply.thinking:
                answer = reply.text or answer
                if reply.text:
                    self.host.markdown(reply.text)
                self._emit("reply", text=reply.text, thinking=reply.thinking)
            if not reply.tool_calls:
                if not self.provider.supports_tools:
                    self._offer_code(reply.text)
                break
            for call in reply.tool_calls:
                if self.cancelled:
                    outcome = {"ok": False, "error": "Stopped by the user"}
                else:
                    self._emit("tool_start", call=call)
                    outcome = self.execute(call)
                    self._emit("tool_end", call=call, outcome=outcome)
                self.transcript.append({"role": "tool", "id": call.id, "name": call.name,
                                        "content": json.dumps(outcome, ensure_ascii=False,
                                                              default=str)[:20000]})
            if self.cancelled:
                self.host.warning("Request stopped")
                break
        else:
            self.host.warning("The assistant stopped after too many tool calls")
        self._emit("done", text=answer)
        return answer

    def _chat(self, system: str, specs: list) -> Reply:
        """One model call; streamed when the provider can and an event handler listens."""
        if self.on_event is None or not getattr(self.provider, "supports_streaming", False):
            return self.provider.chat(system, self.transcript, specs)

        def delta(kind: str, text: str) -> None:
            if self.cancelled:
                raise RequestCancelled
            self._emit("delta", kind=kind, text=text)

        return self.provider.chat(system, self.transcript, specs,  # type: ignore[call-arg]
                                  on_delta=delta)

    def _allowed(self, call: ToolCall, tool: Tool) -> bool:
        auto = str(self.session.config.get("ai.auto_execute", "read_only")).lower()
        if not tool.confirm and auto == "read_only":
            return True
        args = ", ".join(f"{k}={v!r}" for k, v in call.arguments.items())
        question = f"The assistant wants to run {call.name}({args}). Allow?"
        details = str(call.arguments.get("code", ""))
        try:
            return bool(self.host.confirm(question, details=details, key=call.name))
        except TypeError:  # a host without the key argument
            return bool(self.host.confirm(question, details=details))

    def execute(self, call: ToolCall) -> dict:
        """Run one tool call under the confirmation policy; errors are returned to the model."""
        tool = self.tools.get(call.name)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool {call.name}"}
        if not self._allowed(call, tool):
            return {"ok": False, "error": "The user refused this action"}
        self.session.history.append(f"ai: {call.name}({json.dumps(call.arguments, default=str)})")
        try:
            return {"ok": True, "result": tool.func(call.arguments)}
        except Exception as exc:  # reported to the model so it can correct itself
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _offer_code(self, text: str) -> None:
        """Models without tool calling propose Python code: shown, then run on consent."""
        code = extract_code(text)
        if not code:
            return
        if self.host.confirm("Run this code in the console?", details=code):
            self.session.history.append("ai: python code run")
            self.host.run_python(code)

    # ------------------------------------------------------------------ script generation
    def generate_script(self, name: str, description: str) -> Path:
        """``/ai_script``: write ``scripts/<name>.py`` from a description (checked, not run).

        A host with a ``review_handler(path, original, proposed) -> str | None`` (the diff
        view of the web interface) shows the proposal first: the script is written with the
        text accepted by the user, and not at all when the proposal is refused.
        """
        from ..scripts import TEMPLATE, check_syntax, script_path

        path = script_path(name)
        review = getattr(self.host, "review_handler", None)
        if path.exists() and review is None and \
                not self.host.confirm(f"{path} exists. Overwrite?"):
            raise ParameterError("Script generation cancelled")
        api_ref = "\n".join(f"- {c.name}: {c.description}" for c in commands())
        prompt = (f"Script name: {name}\nTask: {description}\n\nTemplate:\n```python\n"
                  f"{TEMPLATE.read_text(encoding='utf-8')}```\n\nAvailable analyses "
                  f"(onthesignal.analysis.compute_<name>(signal, **params) -> Result):\n{api_ref}")
        reply = self.provider.chat(SCRIPT_SYSTEM, [{"role": "user", "content": prompt}], [])
        code = extract_code(reply.text)
        if code is None:
            raise ParameterError("The model did not return a Python code block")
        header = (f"# Generated by AI ({self.provider.name}, {self.provider.model}, "
                  f"{date.today()}) — review before use\n")
        text = header + code
        if review is not None:
            original = path.read_text(encoding="utf-8") if path.exists() else ""
            accepted = review(path, original, text)
            if accepted is None:
                raise ParameterError(f"{path.name} was not written: the proposal was refused")
            text = str(accepted)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        error = check_syntax(path)
        if error:
            self.host.error(f"Syntax error in the generated script: {error}")
        return path


def get_assistant(host: Any, provider: LLMProvider | None = None,
                  on_event: Callable[[str, dict], None] | None = None) -> Assistant:
    return Assistant(host, provider, on_event)
