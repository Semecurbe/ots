"""AI chat panel (web specification §11): conversation, tool cards, confirmations."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from nicegui import ui

from ...ai.assistant import extract_code
from ...core.errors import ParameterError

if TYPE_CHECKING:
    from .workbench import Workbench


class ChatHost:
    """User host of the assistant for one browser tab (rule R14).

    Runs in the assistant's thread: it never touches widgets, it sends events to the tab.
    """

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.session = wb.state.session

    def _push(self, event: dict) -> None:
        self.wb.channel.push(event)

    def info(self, text: str) -> None:
        self._push({"type": "chat", "kind": "note", "level": "info", "text": text})

    def warning(self, text: str) -> None:
        self._push({"type": "chat", "kind": "note", "level": "warning", "text": text})

    def error(self, text: str) -> None:
        self._push({"type": "chat", "kind": "note", "level": "error", "text": text})

    def markdown(self, text: str) -> None:
        """Answers arrive through the ``reply`` event of the assistant."""

    def confirm(self, question: str, details: str = "") -> bool:
        if not self.wb.state.code_execution:
            self.warning(f"Refused ([web] code_execution = false): {question}")
            return False
        answer = self.wb.state.requests.ask({"type": "confirm", "question": question,
                                             "details": details}, client=self.wb.id)
        return bool(answer)

    def run_python(self, code: str) -> None:
        self.wb.state.terminal.submit(code)


class ChatPanel:
    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.assistant: Any = None
        self.busy = False
        self.cards: dict[str, dict[str, Any]] = {}
        self.results_before = 0
        self.tool_started: dict[str, float] = {}

    # ------------------------------------------------------------------ layout
    def build(self) -> None:
        with ui.column().classes("w-full h-full gap-1 q-pa-sm no-wrap"):
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                ui.label("AI CHAT").classes("text-caption text-weight-bold text-grey-8")
                self.provider_label = ui.label("").classes("text-caption text-grey-7 ellipsis grow")
                ui.button(icon="tune", on_click=self.choose_model) \
                    .props("flat dense round size=sm").tooltip("Provider and model")
                ui.button(icon="add_comment", on_click=self.new_chat) \
                    .props("flat dense round size=sm").tooltip("New chat")
            with ui.row().classes("w-full gap-1"):
                ui.button("Init", icon="travel_explore", on_click=self.init_context) \
                    .props("flat dense no-caps size=sm").tooltip("/init: summarize the signals")
                ui.button("Context", icon="description", on_click=self.edit_context) \
                    .props("flat dense no-caps size=sm").tooltip("Edit context.md")
            self.scroll = ui.scroll_area().classes("w-full grow border rounded-borders")
            with self.scroll:
                self.log = ui.column().classes("w-full gap-2 q-pa-xs")
            self.status = ui.label("").classes("text-caption text-grey-7")
            self.input = ui.textarea(placeholder="Ask the assistant… (/ for commands, Enter to "
                                     "send, Shift+Enter for a new line)") \
                .props("dense outlined autogrow").classes("w-full")
            self.input.on("keydown.enter", self._enter,
                          js_handler="(e) => { if (!e.shiftKey) { e.preventDefault(); emit(); } }")
            with ui.row().classes("w-full justify-end gap-1"):
                self.stop_button = ui.button("Stop", icon="stop", on_click=self.stop) \
                    .props("flat dense no-caps")
                self.stop_button.set_visibility(False)
                ui.button("Send", icon="send", on_click=self.send).props("unelevated dense no-caps")
        self.update_provider()
        self._note("info", "The assistant drives onthesignal: it runs analyses, reads results and "
                   "proposes code. It receives summaries, never the samples.")

    def update_provider(self) -> None:
        from ...ai.context import provider_label

        self.provider_label.text = provider_label(self.wb.state.config)

    # ------------------------------------------------------------------ messages
    def _bubble(self, text: str, mine: bool) -> None:
        with self.log:
            classes = "self-end bg-blue-1" if mine else "bg-grey-1"
            with ui.card().props("flat").classes(f"q-pa-sm {classes} max-w-full"):
                if mine:
                    ui.label(text).classes("text-body2 whitespace-pre-wrap")
                else:
                    ui.markdown(text).classes("text-body2")
                    code = extract_code(text)
                    if code:
                        with ui.row().classes("gap-1"):
                            ui.button("Copy", icon="content_copy",
                                      on_click=lambda c=code: ui.clipboard.write(c)) \
                                .props("flat dense no-caps size=sm")
                            ui.button("Open in editor", icon="edit",
                                      on_click=lambda c=code: self.wb.open_code(c)) \
                                .props("flat dense no-caps size=sm")
                            if self.wb.state.code_execution:
                                ui.button("Run in terminal", icon="play_arrow",
                                          on_click=lambda c=code: self.run_code(c)) \
                                    .props("flat dense no-caps size=sm")
        self.scroll.scroll_to(percent=1.0)

    def _note(self, level: str, text: str) -> None:
        color = {"warning": "text-amber-10", "error": "text-negative"}.get(level, "text-grey-7")
        with self.log:
            ui.label(text).classes(f"text-caption {color}")
        self.scroll.scroll_to(percent=1.0)

    def attach(self, text: str) -> None:
        """Insert a mention (``@S1``) or a question in the input field."""
        self.wb.show_chat()
        self.input.value = (self.input.value + " " if self.input.value else "") + text
        self.input.run_method("focus")

    async def run_code(self, code: str) -> None:
        from .dialogs import confirm

        if await confirm("Run this code in the Python terminal?", code[:600], "Run"):
            self.wb.state.terminal.submit(code)
            self.wb.show_terminal()

    # ------------------------------------------------------------------ sending
    async def _enter(self) -> None:
        await self.send()

    async def send(self) -> None:
        text = (self.input.value or "").strip()
        if not text:
            return
        if self.busy:
            ui.notify("The assistant is still answering (Stop to interrupt)", type="warning")
            return
        self.input.value = ""
        if text.startswith("/") and not self.wb.state.code_execution:
            self._note("warning", "Commands run in the Python terminal, disabled by "
                       "[web] code_execution = false")
            return
        if text.startswith("/"):
            self._bubble(text, True)
            self._note("info", "Command run in the Python terminal")
            self.wb.state.terminal.submit(text)
            self.wb.show_terminal()
            return
        await self.ask(text)

    async def consent(self) -> bool:
        """Ask once per online provider before sending it the first summaries (§11.5)."""
        from ...ai.providers import local_provider

        cfg = self.wb.state.config
        provider = str(cfg.get("ai.provider", "ollama")).lower()
        if local_provider(provider, str(cfg.get("ai.base_url", "") or "")) or \
                provider in self.wb.state.ai_consent:
            return True
        from .dialogs import confirm

        agreed = await confirm(
            f"Send the session summaries to {provider}?",
            "The assistant sends to this online provider the metadata of the signals, the "
            "results of the analyses and your questions — never the samples "
            "([ai] send_raw_data is false). Ollama keeps everything on your network.",
            "Agree and send")
        if agreed:
            self.wb.state.ai_consent.add(provider)
            self.wb.state.log("ai", f"consent given for {provider}")
        return agreed

    async def ask(self, text: str) -> None:
        from ...ai import get_assistant

        if not await self.consent():
            self._note("warning", "Not sent: no consent for the online provider")
            return
        self._bubble(text, True)
        if self.assistant is None:
            try:
                self.assistant = get_assistant(ChatHost(self.wb), on_event=self._on_event)
            except (ParameterError, Exception) as exc:  # missing package, key, model
                self._note("error", f"The assistant is not available: {exc}")
                return
        self.busy = True
        self.started = time.time()
        self.stop_button.set_visibility(True)
        assistant = self.assistant

        def work(job: Any) -> Any:
            return assistant.ask(text)

        def done(job: Any) -> None:
            self.wb.channel.push({"type": "chat", "kind": "done", "state": job.state,
                                  "error": job.error})

        self.wb.state.jobs.start("AI request", work, kind="ai", client=self.wb.id, on_done=done,
                                 cancel=assistant.cancel)

    def _on_event(self, event: str, data: dict) -> None:
        """Assistant thread: turn its events into chat events of this browser tab."""
        payload: dict[str, Any] = {"type": "chat", "kind": event}
        if event == "reply":
            payload["text"] = data.get("text", "")
        elif event in ("tool_start", "tool_end"):
            call = data["call"]
            payload.update(id=call.id, name=call.name,
                           arguments=json.dumps(call.arguments, default=str, ensure_ascii=False))
            if event == "tool_start":
                self.results_before = len(self.wb.state.session.results)
                self.tool_started[call.id] = time.time()
                self.wb.state.log("ai", f"{call.name}({payload['arguments'][:200]})")
            else:
                payload["duration"] = time.time() - self.tool_started.pop(call.id, time.time())
                outcome = data.get("outcome") or {}
                payload["ok"] = bool(outcome.get("ok"))
                payload["error"] = outcome.get("error", "")
                new = self.wb.state.session.results[self.results_before:]
                payload["results"] = [r.name for r in new]
                summary = outcome.get("result")
                if isinstance(summary, dict) and "values" in summary:
                    items = list(summary["values"].items())[:3]
                    payload["summary"] = " · ".join(f"{k} {v}" for k, v in items)
        self.wb.channel.push(payload)

    def stop(self) -> None:
        if self.assistant is not None:
            self.assistant.cancel()
        self._note("warning", "Stopping after the current step…")

    def new_chat(self) -> None:
        if self.busy:
            ui.notify("Stop the current request first", type="warning")
            return
        self.assistant = None
        self.log.clear()
        self.cards.clear()
        self._note("info", "New chat")

    # ------------------------------------------------------------------ events (UI thread)
    def handle(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "reply":
            self._bubble(event.get("text", ""), False)
        elif kind == "note":
            self._note(event.get("level", "info"), event.get("text", ""))
        elif kind == "tool_start":
            with self.log:
                card = ui.card().props("flat bordered").classes("q-pa-xs w-full")
                with card:
                    with ui.row().classes("items-center no-wrap gap-1"):
                        spinner = ui.spinner(size="sm")
                        ui.label(f"{event['name']}({event['arguments'][:120]})") \
                            .classes("text-caption text-weight-medium")
                    body = ui.column().classes("gap-0")
            self.cards[event["id"]] = {"card": card, "spinner": spinner, "body": body}
        elif kind == "tool_end":
            item = self.cards.get(event["id"])
            if item is None:
                return
            item["spinner"].delete()
            with item["body"]:
                duration = float(event.get("duration", 0.0))
                if event.get("ok"):
                    ui.label(f"done in {duration:.1f} s" + (f" · {event['summary']}"
                                                          if event.get("summary") else "")) \
                        .classes("text-caption text-grey-8")
                else:
                    ui.label(f"{event.get('error', 'failed')}") \
                        .classes("text-caption text-negative")
                for name in event.get("results", []):
                    ui.button(f"Open {name}", icon="open_in_new",
                              on_click=lambda n=name: self.wb.open_result(n)) \
                        .props("flat dense no-caps size=sm")
        elif kind == "done":
            self.busy = False
            self.stop_button.set_visibility(False)
            self.status.text = ""
            if event.get("state") == "failed":
                self._note("error", event.get("error") or "The request failed")
        self.scroll.scroll_to(percent=1.0)

    def confirm_card(self, event: dict) -> None:
        """Allow / Deny card of an action that needs the user's consent (§11.3)."""
        request = event["request"]
        self.wb.show_chat()
        with self.log:
            with ui.card().props("flat bordered").classes("q-pa-sm w-full bg-amber-1") as card:
                ui.label(event.get("question", "")).classes("text-body2 text-weight-medium")
                if event.get("details"):
                    ui.code(event["details"][:4000]).classes("w-full text-xs")
                with ui.row().classes("gap-1"):
                    def answer(value: bool, card: Any = card) -> None:
                        self.wb.state.requests.answer(request, value)
                        card.clear()
                        with card:
                            ui.label(("Allowed: " if value else "Denied: ")
                                     + event.get("question", "")).classes("text-caption")

                    ui.button("Allow", icon="check", on_click=lambda: answer(True)) \
                        .props("unelevated dense no-caps")
                    ui.button("Deny", icon="block", on_click=lambda: answer(False)) \
                        .props("flat dense no-caps")
        self.scroll.scroll_to(percent=1.0)

    def tick(self) -> None:
        if self.busy:
            self.status.text = f"Waiting for the model… {time.time() - self.started:.0f} s"

    # ------------------------------------------------------------------ tools
    def init_context(self) -> None:
        """``/init``: summarize every signal of the session for the assistant."""
        from ...ai.context import init_context

        def work(job: Any) -> Any:
            return init_context(self.wb.state.session)

        def done(job: Any) -> None:
            if job.state == "done":
                self.wb.channel.push({"type": "chat", "kind": "note", "level": "info",
                                      "text": f"AI context written to {job.result}"})
            self.wb.report_failure(job)

        self.wb.state.jobs.start("/init", work, kind="ai", client=self.wb.id, on_done=done)
        self._note("info", "Summarizing the signals for the assistant (/init)…")

    def edit_context(self) -> None:
        path = self.wb.root / "context.md"
        if not path.exists():
            path.write_text("# Context for the AI assistant\n\nBench, digitizer settings, "
                            "sensor, expected performance…\n", encoding="utf-8")
        self.wb.open_file(path)

    async def choose_model(self) -> None:
        cfg = self.wb.state.config
        with ui.dialog() as dialog, ui.card().classes("w-[460px]"):
            ui.label("AI provider for this session").classes("text-subtitle1")
            provider = ui.select(["ollama", "anthropic", "openai"],
                                 value=cfg.get("ai.provider", "ollama"), label="Provider") \
                .props("dense outlined").classes("w-full")
            model = ui.input("Model", value=cfg.get("ai.model", "")).props("dense outlined") \
                .classes("w-full")
            base = ui.input("Server URL (Ollama, vLLM)", value=cfg.get("ai.base_url", "")) \
                .props("dense outlined").classes("w-full")
            context = ui.number("Context (tokens, Ollama; 0 = server default)",
                                value=int(cfg.get("ai.context", 0) or 0)) \
                .props("dense outlined").classes("w-full")
            ui.label("API keys are read from the environment of the server only.") \
                .classes("text-caption text-grey-7")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Apply", on_click=lambda: dialog.submit(True)).props("unelevated")
        dialog.open()
        if await dialog:
            cfg.set("ai.provider", provider.value)
            cfg.set("ai.model", model.value or "")
            cfg.set("ai.base_url", base.value or "")
            cfg.set("ai.context", int(context.value or 0))
            self.assistant = None
            self.update_provider()
            self._note("info", f"Provider set to {provider.value} for this session")
        dialog.delete()


__all__ = ["ChatHost", "ChatPanel"]
