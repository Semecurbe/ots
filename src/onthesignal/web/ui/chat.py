"""AI chat panel (web specification §11): conversation, tool cards, confirmations.

The answer appears as it is generated (with the reasoning of the model in a folded block)
and its LaTeX formulas are drawn; the tokens used are shown against the context size,
profiles of ``[[ai.profiles]]`` are chosen in the header, ``@S1``, ``@R2`` or ``@context.md``
attach summaries of objects or the text of a file, the last question can be edited or asked
again, code proposed about a file of the editor is reviewed in a diff view, and the
conversations are saved in ``.onthesignal/chats/`` to be reopened or exported in Markdown.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nicegui import ui

from ...ai.assistant import extract_code
from ...core.errors import ParameterError
from ..mathtext import ChatMarkdown

if TYPE_CHECKING:
    from .workbench import Workbench

MENTION = re.compile(r"(?<![\w.])@([\w./-]+)")
#: Largest file attached to a message (characters).
FILE_LIMIT = 20_000


def _tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


class ChatHost:
    """User host of the assistant for one browser tab (rule R14).

    Runs in the assistant's thread: it never touches widgets, it sends events to the tab.
    ``allowed`` holds the tools the user allowed for the whole chat.
    """

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.session = wb.state.session
        self.allowed: set[str] = set()

    def _push(self, event: dict) -> None:
        self.wb.channel.push(event)

    def info(self, text: str) -> None:
        self._push({"type": "chat", "kind": "note", "level": "info", "text": text})

    def warning(self, text: str) -> None:
        self._push({"type": "chat", "kind": "note", "level": "warning", "text": text})

    def error(self, text: str) -> None:
        self._push({"type": "chat", "kind": "note", "level": "error", "text": text})

    def markdown(self, text: str) -> None:
        """Answers arrive through the ``delta`` and ``reply`` events of the assistant."""

    def confirm(self, question: str, details: str = "", key: str | None = None) -> bool:
        if not self.wb.state.code_execution:
            self.warning(f"Refused ([web] code_execution = false): {question}")
            return False
        if key is not None and key in self.allowed:
            self.info(f"Allowed for this chat: {question}")
            return True
        answer = self.wb.state.requests.ask({"type": "confirm", "question": question,
                                             "details": details, "key": key},
                                            client=self.wb.id)
        if answer == "chat" and key is not None:
            self.allowed.add(key)
        return bool(answer)

    def run_python(self, code: str) -> None:
        self.wb.state.terminal.submit(code)


# ---------------------------------------------------------------------------------- history
def chats_dir(state: Any) -> Path:
    return Path(state.project) / str(state.config.get("paths.state", ".onthesignal")) / "chats"


def _transcript_to_json(transcript: list[dict]) -> list[dict]:
    out = []
    for entry in transcript:
        entry = dict(entry)
        if entry.get("tool_calls"):
            entry["tool_calls"] = [{"id": c.id, "name": c.name, "arguments": c.arguments}
                                   for c in entry["tool_calls"]]
        out.append(entry)
    return out


def _transcript_from_json(entries: list[dict]) -> list[dict]:
    from ...ai.providers import ToolCall

    out = []
    for entry in entries:
        entry = dict(entry)
        if entry.get("tool_calls"):
            entry["tool_calls"] = [ToolCall(c["id"], c["name"], c.get("arguments", {}))
                                   for c in entry["tool_calls"]]
        out.append(entry)
    return out


def chat_markdown(record: dict) -> str:
    """A saved conversation as Markdown (export)."""
    lines = [f"# {record.get('title') or 'Chat'}", "",
             f"{record.get('created', '')} · {record.get('provider', '')}", ""]
    for item in record.get("items", []):
        kind = item.get("kind")
        if kind == "user":
            lines += [f"**You:** {item.get('text', '')}", ""]
        elif kind == "assistant":
            lines += ["**Assistant:**", "", item.get("text", ""), ""]
        elif kind == "tool":
            state = "done" if item.get("ok") else f"failed: {item.get('error', '')}"
            summary = f" · {item['summary']}" if item.get("summary") else ""
            lines += [f"> `{item.get('name')}({item.get('arguments', '')})` — {state}{summary}",
                      ""]
        elif kind == "note":
            lines += [f"_{item.get('text', '')}_", ""]
    return "\n".join(lines)


class ChatPanel:
    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.assistant: Any = None
        self.busy = False
        self.cards: dict[str, dict[str, Any]] = {}
        self.results_before = 0
        self.tool_started: dict[str, float] = {}
        self.stream: dict[str, Any] | None = None
        self.record = self._new_record()
        #: File and code of the last "Ask AI" of the editor: code of the answers can be
        #: reviewed against this file (§9.6).
        self.code_target: dict[str, Any] | None = None
        #: The last question is being edited: sending replaces it (§11.2).
        self.editing = False

    # ------------------------------------------------------------------ layout
    def build(self) -> None:
        from ...ai.providers import profiles

        with ui.column().classes("w-full h-full gap-1 q-pa-sm no-wrap"):
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                ui.label("AI CHAT").classes("text-caption text-weight-bold text-grey-8 "
                                            "no-wrap")
                self.provider_label = ui.label("").classes("text-caption text-grey-7 "
                                                           "ots-ellipsis grow min-w-0")
                ui.button(icon="tune", on_click=self.choose_model) \
                    .props("flat dense round size=sm").tooltip("Provider and model")
                ui.button(icon="history", on_click=self.history) \
                    .props("flat dense round size=sm").tooltip("Saved conversations")
                ui.button(icon="add_comment", on_click=self.new_chat) \
                    .props("flat dense round size=sm").tooltip("New chat")
            names = {p["name"]: p["name"] for p in profiles(self.wb.state.config)}
            self.profile = ui.select({"": "[ai] settings", **names}, label="Profile",
                                     value=str(self.wb.state.config.get("ai.profile", "") or ""),
                                     on_change=lambda e: self.use_profile(e.value)) \
                .props("dense outlined options-dense").classes("w-full") \
                .tooltip("AI profile ([[ai.profiles]] of the configuration)")
            self.profile.set_visibility(bool(names))
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                ui.button("Init", icon="travel_explore", on_click=self.init_context) \
                    .props("flat dense no-caps size=sm").tooltip("/init: summarize the signals")
                ui.button("Context", icon="description", on_click=self.edit_context) \
                    .props("flat dense no-caps size=sm").tooltip("Edit context.md")
                ui.space()
                with ui.label("").classes("text-caption ellipsis") as self.availability:
                    self.availability_tip = ui.tooltip("")
                self.context_label = ui.label("").classes("text-caption text-grey-7") \
                    .tooltip("Tokens of the last request / context size of the model")
            self.scroll = ui.scroll_area().classes("w-full grow border rounded-borders")
            with self.scroll:
                self.log = ui.column().classes("w-full gap-2 q-pa-xs")
            self.status = ui.label("").classes("text-caption text-grey-7")
            with ui.row().classes("w-full items-center no-wrap gap-1 q-px-xs bg-blue-1 "
                                  "rounded-borders") as self.edit_banner:
                ui.icon("edit", size="16px", color="primary")
                ui.label("Editing the last question: Send replaces it and its answer") \
                    .classes("text-caption grow")
                ui.button(icon="close", on_click=self.cancel_edit) \
                    .props("flat dense round size=xs").tooltip("Cancel the edit")
            self.edit_banner.set_visibility(False)
            self.suggestions = ui.row().classes("w-full gap-1")
            self.input = ui.textarea(placeholder="Ask the assistant… (@ attaches a signal, a "
                                     "result or a file; / for commands; Enter to send, "
                                     "Shift+Enter for a new line)") \
                .props("dense outlined autogrow").classes("w-full")
            self.input.on("keydown.enter", self._enter,
                          js_handler="(e) => { if (!e.shiftKey) { e.preventDefault(); emit(); } }")
            self.input.on_value_change(lambda e: self._suggest(e.value or ""))
            with ui.row().classes("w-full justify-end gap-1"):
                self.stop_button = ui.button("Stop", icon="stop", on_click=self.stop) \
                    .props("flat dense no-caps")
                self.stop_button.set_visibility(False)
                ui.button(icon="edit_note", on_click=self.edit_last) \
                    .props("flat dense round size=sm").tooltip("Edit the last question")
                ui.button(icon="replay", on_click=self.regenerate) \
                    .props("flat dense round size=sm").tooltip("Regenerate the last answer")
                ui.button("Send", icon="send", on_click=self.send).props("unelevated dense no-caps")
        self.update_provider()
        self._note("info", "The assistant drives onthesignal: it runs analyses, reads results and "
                   "proposes code. It receives summaries, never the samples.", record=False)

    def update_provider(self) -> None:
        from ...ai.context import provider_label

        self.provider_label.text = provider_label(self.wb.state.config)
        self.check_availability()

    def check_availability(self) -> None:
        """Server reachable and model present (Ollama), API key in the environment (§11.5)."""
        import threading

        from ...ai.providers import check_availability

        config, channel = self.wb.state.config, self.wb.channel

        def work() -> None:  # a few seconds at most; not worth a job of the Jobs panel
            try:
                ok, message = check_availability(config)
            except Exception as exc:  # never break the chat for a check
                ok, message = False, str(exc)
            channel.push({"type": "chat", "kind": "availability", "ok": ok, "text": message})

        threading.Thread(target=work, name="ots-ai-check", daemon=True).start()

    def use_profile(self, name: str | None) -> None:
        from ...ai.providers import use_profile

        try:
            use_profile(self.wb.state.config, name or "")
        except ParameterError as exc:
            ui.notify(str(exc), type="warning")
            return
        self.assistant = None
        self.update_provider()
        self._note("info", f"Profile: {name}" if name else "Profile: the [ai] settings")

    # ------------------------------------------------------------------ messages
    def _code_buttons(self, text: str) -> None:
        code = extract_code(text)
        if not code:
            return
        with ui.row().classes("gap-1"):
            ui.button("Copy", icon="content_copy", on_click=lambda c=code: ui.clipboard.write(c)) \
                .props("flat dense no-caps size=sm")
            ui.button("Open in editor", icon="edit", on_click=lambda c=code: self.wb.open_code(c)) \
                .props("flat dense no-caps size=sm")
            if self.wb.state.code_execution:
                ui.button("Run in terminal", icon="play_arrow",
                          on_click=lambda c=code: self.run_code(c)) \
                    .props("flat dense no-caps size=sm")
            target = self.code_target
            if target is not None:
                ui.button(f"Review in {target['path'].name}", icon="difference",
                          on_click=lambda c=code, t=target: self.review_in_editor(c, t)) \
                    .props("flat dense no-caps size=sm") \
                    .tooltip("Compare with the code you asked about, then accept or reject")

    async def review_in_editor(self, code: str, target: dict[str, Any]) -> None:
        """Diff view of the file asked about, its selection replaced by the proposed code."""
        from .tabs import EditorTab

        path: Path = target["path"]
        key = f"file:{path}"
        tab = self.wb.work.content(key)
        if isinstance(tab, EditorTab):
            current = await tab.editor.get_value()
        else:
            current = path.read_text(encoding="utf-8", errors="replace") if path.exists() \
                else None
        selection = str(target.get("selection") or "")
        if current is None or not selection.strip() or selection not in str(current):
            ui.notify(f"The code you asked about is no longer in {path.name}: copy the "
                      "proposal instead", type="warning")
            return
        current = str(current)
        replacement = code.rstrip("\n") + ("\n" if selection.endswith("\n") else "")
        proposed = current.replace(selection, replacement, 1)

        def accept(text: str) -> None:
            editor = self.wb.work.content(key)
            if isinstance(editor, EditorTab):
                editor.apply_text(text)
                self.wb.work.open(key, path.name, lambda: editor)  # show it
            else:  # closed meanwhile: opened again with the accepted text, not saved
                self.wb.open_file(path, text=text)
            ui.notify(f"Change applied to {path.name}: save it (Ctrl+S) to keep it")

        self.wb.review_changes(path, current, proposed, accept, key=f"review:{key}")

    def _bubble(self, text: str, mine: bool, thinking: str = "",
                attachments: list[str] | None = None) -> None:
        with self.log:
            classes = "self-end bg-blue-1" if mine else "bg-grey-1"
            with ui.card().props("flat").classes(f"q-pa-sm {classes} max-w-full"):
                if mine:
                    ui.label(text).classes("text-body2 whitespace-pre-wrap")
                    if attachments:
                        with ui.row().classes("gap-1"):
                            for name in attachments:
                                ui.chip(name, icon="attach_file").props("dense outline")
                else:
                    if thinking:
                        with ui.expansion("Reasoning", icon="psychology") \
                                .props("dense").classes("w-full text-grey-8"):
                            ChatMarkdown(thinking).classes("text-caption")
                    ChatMarkdown(text).classes("text-body2")
                    self._code_buttons(text)
        self.scroll.scroll_to(percent=1.0)

    def _note(self, level: str, text: str, record: bool = True) -> None:
        color = {"warning": "text-amber-10", "error": "text-negative"}.get(level, "text-grey-7")
        with self.log:
            ui.label(text).classes(f"text-caption {color}")
        if record:
            self.record["items"].append({"kind": "note", "level": level, "text": text})
        self.scroll.scroll_to(percent=1.0)

    def attach(self, text: str, target: dict[str, Any] | None = None) -> None:
        """Insert a mention (``@S1``) or a question in the input field.

        ``target`` (``path`` and ``selection``): the code asked about, against which the code
        of the answers can be reviewed.
        """
        if target is not None:
            self.code_target = target
        self.wb.show_chat()
        self.input.value = (self.input.value + " " if self.input.value else "") + text
        self.input.run_method("focus")

    async def run_code(self, code: str) -> None:
        from .dialogs import confirm

        if await confirm("Run this code in the Python terminal?", code[:600], "Run"):
            self.wb.state.terminal.submit(code)
            self.wb.show_terminal()

    # ------------------------------------------------------------------ mentions
    def _candidates(self) -> list[str]:
        session = self.wb.state.session
        names = list(session.signals) + [r.name for r in session.results if r.name]
        for path in sorted(self.wb.root.glob("*")):
            if path.is_file() and path.suffix in {".md", ".qmd", ".toml", ".py", ".txt", ".csv"}:
                names.append(path.name)
        scripts = self.wb.root / "scripts"
        if scripts.is_dir():
            names += [f"scripts/{p.name}" for p in sorted(scripts.glob("*.py"))]
        return names

    def _suggest(self, text: str) -> None:
        """Completion of a mention being typed (``@S`` → S1, S2…)."""
        self.suggestions.clear()
        match = re.search(r"(?:^|\s)@([\w./-]*)$", text)
        if not match:
            return
        typed = match.group(1).lower()
        found = [n for n in self._candidates() if n.lower().startswith(typed)][:12]
        with self.suggestions:
            for name in found:
                ui.chip(name, icon="alternate_email",
                        on_click=lambda n=name, t=typed: self._complete(n, t)) \
                    .props("dense clickable outline")

    def _complete(self, name: str, typed: str) -> None:
        text = self.input.value or ""
        self.input.value = text[: len(text) - len(typed)] + name + " "
        self.suggestions.clear()
        # Back to the field, the cursor at the end, so that typing goes on after the mention.
        ui.run_javascript(
            f"setTimeout(() => {{ const el = getHtmlElement({self.input.id})"
            ".querySelector('textarea'); el.focus(); "
            "el.setSelectionRange(el.value.length, el.value.length); }, 50)")

    def attachments(self, text: str) -> tuple[list[str], str]:
        """Objects mentioned in ``text`` and the block of their summaries (§11.2, §11.4).

        Signals and results are attached as summaries, never as samples; text files of the
        project as their text (limited size).
        """
        from ...ai.context import describe_signal
        from ..security import confine

        session = self.wb.state.session
        names, blocks = [], []
        for name in dict.fromkeys(MENTION.findall(text)):
            if name in session.signals:
                blocks.append("\n".join(describe_signal(session.signals[name])))
            elif any(r.name == name for r in session.results):
                result = session.get_result(name)
                blocks.append(f"### Result {name}\n```\n{result.to_text()}\n```")
            else:
                try:
                    path = confine(self.wb.root / name, self.wb.roots)
                except PermissionError:
                    continue
                if not path.is_file():
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                cut = "\n[… cut]" if len(content) > FILE_LIMIT else ""
                blocks.append(f"### File {name}\n```\n{content[:FILE_LIMIT]}{cut}\n```")
            names.append(name)
        if not blocks:
            return [], ""
        return names, "\n\nAttached by the user (summaries, no samples):\n\n" + \
            "\n\n".join(blocks)

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
        self.suggestions.clear()
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
        if self.editing:
            self._withdraw_last()
            self.cancel_edit()
            self._note("info", "Edited question: new answer")
        await self.ask(text)

    def _withdraw_last(self) -> None:
        """Remove the last question and its answer from what the assistant remembers."""
        if self.assistant is None:
            return
        transcript = self.assistant.transcript
        start = max((k for k, e in enumerate(transcript) if e.get("role") == "user"),
                    default=len(transcript))
        del transcript[start:]

    def edit_last(self) -> None:
        """Put the last question back in the input field; sending it replaces the exchange."""
        if self.busy:
            ui.notify("The assistant is still answering", type="warning")
            return
        last = next((i for i in reversed(self.record["items"]) if i.get("kind") == "user"),
                    None)
        if last is None:
            ui.notify("No question to edit", type="warning")
            return
        self.editing = True
        self.edit_banner.set_visibility(True)
        self.input.value = str(last.get("text", ""))
        self.input.run_method("focus")

    def cancel_edit(self) -> None:
        self.editing = False
        self.edit_banner.set_visibility(False)

    async def consent(self) -> bool:
        """Ask once per online profile (or provider) before sending it summaries (§11.5)."""
        from ...ai.providers import ai_settings, consent_key, local_provider

        cfg = self.wb.state.config
        settings = ai_settings(cfg)
        provider, key = settings["provider"], consent_key(cfg)
        if local_provider(provider, settings["base_url"]) or key in self.wb.state.ai_consent:
            return True
        from .dialogs import confirm

        agreed = await confirm(
            f"Send the session summaries to {provider}?",
            "The assistant sends to this online provider the metadata of the signals, the "
            "results of the analyses and your questions — never the samples "
            "([ai] send_raw_data is false). Ollama keeps everything on your network.",
            "Agree and send")
        if agreed:
            self.wb.state.ai_consent.add(key)
            self.wb.state.log("ai", f"consent given for {key}")
        return agreed

    async def ask(self, text: str) -> None:
        from ...ai import get_assistant

        if not await self.consent():
            self._note("warning", "Not sent: no consent for the online provider")
            return
        names, block = self.attachments(text)
        self._bubble(text, True, attachments=names)
        self.record["items"].append({"kind": "user", "text": text, "attachments": names})
        if not self.record["title"]:
            self.record["title"] = text[:80]
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
        question = text + block

        def work(job: Any) -> Any:
            return assistant.ask(question)

        def done(job: Any) -> None:
            self.wb.channel.push({"type": "chat", "kind": "done", "state": job.state,
                                  "error": job.error})

        self.wb.state.jobs.start("AI request", work, kind="ai", client=self.wb.id, on_done=done,
                                 cancel=assistant.cancel)

    def _on_event(self, event: str, data: dict) -> None:
        """Assistant thread: turn its events into chat events of this browser tab."""
        payload: dict[str, Any] = {"type": "chat", "kind": event}
        if event == "delta":
            payload.update(part=data.get("kind", "text"), text=data.get("text", ""))
        elif event == "reply":
            payload.update(text=data.get("text", ""), thinking=data.get("thinking", ""))
        elif event == "usage":
            payload.update(input=data.get("input", 0), output=data.get("output", 0))
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
        self._note("warning", "Stopping…")

    async def regenerate(self) -> None:
        """Ask the last question again: the last exchange is withdrawn from the assistant."""
        if self.busy:
            ui.notify("The assistant is still answering", type="warning")
            return
        last = next((i for i in reversed(self.record["items"]) if i.get("kind") == "user"),
                    None)
        if last is None or self.assistant is None:
            ui.notify("No question to ask again", type="warning")
            return
        self._withdraw_last()
        self._note("info", "New answer to the last question")
        await self.ask(str(last.get("text", "")))

    # ------------------------------------------------------------------ conversations
    @staticmethod
    def _new_record() -> dict:
        now = datetime.now()
        return {"id": now.strftime("%Y%m%d_%H%M%S_%f"), "title": "",
                "created": now.isoformat(timespec="seconds"), "provider": "", "items": [],
                "transcript": []}

    def new_chat(self) -> None:
        if self.busy:
            ui.notify("Stop the current request first", type="warning")
            return
        self.assistant = None
        self.stream = None
        self.log.clear()
        self.cards.clear()
        self.record = self._new_record()
        self.code_target = None
        self.cancel_edit()
        self.context_label.text = ""
        self._note("info", "New chat", record=False)

    def save(self) -> None:
        """Write the conversation to ``.onthesignal/chats/<id>.json``."""
        from ...ai.context import provider_label

        if not self.record["items"]:
            return
        self.record["provider"] = provider_label(self.wb.state.config)
        self.record["updated"] = datetime.now().isoformat(timespec="seconds")
        if self.assistant is not None:
            self.record["transcript"] = _transcript_to_json(self.assistant.transcript)
        try:
            folder = chats_dir(self.wb.state)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{self.record['id']}.json").write_text(
                json.dumps(self.record, ensure_ascii=False, indent=1, default=str),
                encoding="utf-8")
        except OSError as exc:
            self._note("warning", f"The conversation was not saved: {exc}", record=False)

    def saved_chats(self) -> list[dict]:
        out = []
        for path in chats_dir(self.wb.state).glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            record["path"] = path
            out.append(record)
        return sorted(out, key=lambda r: r.get("updated", r.get("created", "")), reverse=True)

    async def history(self) -> None:
        records = self.saved_chats()
        with ui.dialog() as dialog, ui.card().classes("w-[620px] max-w-[94vw]"):
            ui.label("Saved conversations").classes("text-subtitle1")
            if not records:
                ui.label(f"No conversation yet in {chats_dir(self.wb.state)}") \
                    .classes("text-caption text-grey-7")
            with ui.column().classes("w-full gap-0 max-h-[60vh] overflow-auto"):
                for record in records[:100]:
                    with ui.item().props("dense").classes("w-full"):
                        with ui.item_section():
                            ui.item_label(record.get("title") or "(untitled)") \
                                .classes("text-body2 ots-ellipsis")
                            ui.item_label(f"{record.get('updated', record.get('created', ''))} · "
                                          f"{record.get('provider', '')}").props("caption")
                        with ui.item_section().props("side"):
                            with ui.row().classes("gap-0"):
                                ui.button(icon="open_in_browser",
                                          on_click=lambda r=record: dialog.submit(("open", r))) \
                                    .props("flat dense round size=sm").tooltip("Reopen")
                                ui.button(icon="download",
                                          on_click=lambda r=record: self.export(r)) \
                                    .props("flat dense round size=sm") \
                                    .tooltip("Export in Markdown")
                                ui.button(icon="delete",
                                          on_click=lambda r=record: dialog.submit(("delete", r))) \
                                    .props("flat dense round size=sm").tooltip("Delete")
            with ui.row().classes("w-full justify-end"):
                ui.button("Close", on_click=lambda: dialog.submit(None)).props("flat")
        dialog.open()
        answer = await dialog
        dialog.delete()
        if not answer:
            return
        action, record = answer
        if action == "delete":
            Path(record["path"]).unlink(missing_ok=True)
            ui.notify("Conversation deleted")
        else:
            self.reopen(record)

    def export(self, record: dict) -> None:
        name = re.sub(r"[^\w-]+", "_", (record.get("title") or "chat")[:40]).strip("_") or "chat"
        ui.download.content(chat_markdown(record), f"{name}.md")

    def reopen(self, record: dict) -> None:
        """Show a saved conversation again; the assistant continues it."""
        from ...ai import get_assistant

        if self.busy:
            ui.notify("Stop the current request first", type="warning")
            return
        self.new_chat()
        self.record = {k: v for k, v in record.items() if k != "path"}
        for item in self.record.get("items", []):
            kind = item.get("kind")
            if kind == "user":
                self._bubble(item.get("text", ""), True, attachments=item.get("attachments"))
            elif kind == "assistant":
                self._bubble(item.get("text", ""), False, item.get("thinking", ""))
            elif kind == "tool":
                self._tool_card(item)
            elif kind == "note":
                self._note(item.get("level", "info"), item.get("text", ""), record=False)
        try:
            self.assistant = get_assistant(ChatHost(self.wb), on_event=self._on_event)
            self.assistant.transcript = _transcript_from_json(self.record.get("transcript", []))
        except Exception as exc:  # no provider: the conversation can still be read
            self.assistant = None
            self._note("warning", f"Reopened for reading only: {exc}", record=False)
        self._note("info", "Conversation reopened", record=False)

    # ------------------------------------------------------------------ events (UI thread)
    def _stream_bubble(self) -> dict[str, Any]:
        if self.stream is None:
            with self.log:
                card = ui.card().props("flat").classes("q-pa-sm bg-grey-1 max-w-full")
                with card:
                    reasoning = ui.column().classes("w-full gap-0")
                    text = ChatMarkdown("").classes("text-body2")
                    buttons = ui.column().classes("gap-0")
            self.stream = {"card": card, "reasoning": reasoning, "text": text, "buttons": buttons,
                           "content": "", "thinking": "", "thinking_md": None}
        return self.stream

    def _tool_card(self, item: dict, running: bool = False) -> dict[str, Any]:
        with self.log:
            card = ui.card().props("flat bordered").classes("q-pa-xs w-full")
            with card:
                with ui.row().classes("items-center no-wrap gap-1"):
                    spinner = ui.spinner(size="sm") if running else None
                    ui.label(f"{item['name']}({str(item.get('arguments', ''))[:120]})") \
                        .classes("text-caption text-weight-medium")
                body = ui.column().classes("gap-0")
        entry = {"card": card, "spinner": spinner, "body": body}
        if not running:
            self._tool_result(entry, item)
        return entry

    def _tool_result(self, entry: dict[str, Any], event: dict) -> None:
        if entry.get("spinner") is not None:
            entry["spinner"].delete()
            entry["spinner"] = None
        with entry["body"]:
            duration = float(event.get("duration", 0.0))
            if event.get("ok"):
                ui.label(f"done in {duration:.1f} s" + (f" · {event['summary']}"
                                                      if event.get("summary") else "")) \
                    .classes("text-caption text-grey-8")
            else:
                ui.label(f"{event.get('error', 'failed')}").classes("text-caption text-negative")
            session = self.wb.state.session
            for name in event.get("results", []):
                if any(r.name == name for r in session.results):
                    ui.button(f"Open {name}", icon="open_in_new",
                              on_click=lambda n=name: self.wb.open_result(n)) \
                        .props("flat dense no-caps size=sm")

    def handle(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "delta":
            bubble = self._stream_bubble()
            if event.get("part") == "thinking":
                bubble["thinking"] += event.get("text", "")
                if bubble["thinking_md"] is None:
                    with bubble["reasoning"]:
                        with ui.expansion("Reasoning", icon="psychology") \
                                .props("dense").classes("w-full text-grey-8"):
                            bubble["thinking_md"] = ChatMarkdown("").classes("text-caption")
                bubble["thinking_md"].set_content(bubble["thinking"])
            else:
                bubble["content"] += event.get("text", "")
                bubble["text"].set_content(bubble["content"])
        elif kind == "reply":
            text, thinking = event.get("text", ""), event.get("thinking", "")
            if self.stream is not None:
                bubble = self.stream
                bubble["text"].set_content(text)
                if thinking and bubble["thinking_md"] is None:
                    with bubble["reasoning"]:
                        with ui.expansion("Reasoning", icon="psychology") \
                                .props("dense").classes("w-full text-grey-8"):
                            ChatMarkdown(thinking).classes("text-caption")
                with bubble["buttons"]:
                    self._code_buttons(text)
                self.stream = None
            else:
                self._bubble(text, False, thinking)
            self.record["items"].append({"kind": "assistant", "text": text,
                                         "thinking": thinking})
        elif kind == "usage":
            from ...ai.providers import context_tokens

            used = int(event.get("input", 0)) + int(event.get("output", 0))
            try:
                size = context_tokens(self.wb.state.config)
            except ParameterError:
                size = 0
            self.context_label.text = f"{_tokens(used)} / {_tokens(size)} tokens" if size \
                else f"{_tokens(used)} tokens"
        elif kind == "availability":
            ok = bool(event.get("ok"))
            self.availability.text = ("● " if ok else "✕ ") + ("available" if ok else
                                                               event.get("text", ""))
            self.availability.classes(replace="text-caption ellipsis " + (
                "text-positive" if ok else "text-negative"))
            self.availability_tip.text = event.get("text", "")
        elif kind == "note":
            self._note(event.get("level", "info"), event.get("text", ""))
        elif kind == "tool_start":
            self.stream = None  # the text of this round is complete
            self.cards[event["id"]] = self._tool_card(event, running=True)
        elif kind == "tool_end":
            entry = self.cards.get(event["id"])
            if entry is not None:
                self._tool_result(entry, event)
            self.record["items"].append({k: event.get(k) for k in (
                "name", "arguments", "ok", "error", "summary", "duration", "results")}
                | {"kind": "tool"})
        elif kind == "done":
            self.busy = False
            self.stream = None
            self.stop_button.set_visibility(False)
            self.status.text = ""
            if event.get("state") == "failed":
                self._note("error", event.get("error") or "The request failed")
            self.save()
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
                    def answer(value: Any, card: Any = card) -> None:
                        self.wb.state.requests.answer(request, value)
                        card.clear()
                        with card:
                            label = {True: "Allowed: ", False: "Denied: ",
                                     "chat": "Allowed for this chat: "}[value]
                            ui.label(label + event.get("question", "")).classes("text-caption")

                    ui.button("Allow", icon="check", on_click=lambda: answer(True)) \
                        .props("unelevated dense no-caps")
                    if event.get("key"):
                        ui.button("Allow for this chat", icon="done_all",
                                  on_click=lambda: answer("chat")) \
                            .props("flat dense no-caps") \
                            .tooltip(f"Do not ask again for {event['key']} in this conversation")
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
        self._note("info", "Summarizing the signals for the assistant (/init)…", record=False)

    def edit_context(self) -> None:
        path = self.wb.root / "context.md"
        if not path.exists():
            path.write_text("# Context for the AI assistant\n\nBench, digitizer settings, "
                            "sensor, expected performance…\n", encoding="utf-8")
        self.wb.open_file(path)

    async def choose_model(self) -> None:
        from ...ai.providers import ai_settings

        cfg = self.wb.state.config
        settings = ai_settings(cfg)
        with ui.dialog() as dialog, ui.card().classes("w-[460px]"):
            ui.label("AI provider for this session").classes("text-subtitle1")
            provider = ui.select(["ollama", "anthropic", "openai"],
                                 value=settings["provider"], label="Provider") \
                .props("dense outlined").classes("w-full")
            model = ui.input("Model", value=settings["model"]).props("dense outlined") \
                .classes("w-full")
            base = ui.input("Server URL (Ollama, vLLM)", value=settings["base_url"]) \
                .props("dense outlined").classes("w-full")
            context = ui.number("Context (tokens, Ollama; 0 = server default)",
                                value=int(str(settings.get("context") or 0).replace("_", ""))) \
                .props("dense outlined").classes("w-full")
            ui.label("API keys are read from the environment of the server only.") \
                .classes("text-caption text-grey-7")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Apply", on_click=lambda: dialog.submit(True)).props("unelevated")
        dialog.open()
        if await dialog:
            cfg.set("ai.profile", "")  # explicit settings replace the profile
            cfg.set("ai.provider", provider.value)
            cfg.set("ai.model", model.value or "")
            cfg.set("ai.base_url", base.value or "")
            cfg.set("ai.context", int(context.value or 0))
            self.profile.value = ""
            self.assistant = None
            self.update_provider()
            self._note("info", f"Provider set to {provider.value} for this session")
        dialog.delete()


__all__ = ["ChatHost", "ChatPanel", "chat_markdown", "chats_dir"]
