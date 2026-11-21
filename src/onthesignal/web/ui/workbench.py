"""The workbench: layout of a browser tab and everything it shows (§4).

One :class:`Workbench` is created per browser tab. It reads the shared
:class:`~onthesignal.web.state.WebState`: a timer drains the events of its channel (results
to open, notifications, questions) and follows ``session.version`` to refresh the views.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nicegui import background_tasks, ui

from ... import api
from ...cli.completion import fuzzy_match
from ...core.errors import ParameterError
from ...core.registry import commands
from ...io import is_signal_file
from ..security import confine
from ..state import WebState
from .chat import ChatPanel
from .dialogs import (
    ask_text,
    batch_dialog,
    compare_dialog,
    launch_analysis,
    new_test_signal,
    run_script_dialog,
)
from .objects import ObjectsPanel
from .tabs import (
    BatchTab,
    CompareTab,
    DiffTab,
    EditorTab,
    FigureTab,
    RealtimeTab,
    ReportTab,
    ResultTab,
    SignalTab,
    VariableTab,
    WorkArea,
)
from .views import (
    AcquisitionView,
    AnalysesView,
    FilesView,
    HelpView,
    RealtimeView,
    ReportsView,
    ScriptsView,
    SettingsView,
)

CSS = """
body { font-size: 13px; }
.q-tab { min-height: 32px; padding: 0 10px; }
.q-tab__label { font-size: 12.5px; }
.ots-activity .q-btn { width: 44px; }
.ots-term { width: 100%; height: 100%; }
.ots-term .xterm { height: 100%; padding: 4px; }
.ots-term .xterm .xterm-viewport { background-color: #fcfcfb !important; }  /* xterm.js 6 */
.u-legend { font-size: 11.5px; }
.u-legend .u-marker { width: 10px; height: 3px; }
/* Frame of the page: NiceGUI 4 puts the padding and gap of its containers in a layer above
   Quasar's spacing classes, which would not apply alone. The work area and the drawers start
   right under the header line; the splitter fills the height left by the header and the
   footer (--ots-frame, measured by FRAME_SCRIPT), so that the page does not scroll. */
.nicegui-content { padding: 0; gap: 0; }
.nicegui-drawer.q-pa-none { padding: 0; }
.nicegui-header.q-py-xs { padding-top: 4px; padding-bottom: 4px; }
.nicegui-footer.q-py-none { padding-top: 0; padding-bottom: 0; }
.nicegui-header.q-px-md, .nicegui-footer.q-px-md { padding-left: 16px; padding-right: 16px; }
.ots-main { height: calc(100vh - var(--ots-frame, 92px)); }
.q-drawer__content { overflow-x: hidden; }
.q-drawer .q-splitter, .q-drawer .q-splitter__panel { min-width: 0; max-width: 100%; }
.q-item__section--main { min-width: 0; }
.ots-ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* Work area in one or two sides (§4.3) */
.ots-unsplit > .q-splitter__separator, .ots-unsplit > .q-splitter__after { display: none; }
.ots-work > .q-splitter__panel { min-width: 0; }
.ots-side-bar { border-bottom: 1px solid rgba(128, 128, 128, 0.18); min-height: 33px; }
.ots-side.ots-focused > .ots-side-bar { box-shadow: inset 0 2px 0 var(--q-primary); }
/* Formulas of the chat (MathML, §11.2) */
.nicegui-markdown math { font-size: 1.06em; }
.nicegui-markdown math[display="block"] { margin: 0.35em 0; overflow-x: auto; }
/* Dark theme (§4.8): surfaces and inks of the validated dark palette (plot.style.DARK).
   In the "overrides" layer: Quasar's colour classes are !important rules of a later
   layer, and for !important rules the earlier layer wins. */
@layer overrides {
  body.body--dark { background: #0d0d0d; color: #f0efec; }
  body.body--dark .bg-white { background: #1a1a19 !important; }
  body.body--dark .bg-grey-1 { background: #141413 !important; }
  body.body--dark .bg-grey-2 { background: #232321 !important; }
  body.body--dark .bg-blue-1 { background: #1b2a3e !important; }
  body.body--dark .bg-amber-1 { background: #3a2f12 !important; }
  body.body--dark .text-grey-5, body.body--dark .text-grey-6,
  body.body--dark .text-grey-7 { color: #898781 !important; }
  body.body--dark .text-grey-8, body.body--dark .text-grey-9,
  body.body--dark .text-grey-10 { color: #c3c2b7 !important; }
  body.body--dark .border-b, body.body--dark .border,
  body.body--dark .q-header { border-color: #2c2c2a !important; }
  body.body--dark .ots-term .xterm .xterm-viewport { background-color: #1a1a19 !important; }
  body.body--dark .nicegui-code { background: #232321; }
}
"""

#: Terminal colors of the two themes (xterm.js); the page script switches them.
TERMINAL_THEMES = {
    "light": {"background": "#fcfcfb", "foreground": "#0b0b0b", "cursor": "#2a78d6",
              "selectionBackground": "#cde2fb", "brightBlack": "#898781"},
    "dark": {"background": "#1a1a19", "foreground": "#f0efec", "cursor": "#3987e5",
             "selectionBackground": "#184f95", "brightBlack": "#898781"},
}
THEME_SCRIPT = """<script>
(() => {
  const themes = %s;
  window.otsApplyTheme = () => {
    const dark = document.body.classList.contains("body--dark");
    if (window.monaco && window.monaco.editor) {
      window.monaco.editor.setTheme(dark ? "vs-dark" : "vs");
    }
    for (const el of document.querySelectorAll(".ots-term")) {
      const term = (getElement(el) || {}).terminal;
      if (term) term.options.theme = dark ? themes.dark : themes.light;
    }
  };
  new MutationObserver(() => window.otsApplyTheme())
    .observe(document.body, { attributes: true, attributeFilter: ["class"] });
  window.addEventListener("load", () => setTimeout(window.otsApplyTheme, 800));
})();
</script>"""

#: Height of the header and the footer in --ots-frame (they may wrap on a narrow window).
FRAME_SCRIPT = """<script>
(() => {
  const start = () => {
    const header = document.querySelector(".q-header");
    const footer = document.querySelector(".q-footer");
    if (!header || !footer) { setTimeout(start, 100); return; }
    const fit = () => document.documentElement.style.setProperty(
      "--ots-frame", header.offsetHeight + footer.offsetHeight + "px");
    const observer = new ResizeObserver(fit);
    observer.observe(header);
    observer.observe(footer);
    fit();
  };
  start();
})();
</script>"""

VIEWS: list[tuple[str, str, str]] = [
    ("files", "folder", "Files"),
    ("analyses", "query_stats", "Analyses"),
    ("acquisition", "sensors", "Acquisition"),
    ("realtime", "monitor_heart", "Real time"),
    ("reports", "article", "Reports"),
    ("scripts", "code", "Scripts"),
    ("settings", "settings", "Settings"),
    ("help", "help_outline", "Help"),
]
BINARY_PEEK = 8192


class Workbench:
    def __init__(self, state: WebState, client: Any, root: Path, docs_url: str = "") -> None:
        self.state = state
        self.client = client
        self.id = client.id
        self.root = root.resolve()
        self.roots = [(self.root / r).resolve() for r in state.config.get("web.roots", ["."])]
        if self.root not in self.roots:
            self.roots.insert(0, self.root)
        self.reports_dir = self.root / str(state.config.get("paths.reports", "reports"))
        self.docs_url = docs_url
        self.registered = {c.name for c in commands()}
        self.channel = state.connect(self.id)
        self.seen_version = -1
        self.pending_window: tuple[str, str] | None = None
        self.views: dict[str, Any] = {}
        self._term_buffer: list[str] = []
        self._term_lock = threading.Lock()
        self._log_seen = 0
        self._problems_seen = 0
        state.terminal.on_output.append(self._terminal_output)
        client.on_disconnect(self._disconnected)

    # ------------------------------------------------------------------ layout
    def build(self) -> None:
        import json

        ui.add_css(CSS)
        ui.add_body_html("<script>document.addEventListener('keydown', (e) => {"
                         "if ((e.ctrlKey || e.metaKey) && ['k', 'p'].includes(e.key)) "
                         "e.preventDefault(); }, true);</script>")
        ui.add_body_html(THEME_SCRIPT % json.dumps(TERMINAL_THEMES))
        ui.add_body_html(FRAME_SCRIPT)
        theme = str(self.state.config.get("web.theme", "auto")).lower()
        self.dark = ui.dark_mode({"dark": True, "light": False}.get(theme))
        self.layout_root = ui.element("div").classes("w-full")
        with ui.header(elevated=False).classes("bg-white text-grey-9 q-py-xs q-px-md items-center "
                                               "gap-3 border-b"):
            ui.label("onthesignal").classes("text-subtitle1 text-weight-bold")
            ui.label(str(self.root)).classes("text-caption text-grey-7")
            ui.button("/  Search commands, objects, files", on_click=lambda: self.palette()) \
                .props("flat no-caps align=left").classes("grow bg-grey-2 text-grey-7")
            self.ai_label = ui.label("").classes("text-caption text-grey-8")
            with ui.button(icon="contrast").props("flat round dense") as theme_button:
                with ui.menu():
                    ui.menu_item("Follow the system", lambda: self.set_theme("auto"))
                    ui.menu_item("Light", lambda: self.set_theme("light"))
                    ui.menu_item("Dark", lambda: self.set_theme("dark"))
            theme_button.tooltip("Theme: light, dark or that of the system")
            ui.button(icon="terminal", on_click=self.toggle_terminal) \
                .props("flat round dense").tooltip("Python terminal (Ctrl+`)")
            ui.button(icon="smart_toy", on_click=self.toggle_chat) \
                .props("flat round dense").tooltip("AI chat (Ctrl+Shift+I)")
        with ui.left_drawer(value=True, bordered=True).props("width=360").classes("q-pa-none") \
                as self.left:
            with ui.row().classes("w-full h-full no-wrap gap-0"):
                with ui.column().classes("ots-activity gap-0 bg-grey-2 h-full q-py-xs"):
                    for key, icon, label in VIEWS:
                        ui.button(icon=icon, on_click=lambda key=key: self.show_view(key)) \
                            .props("flat dense").tooltip(label)
                with ui.splitter(horizontal=True, value=58).classes("grow h-full min-w-0") \
                        as split:
                    with split.before:
                        self.objects = ObjectsPanel(self)
                        self.objects.build()
                    with split.after:
                        with ui.column().classes("w-full gap-0"):
                            self.view_title = ui.label("").classes(
                                "text-caption text-weight-bold text-grey-8 q-px-sm q-pt-xs")
                            self.view_box = ui.column().classes("w-full gap-0")
        with ui.right_drawer(value=True, bordered=True).props("width=390").classes("q-pa-none") \
                as self.right:
            self.chat = ChatPanel(self)
            self.chat.build()
        with ui.footer().classes("bg-grey-2 text-grey-8 q-py-none q-px-md"):
            with ui.row().classes("w-full items-center gap-4 no-wrap text-caption"):
                self.status_objects = ui.label("")
                self.status_jobs = ui.label("")
                ui.space()
                self.status_ai = ui.label("")
                self.status_clock = ui.label("")
        with ui.splitter(horizontal=True, value=66) \
                .classes("w-full ots-main") as self.main_split:
            with self.main_split.before:
                self.work = WorkArea(self)
                self.work.build()
            with self.main_split.after:
                self._bottom_panel()
        self.keyboard = ui.keyboard(on_key=self._key)
        self.show_view("files")
        ui.timer(0.1, self._poll)
        ui.timer(1.0, self._tick)
        ui.timer(0.6, self._fit_terminal, once=True)

    def _bottom_panel(self) -> None:
        with ui.column().classes("w-full h-full gap-0"):
            self.bottom_tabs = ui.tabs().props("dense no-caps align=left inline-label") \
                .classes("w-full bg-grey-1 text-grey-8")
            with self.bottom_tabs:
                ui.tab("python", "PYTHON", icon="terminal")
                ui.tab("output", "OUTPUT")
                ui.tab("problems", "PROBLEMS")
                ui.tab("jobs", "JOBS")
                ui.tab("history", "HISTORY")
            with ui.tab_panels(self.bottom_tabs, value="python") \
                    .props("animated=false keep-alive").classes("w-full grow"):
                with ui.tab_panel("python").classes("q-pa-none h-full"):
                    self.xterm: Any = None
                    if not self.state.code_execution:
                        ui.label("The Python terminal is disabled ([web] code_execution = "
                                 "false).").classes("text-grey-7 q-pa-md")
                        return
                    scrollback = int(self.state.config.get("web.scrollback", 10000))
                    self.xterm = ui.xterm({
                        "convertEol": True, "cursorBlink": True, "fontSize": 13,
                        "scrollback": scrollback,
                        "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                        "theme": TERMINAL_THEMES["light"],  # the page script follows the theme
                    }).classes("ots-term")
                    self.xterm.on_data(lambda e: self.state.terminal.feed(e.data))
                    self.xterm.on_resize(lambda e: self.state.terminal.resize(e.cols, e.rows))
                    replay = self.state.terminal.scrollback()
                    if replay:
                        self.xterm.write(replay)
                with ui.tab_panel("output").classes("q-pa-xs"):
                    self.output_log = ui.log(max_lines=2000).classes("w-full h-full text-xs")
                with ui.tab_panel("problems").classes("q-pa-xs"):
                    self.problems_log = ui.log(max_lines=500).classes("w-full h-full text-xs")
                with ui.tab_panel("jobs").classes("q-pa-xs"):
                    self.jobs_box = ui.column().classes("w-full gap-0")
                with ui.tab_panel("history").classes("q-pa-xs"):
                    self.history_log = ui.log(max_lines=5000).classes("w-full h-full text-xs")

    # ------------------------------------------------------------------ side views
    def show_view(self, key: str) -> None:
        builders: dict[str, Callable[[], Any]] = {
            "files": lambda: FilesView(self), "analyses": lambda: AnalysesView(self),
            "acquisition": lambda: AcquisitionView(self), "realtime": lambda: RealtimeView(self),
            "reports": lambda: ReportsView(self),
            "scripts": lambda: ScriptsView(self), "settings": lambda: SettingsView(self),
            "help": lambda: HelpView(self),
        }
        self.left.show()
        self.view_title.text = dict((k, label) for k, _, label in VIEWS)[key].upper()
        self.view_box.clear()
        with self.view_box:
            view = builders[key]()
            view.build()
        self.views = {key: view}

    def _view(self, key: str) -> Any:
        return self.views.get(key)

    # ------------------------------------------------------------------ opening objects
    def active_signal(self) -> str | None:
        key = self.work.active()
        if key and key.startswith("signal:"):
            return key.split(":", 1)[1].split("+")[0]
        return None

    def open_signal(self, *names: str, overlay: bool | None = None) -> None:
        """Time plot of one or several signals: ``overlay`` in one panel, or stacked."""
        names = tuple(n for n in names if n in self.state.session.signals)
        if not names:
            return
        key = "signal:" + "+".join(names)
        tab = self.work.content(key)
        if tab is not None and overlay is not None and len(names) > 1 \
                and tab.stacked == overlay:
            tab._set("stacked", not overlay)
            tab._header()
        self.work.open(key, " + ".join(names), lambda: SignalTab(
            self, list(names), stacked=not overlay if overlay is not None else True).build(),
                       "show_chart")
        self.objects.refresh()

    def open_result(self, name: str) -> None:
        try:
            result = self.state.session.get_result(name)
        except ParameterError as exc:
            ui.notify(str(exc), type="warning")
            return
        signals = ", ".join(s.get("name", "") for s in result.signals)
        self.work.open(f"result:{name}", f"{name} {result.kind} {signals}".strip(),
                       lambda: ResultTab(self, name).build(), "analytics")
        self.objects.refresh()

    def open_figure(self, name: str) -> None:
        self.work.open(f"figure:{name}", name, lambda: FigureTab(self, name).build(), "image")

    def open_variable(self, name: str) -> None:
        self.work.open(f"variable:{name}", name, lambda: VariableTab(self, name).build(),
                       "data_object")

    def open_file(self, path: str | Path, text: str | None = None) -> None:
        """Open a file in the editor; ``text`` replaces its content (not saved)."""
        try:
            path = confine(path, self.roots)
        except PermissionError as exc:
            ui.notify(str(exc), type="negative")
            return
        limit = float(self.state.config.get("web.editor_max_mb", 5)) * 1024 * 1024
        if path.exists() and text is None:
            if is_signal_file(path):  # a day file of an SDS archive has no .mseed extension
                ui.notify(f"{path.name} is a signal file (miniSEED): loaded, not edited")
                self.load_files([path], {})
                return
            with path.open("rb") as fh:
                if b"\0" in fh.read(BINARY_PEEK):
                    ui.notify(f"{path.name} is a binary file", type="warning")
                    return
            if path.stat().st_size > limit:
                ui.notify(f"{path.name} is larger than the editor limit "
                          f"([web] editor_max_mb)", type="warning")
                return
        self.work.open(f"file:{path}", path.name, lambda: EditorTab(self, path, text).build(),
                       "edit")

    def open_code(self, code: str) -> None:
        scratch = self.root / "scratch"
        scratch.mkdir(exist_ok=True)
        path = scratch / f"ai_{datetime.now():%Y%m%d_%H%M%S}.py"
        path.write_text(code, encoding="utf-8")
        self.open_file(path)

    def review_changes(self, path: Path | None, original: str, proposed: str,
                       on_accept: Callable[[str], Any],
                       on_reject: Callable[[], Any] | None = None, key: str = "",
                       title: str = "", note: str = "") -> None:
        """Show a change proposed by the AI in a diff view, to accept or reject (§9.6)."""
        name = path.name if path is not None else "proposal"
        title = title or f"Review the changes of {name}"
        self.work.open(key or f"review:{path}", f"Review {name}",
                       lambda: DiffTab(self, title, path, original, proposed, on_accept,
                                       on_reject, note).build(), "difference")

    def _review_request(self, event: dict) -> None:
        """A script generated by ``/ai_script``: the terminal waits for the user's choice."""
        request = event["request"]
        answer = self.state.requests.answer
        path = Path(str(event.get("path", "")))
        self.review_changes(
            path, str(event.get("original", "")), str(event.get("proposed", "")),
            on_accept=lambda text: answer(request, text),
            on_reject=lambda: answer(request, None), key=f"review:{request}",
            title=str(event.get("title", "")) or f"Script proposed by the AI: {path.name}",
            note="New file." if not event.get("original") else "")

    def open_compare(self, names: list[str]) -> None:
        """Overlay results of the same analysis (§7.6)."""
        names = list(dict.fromkeys(names))
        if len(names) < 2:
            ui.notify("Choose at least two results to compare", type="warning")
            return
        self.work.open("compare:" + "+".join(names), "Compare " + ", ".join(names),
                       lambda: CompareTab(self, names).build(), "compare_arrows")

    def compare_with(self, name: str) -> None:
        async def run() -> None:
            names = await compare_dialog(self, name)
            if names:
                self.open_compare(names)

        self.spawn(run)

    def new_batch(self, pattern: str | None = None) -> None:
        """Batch form (§8.5), then the tab that follows the batch."""
        async def run() -> None:
            settings = await batch_dialog(self, pattern)
            if settings is None:
                return
            try:
                batch = self.state.start_batch(settings, client=self.id)
            except (ParameterError, PermissionError, OSError) as exc:
                ui.notify(str(exc), type="warning")
                return
            self.open_batch(batch.id)
            view = self._view("scripts")
            if view is not None:
                view.refresh_batches()

        self.spawn(run)

    def open_batch(self, run_id: int) -> None:
        run = self.state.batch(run_id)
        if run is None:
            return
        self.work.open(f"batch:{run_id}", f"{run.title} #{run_id}",
                       lambda: BatchTab(self, run_id).build(), "dynamic_feed")

    def open_realtime(self) -> None:
        self.work.open("realtime", "Real time", lambda: RealtimeTab(self).build(),
                       "monitor_heart")

    def preview_report(self, folder: Path) -> None:
        rel = folder.resolve().relative_to(self.reports_dir.resolve())
        url = f"/_ots/reports/{rel.as_posix()}/report.html"
        self.work.open(f"report:{rel}", f"Report {rel}", lambda: ReportTab(self, url, str(rel))
                       .build(), "article")

    def on_tab_change(self) -> None:
        if hasattr(self, "objects"):
            self.objects.refresh()

    # ------------------------------------------------------------------ actions
    def spawn(self, coroutine_function: Callable[..., Any], *args: Any) -> None:
        """Run a dialog coroutine without blocking the timer that called it."""
        async def runner() -> None:
            with self.layout_root:
                await coroutine_function(*args)

        background_tasks.create(runner())

    def launch(self, name: str, signals: list[str] | None = None) -> None:
        self.spawn(launch_analysis, self, name, signals)

    async def choose_analysis(self) -> str | None:
        with ui.dialog() as dialog, ui.card().classes("w-[460px]"):
            ui.label("Analysis").classes("text-subtitle1")
            for cmd in commands():
                with ui.item(on_click=lambda n=cmd.name: dialog.submit(n)).props("dense clickable"):
                    with ui.item_section():
                        ui.item_label(f"/{cmd.name}").classes("text-weight-medium")
                        ui.item_label(cmd.description).props("caption")
        dialog.open()
        answer = await dialog
        dialog.delete()
        return answer

    def choose_and_launch(self, signals: list[str]) -> None:
        async def run() -> None:
            name = await self.choose_analysis()
            if name:
                await launch_analysis(self, name, signals)

        self.spawn(run)

    def run_analysis(self, name: str, signals: list[str], params: dict) -> None:
        def work(job: Any) -> Any:
            return api.run(name, *signals, show=True, **params)

        self.state.jobs.start(f"{name} {' '.join(signals)}", work, kind="analysis",
                              client=self.id, on_done=self.report_failure)

    def regenerate_agent_doc(self) -> None:
        from ...ai.context import write_agent_doc

        def done(job: Any) -> None:
            self.report_failure(job)
            if job.state == "done":
                self.channel.push({"type": "notify", "level": "positive",
                                   "text": f"Agent doc written to {job.result}"})

        self.state.jobs.start("/gen_ai_doc", lambda job: write_agent_doc(), kind="ai",
                              client=self.id, on_done=done)

    def new_test_signal(self, kind: str) -> None:
        self.spawn(new_test_signal, self, kind)

    def run_script(self, name: str) -> None:
        self.spawn(run_script_dialog, self, name)

    def signal_expression(self) -> None:
        if not self.state.code_execution:
            ui.notify("Expressions run in the Python terminal, disabled by "
                      "[web] code_execution = false", type="warning")
            return

        async def run() -> None:
            text = await ask_text("New signal from an expression",
                                  "Python assignment, e.g. S4 = S1 - S2 or S5 = 2 * S1",
                                  "", "Create")
            if text:
                self.state.terminal.submit(text)

        self.spawn(run)

    def rename_signal(self, name: str) -> None:
        async def run() -> None:
            new = await ask_text(f"Rename {name}", "New name (Python identifier)", name,
                                 "Rename")
            if new and new != name:
                try:
                    self.state.rename_signal(name, new)
                except ParameterError as exc:
                    ui.notify(str(exc), type="negative")

        self.spawn(run)

    def export_signal(self, name: str) -> None:
        async def run() -> None:
            filename = await ask_text(f"Export {name}", "File name (.mseed, .txt or .csv)",
                                      f"{name}.mseed", "Export")
            if not filename:
                return
            try:
                folder = self.root / "data" / "exports"
                folder.mkdir(parents=True, exist_ok=True)
                path = confine(folder / Path(filename).name, self.roots)
                self.state.session.get_signal(name).save(path)
            except (OSError, PermissionError, ParameterError) as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Exported to {path.relative_to(self.root)}")
            ui.download.file(path)

        self.spawn(run)

    def delete_signal(self, name: str) -> None:
        try:
            self.state.remove_signal(name)
        except ParameterError as exc:
            ui.notify(str(exc), type="negative")

    def delete_result(self, name: str) -> None:
        try:
            self.state.session.remove_result(name)
        except ParameterError as exc:
            ui.notify(str(exc), type="warning")

    def delete_figure(self, name: str) -> None:
        self.state.figures = [f for f in self.state.figures if f.name != name]
        self.work.close(f"figure:{name}")
        self.state.bump()

    def add_to_report(self, name: str) -> None:
        if name not in self.state.report_basket:
            self.state.report_basket.append(name)
        ui.notify(f"{name} added to the report basket ({len(self.state.report_basket)})")
        view = self._view("reports")
        if view is not None:
            view.refresh()

    def ask_ai_about(self, result: Any) -> None:  # noqa: D102 - fills the chat input
        signals = ", ".join(s.get("name", "") for s in result.signals)
        self.chat.attach(f"Explain the result {result.name} ({result.kind} of {signals}).")

    def load_files(self, paths: list[Path], options: dict) -> None:
        def work(job: Any) -> Any:
            loaded = []
            for path in paths:
                out = api.load(path, **options)
                loaded += out if isinstance(out, list) else [out]
                self.state.remember_file(path)
            if loaded:
                self.state.to_origin({"type": "open", "what": "signal", "name": loaded[0].name})
            return loaded

        self.state.jobs.start("load " + ", ".join(p.name for p in paths), work, kind="load",
                              client=self.id, on_done=self.report_failure)

    def render_report(self, qmd: Path) -> None:
        from ...report import render_report

        def work(job: Any) -> Any:
            return render_report(Path(qmd), ["html", "pdf"])

        def done(job: Any) -> None:
            self.report_failure(job)
            if job.state == "done":
                self.channel.push({"type": "notify", "level": "positive",
                                   "text": f"Report rendered: {Path(qmd).parent.name}"})
            self.channel.push({"type": "reports"})

        self.state.jobs.start(f"render {Path(qmd).parent.name}", work, kind="report",
                              client=self.id, on_done=done)
        ui.notify("Rendering with Quarto…")

    def report_failure(self, job: Any) -> None:
        """Job callback (any thread): tell this tab when a job failed."""
        if job.state == "failed":
            self.channel.push({"type": "notify", "level": "negative",
                               "text": f"{job.name}: {job.error}"})

    def set_theme(self, theme: str) -> None:
        """Light, dark or following the system (``[web] theme`` gives the default)."""
        if theme == "dark":
            self.dark.enable()
        elif theme == "light":
            self.dark.disable()
        else:
            self.dark.auto()

    def show_chat(self) -> None:
        self.right.show()

    def toggle_chat(self) -> None:
        self.right.toggle()

    def show_terminal(self) -> None:
        if self.main_split.value > 92:
            self.main_split.value = 66
        self.bottom_tabs.set_value("python")

    def toggle_terminal(self) -> None:
        self.main_split.value = 100 if self.main_split.value < 92 else 66

    # ------------------------------------------------------------------ palette
    def palette_items(self, files: bool = False) -> list[tuple[str, str, Callable[[], Any]]]:
        from ...cli.commands import SLASH

        session = self.state.session
        items: list[tuple[str, str, Callable[[], Any]]] = []
        if not files:
            submit = self.state.terminal.submit
            for cmd in commands():
                items.append((f"/{cmd.name}", cmd.description,
                              functools.partial(self.launch, cmd.name)))
            # Console commands with a dedicated view: the palette opens the view.
            views: dict[str, Callable[[], Any]] = {
                "acq": functools.partial(self.show_view, "acquisition"),
                "rt": functools.partial(self.show_view, "realtime"),
                "batch": self.new_batch,
                "scripts": functools.partial(self.show_view, "scripts"),
            }
            for slash in SLASH.values():
                items.append((f"/{slash.name}", slash.description,
                              views.get(slash.name, functools.partial(submit, f"/{slash.name}"))))
            items += [("Real-time dashboard", "SeedLink statistics, trace, FFT and PSD",
                       self.open_realtime),
                      ("New batch…", "run an analysis or a script on many files", self.new_batch),
                      ("Split the work area", "two sides, side by side (Ctrl+\\)",
                       functools.partial(self.spawn, self.work.toggle_split)),
                      ("Move the tab to the other side", "split the work area if needed",
                       functools.partial(self.spawn, self.work.move)),
                      ("Toggle the AI chat", "", self.toggle_chat),
                      ("Toggle dark mode", "light or dark theme", self.dark.toggle),
                      ("Theme: follow the system", "", functools.partial(self.set_theme, "auto")),
                      ("Toggle the Python terminal", "", self.toggle_terminal),
                      ("Focus the Python terminal", "", self.show_terminal),
                      ("New test sine", "", functools.partial(self.new_test_signal, "sine")),
                      ("New test noise", "", functools.partial(self.new_test_signal, "noise")),
                      ("Regenerate agent doc", "/gen_ai_doc", self.regenerate_agent_doc)]
        for name, sig in session.signals.items():
            items.append((name, f"signal {sig.id}", functools.partial(self.open_signal, name)))
        for r in session.results:
            items.append((r.name, f"result {r.kind}", functools.partial(self.open_result, r.name)))
        count = 0
        for root in self.roots:
            for path in sorted(root.rglob("*")):
                if count > 400:
                    break
                parts = path.relative_to(root).parts
                skipped = ("__pycache__", "_site", "_freeze")
                if any(p.startswith(".") or p in skipped for p in parts):
                    continue
                if path.is_file() and path.suffix.lower() in {".py", ".md", ".qmd", ".toml",
                                                               ".txt", ".csv", ".json", ".yml"}:
                    items.append((path.name, str(path.relative_to(root)),
                                  functools.partial(self.open_file, path)))
                    count += 1
                elif path.is_file() and is_signal_file(path):  # miniSEED, SDS day files
                    items.append((path.name, f"load {path.relative_to(root)}",
                                  functools.partial(self.load_files, [path], {})))
                    count += 1
        return items

    def palette(self, files: bool = False) -> None:
        items = self.palette_items(files)
        with ui.dialog() as dialog, ui.card().classes("w-[640px] max-w-[92vw] q-pa-sm"):
            field = ui.input(placeholder="Type a command (/noise S1 fmax=50), an object "
                                         "or a file") \
                .props("autofocus dense outlined").classes("w-full")
            box = ui.column().classes("w-full gap-0 max-h-[60vh] overflow-auto")
            shown: list[tuple[str, str, Callable[[], Any]]] = []

            def render() -> None:
                text = (field.value or "").strip()
                word = text.split(" ")[0].lower()
                shown.clear()
                for item in items:
                    if not word or fuzzy_match(word.lstrip("/"), item[0].lstrip("/").lower()) \
                            or word in item[1].lower():
                        shown.append(item)
                    if len(shown) >= 60:
                        break
                box.clear()
                with box:
                    for label, desc, action in shown:
                        with ui.item(on_click=lambda a=action: (dialog.close(), a())) \
                                .props("dense clickable"):
                            with ui.item_section():
                                ui.item_label(label).classes("text-weight-medium")
                                if desc:
                                    ui.item_label(desc).props("caption lines=1")

            def enter() -> None:
                text = (field.value or "").strip()
                dialog.close()
                if text.startswith("/") and " " in text and not self.state.code_execution:
                    ui.notify("Complete commands run in the Python terminal, disabled by "
                              "[web] code_execution = false", type="warning")
                elif text.startswith("/") and " " in text:
                    self.state.terminal.submit(text)
                    self.show_terminal()
                elif shown:
                    shown[0][2]()
                elif text.startswith("/"):
                    self.state.terminal.submit(text)

            field.on("keydown.enter", enter)
            field.on_value_change(lambda _: render())
            render()
        dialog.open()

    def _key(self, e: Any) -> None:
        if not e.action.keydown:
            return
        key = e.key
        name = str(getattr(key, "name", key)).lower()
        code = str(getattr(key, "code", ""))
        mods = e.modifiers
        if name == "/" and not (mods.ctrl or mods.alt or mods.meta):
            self.palette()
        elif (mods.ctrl or mods.meta) and name == "k":
            self.palette()
        elif (mods.ctrl or mods.meta) and name == "p":
            self.palette(files=True)
        elif mods.ctrl and code == "Backquote":
            self.toggle_terminal()
        elif mods.ctrl and mods.shift and name == "i":
            self.toggle_chat()
        elif (mods.ctrl or mods.meta) and code == "Backslash":
            self.spawn(self.work.toggle_split)

    # ------------------------------------------------------------------ events
    def _terminal_output(self, text: str) -> None:  # terminal thread
        with self._term_lock:
            self._term_buffer.append(text)

    def _disconnected(self) -> None:
        self.state.log("client", "browser tab disconnected")
        if self._terminal_output in self.state.terminal.on_output:
            self.state.terminal.on_output.remove(self._terminal_output)
        self.state.disconnect(self.id)

    def _poll(self) -> None:
        with self._term_lock:
            text = "".join(self._term_buffer)
            self._term_buffer.clear()
        if text and self.xterm is not None:
            self.xterm.write(text)
        for event in self.channel.drain():
            try:
                self._handle(event)
            except Exception as exc:  # one faulty event must not stop the polling
                ui.notify(f"{type(exc).__name__}: {exc}", type="negative")
        if self.state.session.version != self.seen_version:
            self.seen_version = self.state.session.version
            self.objects.refresh()
            self.work.refresh()
            self._refresh_status()
            self._refresh_history()

    def _handle(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "open":
            openers: dict[str, Callable[[str], Any]] = {
                "signal": self.open_signal, "result": self.open_result,
                "figure": self.open_figure, "variable": self.open_variable,
                "file": self.open_file}
            if event.get("what") == "signals":  # plot(S1, S2) of the terminal
                self.open_signal(*event.get("names", []), overlay=event.get("overlay"))
                return
            opener = openers.get(str(event.get("what")))
            if opener is not None:
                opener(str(event.get("name", "")))
        elif kind == "notify":
            level = event.get("level", "info")
            ui.notify(event.get("text", ""), type={"error": "negative"}.get(level, level),
                      multi_line=True)
        elif kind == "problem":
            stamp = datetime.now().strftime("%H:%M:%S")
            self.problems_log.push(f"{stamp} {event.get('level', '')}: {event.get('text', '')}")
        elif kind == "log":
            self._refresh_output()
        elif kind == "job":
            self._refresh_jobs()
            self._refresh_status()
        elif kind == "form":
            self.spawn(launch_analysis, self, event["command"], event.get("signals"),
                       event["request"])
        elif kind == "confirm":
            self.chat.confirm_card(event)
        elif kind == "review":
            self._review_request(event)
        elif kind == "request_done":  # answered in another browser tab
            self.work.close(f"review:{event.get('request')}")
        elif kind == "chat":
            self.chat.handle(event)
        elif kind == "chat_question":
            self.show_chat()
            self.spawn(self.chat.ask, event.get("text", ""))
        elif kind in ("reports", "acquisition"):
            view = self._view(kind)
            if view is not None:
                view.refresh()
        elif kind == "streams":
            for key in ("acquisition", "realtime"):
                view = self._view(key)
                if view is not None:
                    view.refresh()
        elif kind == "batch":
            view = self._view("scripts")
            if view is not None:
                view.refresh_batches()

    def _refresh_output(self) -> None:
        logs = list(self.state.logs)
        for stamp, source, text in logs[self._log_seen:]:
            self.output_log.push(f"{datetime.fromtimestamp(stamp):%H:%M:%S} [{source}] {text}")
        self._log_seen = len(logs)

    def _refresh_history(self) -> None:
        history = self.state.session.history
        self.history_log.clear()
        for line in history[-2000:]:
            self.history_log.push(line)

    def _refresh_jobs(self) -> None:
        self.jobs_box.clear()
        with self.jobs_box:
            for job in reversed(self.state.jobs.items[-30:]):
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    icon = {"running": "hourglass_top", "done": "check_circle",
                            "failed": "error", "cancelled": "block"}.get(job.state, "help")
                    ui.icon(icon, size="16px", color="grey-7")
                    ui.label(f"{job.name} — {job.state} · {job.duration:.1f} s"
                             + (f" · {job.error}" if job.error else "")) \
                        .classes("text-caption grow ellipsis")
                    if job.state == "running" and job.cancel is not None:
                        ui.button("Stop", on_click=lambda j=job: j.cancel()) \
                            .props("flat dense no-caps size=sm")

    def _refresh_status(self) -> None:
        session = self.state.session
        self.status_objects.text = (f"{len(session.signals)} signals · {len(session.results)} "
                                    f"results")
        running = self.state.jobs.running()
        self.status_jobs.text = " · ".join(f"{j.name}…" for j in running[:3])
        from ...ai.context import provider_label

        label = provider_label(self.state.config)
        self.status_ai.text = f"AI: {label}"
        self.ai_label.text = label

    def _tick(self) -> None:
        self.status_clock.text = datetime.now(UTC).strftime("%H:%M:%S UTC")
        self.chat.tick()
        if self.state.jobs.running():
            self._refresh_status()
        for item in self.work.items.values():
            check = getattr(item["content"], "check_disk", None)
            if callable(check):
                check()

    def _fit_terminal(self) -> None:
        if self.xterm is None:
            return
        self.xterm.fit()
        ui.timer(2.0, lambda: self.xterm.fit())
        self.last_fit = time.time()


__all__ = ["Workbench"]
