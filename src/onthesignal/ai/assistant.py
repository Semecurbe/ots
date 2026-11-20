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
from .providers import LLMProvider, Reply, ToolCall, make_provider
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
        ``on_event(event, data)`` with ``event`` in ``"reply"``, ``"tool_start"``,
        ``"tool_end"`` and ``"done"`` (tool-call cards of the web chat).
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
            reply: Reply = self.provider.chat(system, self.transcript, specs)
            if self.cancelled:
                self.transcript.pop()  # the unanswered question is withdrawn
                self.host.warning("Request stopped")
                break
            self.transcript.append({"role": "assistant", "content": reply.text,
                                    "tool_calls": reply.tool_calls})
            if reply.text:
                answer = reply.text
                self.host.markdown(reply.text)
                self._emit("reply", text=reply.text)
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

    def _allowed(self, call: ToolCall, tool: Tool) -> bool:
        auto = str(self.session.config.get("ai.auto_execute", "read_only")).lower()
        if not tool.confirm and auto == "read_only":
            return True
        args = ", ".join(f"{k}={v!r}" for k, v in call.arguments.items())
        return bool(self.host.confirm(f"The assistant wants to run {call.name}({args}). Allow?",
                                      details=str(call.arguments.get("code", ""))))

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
        """``/ai_script``: write ``scripts/<name>.py`` from a description (checked, not run)."""
        from ..scripts import TEMPLATE, check_syntax, script_path

        path = script_path(name)
        if path.exists() and not self.host.confirm(f"{path} exists. Overwrite?"):
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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header + code, encoding="utf-8")
        error = check_syntax(path)
        if error:
            self.host.error(f"Syntax error in the generated script: {error}")
        return path


def get_assistant(host: Any, provider: LLMProvider | None = None,
                  on_event: Callable[[str, dict], None] | None = None) -> Assistant:
    return Assistant(host, provider, on_event)
