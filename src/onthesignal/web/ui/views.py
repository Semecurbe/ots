"""Views of the side column: files, analyses, scripts, reports, acquisition, settings, help."""

from __future__ import annotations

import inspect
import io
import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nicegui import ui

from ...core.errors import ParameterError
from ...core.registry import commands
from ..security import confine, safe_name
from .dialogs import ask_text, confirm, load_file_dialog

if TYPE_CHECKING:
    from .workbench import Workbench

DATA_SUFFIXES = {".mseed", ".msd", ".miniseed", ".seed", ".txt", ".csv", ".dat", ".asc", ".sac"}
TEXT_SUFFIXES = {".py", ".md", ".qmd", ".toml", ".txt", ".csv", ".json", ".yml", ".yaml",
                 ".cfg", ".ini", ".sh", ".j2", ".log", ".dat", ".asc", ".xml", ".sql", ""}
CATEGORIES = {"noise": "Noise", "sine": "Sine", "measure": "Measurements",
              "spectral": "Spectral"}


def _size(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _section(title: str) -> None:
    ui.label(title).classes("text-caption text-weight-bold text-grey-7 q-px-sm q-pt-sm")


# ---------------------------------------------------------------------------------- files
class FilesView:
    """Explorer of the project (§9.2), confined to the configured roots."""

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.cwd = wb.root

    def build(self) -> None:
        with ui.column().classes("w-full gap-0"):
            with ui.row().classes("w-full items-center no-wrap gap-0 q-px-xs"):
                ui.button(icon="arrow_upward", on_click=self.up).props("flat dense round size=sm") \
                    .tooltip("Parent folder")
                self.path_label = ui.label("").classes("text-caption text-grey-8 ellipsis grow")
                ui.button(icon="refresh", on_click=self.refresh).props("flat dense round size=sm")
                with ui.button(icon="add").props("flat dense round size=sm"):
                    with ui.menu():
                        ui.menu_item("New file…", self.new_file)
                        ui.menu_item("New folder…", self.new_folder)
            max_mb = int(self.wb.state.config.get("web.upload_max_mb", 1024))
            ui.upload(label="Upload files (drag & drop)", multiple=True, auto_upload=True,
                      max_file_size=max_mb * 1024 * 1024, on_upload=self.uploaded) \
                .props("flat bordered dense accept=*").classes("w-full q-px-xs")
            self.recent = ui.column().classes("w-full gap-0")
            self.box = ui.column().classes("w-full gap-0")
        self.refresh()

    def _recent_files(self) -> None:
        self.recent.clear()
        files = [Path(p) for p in self.wb.state.recent_files if Path(p).exists()][:6]
        if not files:
            return
        with self.recent:
            _section("RECENT FILES")
            for path in files:
                with ui.item(on_click=lambda p=path: self.load(p)).props("dense clickable") \
                        .classes("w-full q-px-sm"):
                    with ui.item_section():
                        ui.item_label(path.name).classes("text-body2")
                        ui.item_label(str(path.parent)).props("caption lines=1")

    def up(self) -> None:
        parent = self.cwd.parent
        if any(parent == r or parent.is_relative_to(r) for r in self.wb.roots):
            self.cwd = parent
            self.refresh()

    def refresh(self) -> None:
        self._recent_files()
        self.box.clear()
        try:
            rel = self.cwd.relative_to(self.wb.root)
            self.path_label.text = f"project/{rel}" if str(rel) != "." else "project"
        except ValueError:
            self.path_label.text = str(self.cwd)
        try:
            entries = sorted(self.cwd.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            with self.box:
                ui.label(str(exc)).classes("text-negative text-caption")
            return
        with self.box:
            for entry in entries:
                if entry.name.startswith(".") or entry.name == "__pycache__":
                    continue
                self._entry(entry)

    def _entry(self, path: Path) -> None:
        is_dir = path.is_dir()
        icon = "folder" if is_dir else ("graphic_eq" if path.suffix.lower() in DATA_SUFFIXES
                                         else "description")
        size = "" if is_dir else _size(path.stat().st_size)
        with ui.item(on_click=lambda p=path: self.open(p)).props("dense clickable") \
                .classes("w-full q-px-sm"):
            with ui.item_section().props("avatar"):
                ui.icon(icon, color="grey-7", size="18px")
            with ui.item_section():
                ui.item_label(path.name).classes("text-body2 ots-ellipsis")
            with ui.item_section().props("side"):
                ui.item_label(size).props("caption")
            with ui.context_menu():
                if not is_dir:
                    ui.menu_item("Open in the editor", lambda p=path: self.wb.open_file(p))
                    if path.suffix.lower() in DATA_SUFFIXES:
                        ui.menu_item("Load as signal", lambda p=path: self.load(p))
                        ui.menu_item("Load with options…", lambda p=path: self.load(p, True))
                    ui.menu_item("Download", lambda p=path: ui.download.file(p))
                else:
                    ui.menu_item("Download as zip", lambda p=path: self.download_dir(p))
                    ui.menu_item("Batch on this folder…", lambda p=path: self.wb.new_batch(
                        f"{self._relative(p)}/*.mseed"))
                ui.menu_item("Rename…", lambda p=path: self.rename(p))
                ui.menu_item("Copy path", lambda p=path: ui.clipboard.write(str(p)))
                ui.menu_item("Delete…", lambda p=path: self.delete(p))

    async def open(self, path: Path) -> None:
        if path.is_dir():
            self.cwd = path
            self.refresh()
            return
        suffix = path.suffix.lower()
        if suffix in {".mseed", ".msd", ".miniseed", ".seed", ".sac"}:
            await self.load(path)
        else:
            self.wb.open_file(path)

    async def load(self, path: Path, options: bool = False) -> None:
        await load_file_dialog(self.wb, path, options)

    def _target(self, name: str) -> Path:
        return confine(self.cwd / safe_name(name), self.wb.roots)

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.wb.root).as_posix()
        except ValueError:
            return str(path)

    async def new_file(self) -> None:
        name = await ask_text("New file", "File name", "notes.md", "Create")
        if not name:
            return
        try:
            path = self._target(name)
            if path.exists():
                raise ParameterError(f"{path.name} already exists")
            path.write_text("", encoding="utf-8")
        except (OSError, PermissionError, ParameterError) as exc:
            ui.notify(str(exc), type="negative")
            return
        self.refresh()
        self.wb.open_file(path)

    async def new_folder(self) -> None:
        name = await ask_text("New folder", "Folder name", "", "Create")
        if not name:
            return
        try:
            self._target(name).mkdir()
        except (OSError, PermissionError) as exc:
            ui.notify(str(exc), type="negative")
        self.refresh()

    async def rename(self, path: Path) -> None:
        name = await ask_text("Rename", "New name", path.name, "Rename")
        if not name or name == path.name:
            return
        try:
            target = confine(path.parent / safe_name(name), self.wb.roots)
            path.rename(target)
        except (OSError, PermissionError) as exc:
            ui.notify(str(exc), type="negative")
        self.refresh()

    async def delete(self, path: Path) -> None:
        if not await confirm(f"Delete {path.name}?", "This cannot be undone.", "Delete"):
            return
        try:
            confine(path, self.wb.roots)
            shutil.rmtree(path) if path.is_dir() else path.unlink()
            self.wb.state.log("files", f"deleted {path}")
        except (OSError, PermissionError) as exc:
            ui.notify(str(exc), type="negative")
        self.refresh()

    def download_dir(self, path: Path) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in path.rglob("*"):
                if item.is_file():
                    archive.write(item, item.relative_to(path.parent))
        ui.download.content(buffer.getvalue(), f"{path.name}.zip")

    async def uploaded(self, e: Any) -> None:
        upload_dir = self.wb.root / str(self.wb.state.config.get("web.upload_dir",
                                                                 "data/uploads"))
        try:
            upload_dir.mkdir(parents=True, exist_ok=True)
            target = confine(upload_dir / safe_name(e.file.name), self.wb.roots)
            saved = e.file.save(target)
            if inspect.isawaitable(saved):
                await saved
        except (OSError, PermissionError) as exc:
            ui.notify(f"Upload refused: {exc}", type="negative")
            return
        self.wb.state.log("files", f"uploaded {target.name}")
        ui.notify(f"Uploaded to {target.relative_to(self.wb.root)}")
        self.cwd = upload_dir
        self.refresh()
        if target.suffix.lower() in DATA_SUFFIXES:
            await self.load(target)


# ---------------------------------------------------------------------------------- analyses
class AnalysesView:
    def __init__(self, wb: Workbench) -> None:
        self.wb = wb

    def build(self) -> None:
        with ui.column().classes("w-full gap-0"):
            for category, title in CATEGORIES.items():
                _section(title.upper())
                for cmd in commands(category):
                    with ui.item(on_click=lambda name=cmd.name: self.wb.launch(name)) \
                            .props("dense clickable").classes("w-full q-px-sm"):
                        with ui.item_section():
                            ui.item_label(f"/{cmd.name}").classes("text-body2 text-weight-medium")
                            ui.item_label(cmd.description).props("caption lines=2")
            _section("TEST SIGNALS")
            for kind, text in (("sine", "Sine of an ideal N-bit digitizer"),
                               ("noise", "Random noise of an ideal N-bit digitizer")):
                with ui.item(on_click=lambda kind=kind: self.wb.new_test_signal(kind)) \
                        .props("dense clickable").classes("w-full q-px-sm"):
                    with ui.item_section():
                        ui.item_label(f"/make_{kind}").classes("text-body2 text-weight-medium")
                        ui.item_label(text).props("caption")
            _section("SCRIPTS")
            ui.button("Open the Scripts view", icon="code",
                      on_click=lambda: self.wb.show_view("scripts")).props("flat dense no-caps")


# ---------------------------------------------------------------------------------- scripts
class ScriptsView:
    """Scripts of ``scripts/`` (§8.4) and batches (§8.5)."""

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb

    def build(self) -> None:
        with ui.column().classes("w-full gap-0"):
            with ui.row().classes("w-full q-px-sm"):
                ui.button("New script", icon="add", on_click=self.new).props("flat dense no-caps")
                ui.button(icon="refresh", on_click=self.refresh).props("flat dense round size=sm")
            self.box = ui.column().classes("w-full gap-0")
            _section("BATCH")
            with ui.row().classes("w-full q-px-sm"):
                ui.button("New batch…", icon="dynamic_feed",
                          on_click=lambda: self.wb.new_batch()).props("flat dense no-caps") \
                    .tooltip("Run an analysis or a script on many files")
            self.batches = ui.column().classes("w-full gap-0")
        self.refresh()

    def refresh_batches(self) -> None:
        self.batches.clear()
        with self.batches:
            for run in reversed(self.wb.state.batches):
                with ui.item(on_click=lambda i=run.id: self.wb.open_batch(i)) \
                        .props("dense clickable").classes("w-full q-px-sm"):
                    with ui.item_section():
                        ui.item_label(f"{run.title} · {' '.join(run.settings.patterns)}") \
                            .classes("text-body2 ots-ellipsis")
                        ui.item_label(f"{run.state} · {run.done}/{run.total} files · "
                                      f"{len(run.rows)} signal(s), {run.failures} failure(s)") \
                            .props("caption")

    def refresh(self) -> None:
        from ...scripts import list_scripts, script_path

        self.refresh_batches()
        self.box.clear()
        with self.box:
            scripts = list_scripts()
            if not scripts:
                ui.label("No script in scripts/ yet.").classes("text-caption text-grey-7 q-pa-sm")
            for name, description in scripts:
                with ui.item().props("dense").classes("w-full q-px-sm"):
                    with ui.item_section():
                        ui.item_label(name).classes("text-body2 text-weight-medium")
                        ui.item_label(description).props("caption lines=2")
                    with ui.item_section().props("side"):
                        with ui.row().classes("gap-0"):
                            ui.button(icon="edit", on_click=lambda n=name: self.wb.open_file(
                                script_path(n))).props("flat dense round size=sm").tooltip("Edit")
                            if self.wb.state.code_execution:
                                ui.button(icon="play_arrow", on_click=lambda n=name: self.wb
                                          .run_script(n)).props("flat dense round size=sm") \
                                    .tooltip("Run")

    async def new(self) -> None:
        from ...scripts import create_script

        name = await ask_text("New script", "Script name (letters, digits, underscores)",
                              "my_analysis", "Create")
        if not name:
            return
        try:
            path = create_script(name)
        except ParameterError as exc:
            ui.notify(str(exc), type="negative")
            return
        self.refresh()
        self.wb.open_file(path)


# ---------------------------------------------------------------------------------- reports
class ReportsView:
    def __init__(self, wb: Workbench) -> None:
        self.wb = wb

    def build(self) -> None:
        with ui.column().classes("w-full gap-1 q-px-sm"):
            _section("BASKET")
            self.basket = ui.column().classes("w-full gap-0")
            self.title = ui.input("Title", placeholder="title of the first result") \
                .props("dense outlined").classes("w-full")
            self.author = ui.input("Author", value=str(self.wb.state.config.get(
                "report.author", ""))).props("dense outlined").classes("w-full")
            self.formats = ui.select({"html": "HTML", "pdf": "PDF"}, value=["html", "pdf"],
                                     multiple=True, label="Formats").props("dense outlined") \
                .classes("w-full")
            self.render_now = ui.checkbox("Render with Quarto after generation", value=True)
            ui.button("Generate the report", icon="article", on_click=self.generate) \
                .props("unelevated dense no-caps").classes("w-full")
            _section("REPORTS")
            self.existing = ui.column().classes("w-full gap-0")
        self.refresh()

    def refresh(self) -> None:
        session = self.wb.state.session
        self.basket.clear()
        with self.basket:
            if not self.wb.state.report_basket:
                ui.label("Add results with “Add to report”.").classes("text-caption text-grey-7")
            for i, name in enumerate(list(self.wb.state.report_basket)):
                try:
                    r = session.get_result(name)
                except ParameterError:
                    continue
                with ui.row().classes("w-full items-center no-wrap gap-0"):
                    ui.label(f"{name} · {r.kind}").classes("text-body2 grow ellipsis")
                    ui.button(icon="arrow_upward", on_click=lambda i=i: self.move(i, -1)) \
                        .props("flat dense round size=xs")
                    ui.button(icon="close", on_click=lambda n=name: self.remove(n)) \
                        .props("flat dense round size=xs")
        self.existing.clear()
        reports = self.wb.reports_dir
        with self.existing:
            folders = sorted((p for p in reports.iterdir() if p.is_dir()), reverse=True) \
                if reports.exists() else []
            if not folders:
                ui.label("No report yet.").classes("text-caption text-grey-7")
            for folder in folders[:30]:
                qmd = folder / "report.qmd"
                with ui.item().props("dense").classes("w-full q-px-none"):
                    with ui.item_section():
                        ui.item_label(folder.name).classes("text-body2 ots-ellipsis") \
                            .tooltip(folder.name)
                    with ui.item_section().props("side"):
                        with ui.row().classes("gap-0"):
                            if qmd.exists():
                                ui.button(icon="edit",
                                          on_click=lambda q=qmd: self.wb.open_file(q)) \
                                    .props("flat dense round size=xs").tooltip("Edit report.qmd")
                                ui.button(icon="picture_as_pdf",
                                          on_click=lambda q=qmd: self.wb.render_report(q)) \
                                    .props("flat dense round size=xs").tooltip("Render")
                            if (folder / "report.html").exists():
                                ui.button(icon="visibility",
                                          on_click=lambda f=folder: self.wb.preview_report(f)) \
                                    .props("flat dense round size=xs").tooltip("Preview")
                            if (folder / "report.pdf").exists():
                                ui.button(icon="download", on_click=lambda f=folder:
                                          ui.download.file(f / "report.pdf")) \
                                    .props("flat dense round size=xs").tooltip("PDF")

    def move(self, i: int, delta: int) -> None:
        basket = self.wb.state.report_basket
        j = i + delta
        if 0 <= j < len(basket):
            basket[i], basket[j] = basket[j], basket[i]
        self.refresh()

    def remove(self, name: str) -> None:
        if name in self.wb.state.report_basket:
            self.wb.state.report_basket.remove(name)
        self.refresh()

    def generate(self) -> None:
        from ...report import generate_report

        session = self.wb.state.session
        names = list(self.wb.state.report_basket)
        if not names:
            ui.notify("The basket is empty: use “Add to report” on results", type="warning")
            return
        results = [session.get_result(n) for n in names]
        title = self.title.value or None
        formats = list(self.formats.value or ["html"])
        render = bool(self.render_now.value)

        def work(job: Any) -> Any:
            path = generate_report(results, title=title, formats=formats, render=False,
                                   author=self.author.value or None,
                                   output_dir=self.wb.reports_dir)
            if render:
                from ...report import render_report

                job.message = "rendering with Quarto"
                render_report(Path(path), formats)
            return path

        def done(job: Any) -> None:
            self.wb.report_failure(job)
            self.wb.state.to_origin({"type": "reports"})

        self.wb.state.jobs.start("report", work, kind="report", client=self.wb.id,
                                 on_done=done)
        ui.notify("Generating the report…")


# ---------------------------------------------------------------------------------- SeedLink
class StreamPicker:
    """Server, station and channel choice shared by the acquisition and real-time views."""

    def __init__(self, wb: Workbench, on_listed: Any = None) -> None:
        self.wb = wb
        self.streams: list[tuple[str, str, str, str]] = []
        self.checks: dict[str, Any] = {}
        self.on_listed = on_listed

    def build(self) -> None:
        cfg = self.wb.state.config
        self.server = ui.input("Server", value=str(cfg.get("seedlink.server", ""))) \
            .props("dense outlined").classes("w-full")
        with ui.row().classes("w-full no-wrap gap-1"):
            self.port = ui.number("Port", value=int(cfg.get("seedlink.port", 18000)),
                                  format="%d").props("dense outlined").classes("w-24")
            self.network = ui.input("Network", value=str(cfg.get("seedlink.network", ""))) \
                .props("dense outlined").classes("grow")
            self.station = ui.input("Station", value=str(cfg.get("seedlink.station", ""))) \
                .props("dense outlined").classes("grow")
        with ui.row().classes("w-full items-center no-wrap gap-1"):
            ui.button("List streams", icon="list", on_click=self.list_streams) \
                .props("flat dense no-caps")
            self.pattern = ui.input(placeholder="filter, e.g. FH? or 00.HH?",
                                    on_change=lambda _: self.refresh()) \
                .props("dense outlined clearable").classes("grow")
        with ui.row().classes("w-full gap-1"):
            ui.button("All", on_click=lambda: self.check_all(True)).props("flat dense no-caps")
            ui.button("None", on_click=lambda: self.check_all(False)).props("flat dense no-caps")
        self.box = ui.column().classes("w-full gap-0 max-h-64 overflow-auto")

    @property
    def port_value(self) -> int:
        return int(self.port.value or 18000)

    def list_streams(self) -> None:
        server, port = self.server.value, self.port_value
        network, station = self.network.value or None, self.station.value or None
        if not server:
            ui.notify("Give the SeedLink server", type="warning")
            return

        def work(job: Any) -> Any:
            return self.wb.state.list_streams(server, port, network, station)

        def done(job: Any) -> None:
            if job.state == "done":
                self.streams = job.result
            self.wb.report_failure(job)
            self.wb.state.to_origin({"type": "streams"})

        self.wb.state.jobs.start("INFO STREAMS", work, kind="seedlink", client=self.wb.id,
                                 on_done=done)

    def _visible(self) -> list[tuple[str, str, str, str]]:
        from ...seedlink.client import filter_streams

        pattern = (self.pattern.value or "").strip()
        if not pattern:
            return list(self.streams)
        return filter_streams(self.streams, pattern.replace(",", " ").split())

    def refresh(self) -> None:
        previous = {sid for sid, box in self.checks.items() if box.value}
        self.box.clear()
        self.checks = {}
        with self.box:
            visible = self._visible()
            if self.streams and not visible:
                ui.label("No stream matches the filter").classes("text-caption text-grey-7")
            for s in visible:
                sid = ".".join(s)
                self.checks[sid] = ui.checkbox(sid, value=sid in previous).props("dense")
        if self.on_listed is not None:
            self.on_listed()

    def check_all(self, value: bool) -> None:
        for box in self.checks.values():
            box.value = value

    def chosen(self) -> list[tuple[str, str, str, str]]:
        return [s for s in self.streams
                if ".".join(s) in self.checks and self.checks[".".join(s)].value]


class AcquisitionView:
    """SeedLink acquisition with live progress (§8.1).

    The acquisition belongs to the server (``WebState.acquisition``): it goes on when the
    browser is closed, and a reloaded page shows its progress again (W-12).
    """

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb

    def build(self) -> None:
        with ui.column().classes("w-full gap-1 q-px-sm"):
            self.picker = StreamPicker(self.wb)
            self.picker.build()
            with ui.row().classes("w-full no-wrap gap-1"):
                self.duration = ui.number("Duration (s)", value=60, min=1) \
                    .props("dense outlined").classes("grow")
                self.outdir = ui.input("Folder", value="data").props("dense outlined") \
                    .classes("grow")
            self.load = ui.checkbox("Load the signals at the end", value=True)
            with ui.row().classes("w-full gap-1"):
                self.start_button = ui.button("Start", icon="fiber_manual_record",
                                              on_click=self.start).props("unelevated dense")
                self.stop_button = ui.button("Stop", icon="stop", on_click=self.stop) \
                    .props("flat dense")
            self.progress = ui.column().classes("w-full gap-0")
        ui.timer(0.5, self.show_progress)

    def refresh(self) -> None:
        self.picker.refresh()

    def start(self) -> None:
        chosen = self.picker.chosen()
        if not chosen:
            ui.notify("List the streams and choose at least one", type="warning")
            return
        try:
            outdir = confine(self.outdir.value or ".", self.wb.roots)
            outdir.mkdir(parents=True, exist_ok=True)
            self.wb.state.start_acquisition(self.picker.server.value, chosen,
                                            self.picker.port_value,
                                            float(self.duration.value or 60), outdir,
                                            bool(self.load.value), client=self.wb.id)
        except (ParameterError, PermissionError, OSError) as exc:
            ui.notify(str(exc), type="warning")

    def stop(self) -> None:
        if self.wb.state.acquisition is not None:
            self.wb.state.acquisition.stop()

    def show_progress(self) -> None:
        snap = self.wb.state.acquisition_progress
        running = self.wb.state.acquisition is not None
        self.start_button.set_enabled(not running)
        self.stop_button.set_enabled(running)
        self.progress.clear()
        if snap is None:
            return
        with self.progress:
            ui.linear_progress(value=float(snap.fraction or 0.0), show_value=False) \
                .classes("w-full")
            ui.label(f"{snap.state} · {snap.elapsed:.0f} s · {_size(snap.bytes_written)}"
                     + (f" · {snap.message}" if snap.message else "")) \
                .classes("text-caption text-grey-8")
            for sid, st in snap.channels.items():
                latency = st.latency()
                rate = st.effective_rate()
                last = str(st.last_time)[11:23] if st.last_time else "—"
                ui.label(f"{sid}: {st.samples} samples · last {last} · latency "
                         f"{'—' if latency is None else f'{latency:.1f} s'} · gaps {st.gaps} · "
                         f"{'—' if rate is None else f'{rate:.2f} Hz'}").classes("text-caption")


# ---------------------------------------------------------------------------------- real time
class RealtimeView:
    """Settings of the real-time dashboard (§8.2); the dashboard itself is a tab."""

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb

    def build(self) -> None:
        with ui.column().classes("w-full gap-1 q-px-sm"):
            self.picker = StreamPicker(self.wb)
            self.picker.build()
            with ui.row().classes("w-full no-wrap gap-1"):
                self.window = ui.number("Statistics window (s)", value=10, min=0.1) \
                    .props("dense outlined").classes("grow")
                self.spectral = ui.number("FFT / PSD window (s)", value=60, min=1) \
                    .props("dense outlined").classes("grow")
            with ui.row().classes("w-full no-wrap gap-1"):
                self.trace = ui.number("Trace shown (s)", value=30, min=1) \
                    .props("dense outlined").classes("grow")
                self.refresh_s = ui.number("Refresh (s)", value=1, min=0.2) \
                    .props("dense outlined").classes("grow")
                self.spectra_s = ui.number("Spectra refresh (s)", value=2, min=0.5) \
                    .props("dense outlined").classes("grow")
            with ui.row().classes("w-full no-wrap gap-1"):
                self.sensitivity = ui.input("Sensitivity (unit per count)",
                                            placeholder="none: counts only") \
                    .props('dense outlined hint="e.g. 40 / 2**24"').classes("grow")
                self.unit = ui.input("Unit", value="V").props("dense outlined").classes("w-20")
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                self.record = ui.switch("Record to miniSEED in", value=False)
                self.record_dir = ui.input(value="data/realtime").props("dense outlined") \
                    .classes("grow")
            with ui.row().classes("w-full gap-1"):
                self.start_button = ui.button("Start", icon="play_arrow", on_click=self.start) \
                    .props("unelevated dense")
                self.stop_button = ui.button("Stop", icon="stop", on_click=self.stop) \
                    .props("flat dense")
                ui.button("Dashboard", icon="monitor_heart",
                          on_click=self.wb.open_realtime).props("flat dense no-caps")
            self.status = ui.label("").classes("text-caption text-grey-8")
        ui.timer(0.5, self.show_state)

    def refresh(self) -> None:
        self.picker.refresh()

    def _sensitivity(self) -> float | None:
        from ...core.params import safe_eval

        text = (self.sensitivity.value or "").strip()
        return float(safe_eval(text)) if text else None

    def start(self) -> None:
        from ..realtime import RealtimeSettings

        chosen = self.picker.chosen()
        if not chosen:
            ui.notify("List the streams and choose at least one", type="warning")
            return
        try:
            record = None
            if self.record.value:
                record = confine(self.record_dir.value or "data/realtime", self.wb.roots)
            settings = RealtimeSettings(
                self.picker.server.value, chosen, self.picker.port_value,
                window=float(self.window.value or 10),
                spectral_window=float(self.spectral.value or 60),
                trace_seconds=float(self.trace.value or 30),
                refresh=float(self.refresh_s.value or 1),
                spectra_refresh=float(self.spectra_s.value or 2),
                sensitivity=self._sensitivity(), unit=self.unit.value or "V",
                record_dir=record)
            self.wb.state.start_realtime(settings, client=self.wb.id)
        except (ParameterError, PermissionError, ValueError) as exc:
            ui.notify(str(exc), type="warning")
            return
        self.wb.open_realtime()

    def stop(self) -> None:
        run = self.wb.state.realtime
        if run is not None:
            run.stop()

    def show_state(self) -> None:
        run = self.wb.state.realtime
        running = run is not None and run.running
        self.start_button.set_enabled(not running)
        self.stop_button.set_enabled(running)
        if run is None:
            self.status.text = ""
        else:
            self.status.text = (f"{run.state} · {len(run.ids)} channel(s)"
                                + (" · recording" if run.recording else "")
                                + (f" · {run.error}" if run.error else ""))


# ---------------------------------------------------------------------------------- settings
ORIGIN_COLORS = {"session": "orange-8", "project": "blue-8", "global": "teal-8",
                 "given": "grey-7", "default": "grey-5", "unknown": "red-7"}


def parse_value(text: str, current: Any = None) -> Any:
    """A value typed in the Settings view: TOML literal (``8090``, ``true``, ``["."]``), else
    text."""
    import tomllib

    try:
        return tomllib.loads(f"value = {text}")["value"]
    except tomllib.TOMLDecodeError:
        return text


class SettingsView:
    """Configuration with the origin of each value (§13): default, global file, project file,
    session. A value can be changed for the session; the project file opens in the editor."""

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb

    def build(self) -> None:
        with ui.column().classes("w-full gap-1 q-px-sm"):
            with ui.row().classes("w-full gap-1"):
                ui.button("Edit onthesignal.toml", icon="edit", on_click=self.edit) \
                    .props("flat dense no-caps")
                ui.button(icon="refresh", on_click=self.reload).props("flat dense round size=sm") \
                    .tooltip("Read the configuration files again")
            with ui.row().classes("w-full gap-1 items-center"):
                for origin in ("default", "global", "project", "session"):
                    ui.badge(origin, color=ORIGIN_COLORS[origin]).props("outline")
            ui.label("Click a value to change it for this session only.") \
                .classes("text-caption text-grey-7")
            self.box = ui.column().classes("w-full gap-0")
        self.refresh()

    def refresh(self) -> None:
        config = self.wb.state.config
        self.box.clear()
        with self.box:
            sources = ", ".join(str(s) for s in config.sources) or "defaults only"
            ui.label(f"Files: {sources}").classes("text-caption text-grey-7")
            unknown = config.unknown_keys()
            if unknown:
                with ui.row().classes("w-full no-wrap items-start gap-1 q-pa-xs bg-amber-1 "
                                      "rounded"):
                    ui.icon("warning", color="amber-9", size="18px")
                    ui.label(f"Ignored keys (not read by onthesignal): {', '.join(unknown)}") \
                        .classes("text-caption text-grey-9")
            sections: dict[str, list[tuple[str, Any, str]]] = {}
            for key, value, origin in config.items():
                section, _, name = key.partition(".")
                sections.setdefault(section, []).append((name or section, value, origin))
            for section, rows in sections.items():
                changed = sum(1 for _, _, o in rows if o not in ("default",))
                with ui.expansion(f"[{section}]" + (f" · {changed} set" if changed else "")) \
                        .props("dense").classes("w-full"):
                    for name, value, origin in rows:
                        self._row(f"{section}.{name}" if name != section else section, name,
                                  value, origin)

    def _row(self, key: str, name: str, value: Any, origin: str) -> None:
        with ui.row().classes("w-full no-wrap items-center gap-1"):
            ui.label(name).classes("text-caption text-grey-8 w-32 ots-ellipsis").tooltip(key)
            shown = repr(value) if not isinstance(value, str) else f'"{value}"'
            ui.label(shown).classes("text-caption grow ots-ellipsis cursor-pointer") \
                .tooltip(shown).on("click", lambda key=key, value=value: self.change(key, value))
            ui.badge(origin, color=ORIGIN_COLORS.get(origin, "grey-7")).props("outline")

    async def change(self, key: str, value: Any) -> None:
        import json

        text = json.dumps(value) if not isinstance(value, str) else f'"{value}"'
        answer = await ask_text(f"Change {key} for this session",
                                "Value (TOML: 8090, true, \"text\", [\".\"])", text, "Apply")
        if answer is None:
            return
        self.wb.state.config.set(key, parse_value(answer, value))
        self.wb.state.log("config", f"{key} = {answer} (session)")
        ui.notify(f"{key} changed for this session")
        self.refresh()

    def reload(self) -> None:
        try:
            self.wb.state.config.reload()
        except ParameterError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return
        ui.notify("Configuration read again (the session changes are kept)")
        self.refresh()

    def edit(self) -> None:
        path = self.wb.root / "onthesignal.toml"
        if not path.exists():
            path.write_text("# onthesignal project configuration\n", encoding="utf-8")
        self.wb.open_file(path)


# ---------------------------------------------------------------------------------- help
SHORTCUTS = [("/ or Ctrl+K", "command palette"), ("Ctrl+P", "open a file or an object"),
             ("Ctrl+Enter", "run the open form"), ("Ctrl+S", "save the file"),
             ("F5", "run the open script"), ("Shift+Enter", "run the selection in the terminal"),
             ("Ctrl+`", "show or hide the Python terminal"),
             ("Ctrl+Shift+I", "show or hide the chat"),
             ("Drag", "zoom on a rectangle (Zoom mode) or move (Move mode) on a chart"),
             ("Middle drag, Shift+wheel", "move along the abscissa of a chart"),
             ("Ctrl+wheel", "zoom a chart around the cursor"),
             ("Chart toolbar", "full view, previous and next view, Zoom and Move modes"),
             ("Shift+drag", "select a time window on a plot"), ("Double-click", "full view"),
             ("Check boxes, Ctrl+click", "several signals (overlay, stack) or results "
              "(compare)")]


class HelpView:
    def __init__(self, wb: Workbench) -> None:
        self.wb = wb

    def build(self) -> None:
        from ...cli.commands import SLASH

        with ui.column().classes("w-full gap-0 q-px-sm"):
            if self.wb.docs_url:
                ui.link("Documentation (user manual, algorithms)", self.wb.docs_url,
                        new_tab=True).classes("text-body2 q-py-xs")
            _section("SHORTCUTS")
            for key, text in SHORTCUTS:
                with ui.row().classes("w-full no-wrap gap-2"):
                    ui.label(key).classes("text-caption text-weight-medium w-28")
                    ui.label(text).classes("text-caption text-grey-8")
            _section("ANALYSES")
            for cmd in commands():
                ui.label(f"/{cmd.name} — {cmd.description}").classes("text-caption")
            _section("CONSOLE COMMANDS (Python terminal)")
            for s in sorted(SLASH.values(), key=lambda s: s.name):
                ui.label(f"{s.usage} — {s.description}").classes("text-caption")


__all__ = ["AcquisitionView", "AnalysesView", "FilesView", "HelpView", "RealtimeView",
           "ReportsView", "ScriptsView", "SettingsView", "StreamPicker"]
