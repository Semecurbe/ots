"""Dialogs: analysis launcher, test signals, script run, file loading, simple questions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nicegui import ui

from ...core.errors import ParameterError
from ...core.params import Param, param_origins, resolve_params
from ...core.registry import commands, get_command
from ..forms import ParamForm

if TYPE_CHECKING:
    from .workbench import Workbench


async def ask_text(title: str, label: str, value: str = "", ok: str = "OK") -> str | None:
    """One-line question; ``None`` when cancelled."""
    with ui.dialog() as dialog, ui.card().classes("min-w-[420px]"):
        ui.label(title).classes("text-subtitle1 text-weight-medium")
        field = ui.input(label, value=value).props("autofocus dense outlined").classes("w-full")
        field.on("keydown.enter", lambda: dialog.submit(field.value))
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button(ok, on_click=lambda: dialog.submit(field.value)).props("unelevated")
    dialog.open()
    answer = await dialog
    dialog.delete()
    return answer


async def confirm(title: str, text: str = "", ok: str = "OK") -> bool:
    with ui.dialog() as dialog, ui.card().classes("min-w-[380px]"):
        ui.label(title).classes("text-subtitle1 text-weight-medium")
        if text:
            ui.label(text).classes("text-body2 text-grey-8")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button(ok, on_click=lambda: dialog.submit(True)).props("unelevated")
    dialog.open()
    answer = await dialog
    dialog.delete()
    return bool(answer)


async def param_dialog(title: str, subtitle: str, params: list[Param], defaults: dict[str, Any],
                       origins: dict[str, str] | None = None, run_label: str = "Run",
                       signal_selects: int = 0, signal_names: list[str] | None = None,
                       chosen: list[str] | None = None, signal_params: tuple[str, ...] = (),
                       defaults_for: Any = None, preset: dict | None = None) -> dict | None:
    """Generic parameter dialog; returns ``{"signals": [...], "params": {...}}`` or None.

    ``defaults_for(signal_name) -> (defaults, origins)`` recomputes the defaults when the
    first selected signal changes (parameters taken from the signal, such as full_scale).
    """
    signal_names = signal_names or []
    holder: dict[str, Any] = {}
    with ui.dialog() as dialog, ui.card().classes("w-[640px] max-w-[92vw]"):
        ui.label(title).classes("text-h6")
        if subtitle:
            ui.label(subtitle).classes("text-body2 text-grey-8")
        selects = []
        for i in range(signal_selects):
            value = (chosen or [])[i] if chosen and i < len(chosen) else (
                signal_names[min(i, len(signal_names) - 1)] if signal_names else None)
            label = "Signal" if signal_selects == 1 else f"Signal {i + 1}"
            selects.append(ui.select(signal_names, value=value, label=label)
                           .props("dense outlined").classes("w-full"))
        box = ui.column().classes("w-full")

        def rebuild() -> None:
            box.clear()
            d, o = defaults, origins
            if defaults_for is not None and selects and selects[0].value:
                try:
                    d, o = defaults_for(selects[0].value)
                except ParameterError as exc:
                    ui.notify(str(exc), type="warning")
            form = ParamForm(params, d, o, signal_params, signal_names, preset)
            with box:
                form.build()
            holder["form"] = form

        rebuild()
        if selects and defaults_for is not None:
            selects[0].on_value_change(lambda _: rebuild())

        def run() -> None:
            try:
                values = holder["form"].values()
            except ParameterError as exc:
                ui.notify(str(exc), type="negative")
                return
            names = [s.value for s in selects]
            if any(not n for n in names):
                ui.notify("Choose the signal(s)", type="warning")
                return
            dialog.submit({"signals": names, "params": values})

        with ui.row().classes("w-full justify-end items-center"):
            ui.label("Ctrl+Enter").classes("text-xs text-grey-6")
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button(run_label, icon="play_arrow", on_click=run).props("unelevated")
        dialog.on("keydown.ctrl.enter", run)
    dialog.open()
    answer = await dialog
    dialog.delete()
    return answer


# ---------------------------------------------------------------------------------- analyses
async def launch_analysis(wb: Workbench, name: str, signals: list[str] | None = None,
                          request: int | None = None) -> None:
    """Launcher of a registered analysis (§7.1); also answers terminal form requests."""
    session = wb.state.session
    cmd = get_command(name)
    names = list(session.signals)
    if not names:
        ui.notify("Load a signal first (Files view, Upload, or the Python terminal)",
                  type="warning")
        if request is not None:
            wb.state.requests.answer(request, None)
        return
    chosen = list(signals or [])
    active = wb.active_signal()
    if not chosen and active:
        chosen = [active]
    declared = [p for p in cmd.params if p.name != "report"]

    def defaults_for(signal_name: str) -> tuple[dict, dict]:
        sig = session.get_signal(signal_name)
        return (resolve_params(declared, {}, sig, session.config, cmd.name),
                param_origins(declared, {}, sig, session.config))

    first = chosen[0] if chosen else names[-1]
    d, o = defaults_for(first)
    preset = None
    window = getattr(wb, "pending_window", None)
    if window and {"t_start", "t_end"} <= {p.name for p in declared}:
        preset = {"t_start": window[0], "t_end": window[1]}
    answer = await param_dialog(f"/{cmd.name}", cmd.description, list(cmd.params), d, o,
                                signal_selects=cmd.n_signals, signal_names=names,
                                chosen=chosen or [first], signal_params=cmd.signal_params,
                                defaults_for=defaults_for, preset=preset)
    if request is not None:
        wb.state.requests.answer(request, None if answer is None else answer["params"])
        return
    if answer is not None:
        wb.run_analysis(cmd.name, answer["signals"], answer["params"])


async def new_test_signal(wb: Workbench, kind: str = "sine") -> None:
    from ... import api
    from ...synthetic import NOISE_PARAMS, SINE_PARAMS

    params = list(SINE_PARAMS if kind == "sine" else NOISE_PARAMS)
    defaults = {p.name: p.default for p in params}
    answer = await param_dialog(f"New test {kind}", "Ideal N-bit digitizer (§5.1 of the v2 "
                                "specification)", params, defaults, run_label="Create")
    if answer is None:
        return
    func = api.make_sine if kind == "sine" else api.make_noise

    def work(job: Any) -> Any:
        sig = func(**answer["params"])
        wb.state.to_origin({"type": "open", "what": "signal", "name": sig.name})
        return sig

    wb.state.jobs.start(f"make_{kind}", work, kind="signal", client=wb.id,
                        on_done=wb.report_failure)


async def run_script_dialog(wb: Workbench, name: str) -> None:
    from ...scripts import load_script, run_script

    session = wb.state.session
    try:
        script = load_script(name)
    except ParameterError as exc:
        ui.notify(str(exc), type="negative")
        return
    names = list(session.signals)
    if not names:
        ui.notify("Load a signal first", type="warning")
        return

    def defaults_for(signal_name: str) -> tuple[dict, dict]:
        sig = session.get_signal(signal_name)
        return (resolve_params(script.params, {}, sig, session.config, name),
                param_origins(script.params, {}, sig, session.config))

    active = wb.active_signal() or names[-1]
    d, o = defaults_for(active)
    answer = await param_dialog(f"Script {name}", script.description, list(script.params), d,
                                o, signal_selects=1, signal_names=names, chosen=[active],
                                defaults_for=defaults_for)
    if answer is None:
        return

    def work(job: Any) -> Any:
        return run_script(name, *answer["signals"], show=True, **answer["params"])

    wb.state.jobs.start(f"script {name}", work, kind="script", client=wb.id,
                        on_done=wb.report_failure)


# ---------------------------------------------------------------------------------- loading
def _load_params(names: tuple[str, ...]) -> list[Param]:
    from ...cli.commands import LOAD_OPTIONS

    return [p for p in LOAD_OPTIONS if p.name in names]


MSEED_OPTIONS = ("name", "title", "select", "gaps", "starttime", "endtime", "unit",
                 "sensitivity", "full_scale")
TEXT_OPTIONS = ("n_channels", "time_col", "fs", "delimiter", "decimal", "skiprows",
                "time_format", "name", "title", "unit", "sensitivity", "full_scale")


async def load_file_dialog(wb: Workbench, path: Path, options: bool = False) -> None:
    """Load a data file (§6.3): miniSEED directly or with options; text through the wizard."""
    from ...io import detect_format

    fmt = detect_format(path)
    values: dict[str, Any] = {}
    if fmt == "txt":
        answer = await text_wizard(path)
        if answer is None:
            return
        values = answer
    elif options:
        params = _load_params(MSEED_OPTIONS)
        answer = await param_dialog(f"Load {path.name}", "miniSEED options (gaps are never "
                                    "filled silently)", params,
                                    {p.name: p.default for p in params}, run_label="Load")
        if answer is None:
            return
        values = answer["params"]
    wb.load_files([path], values)


async def text_wizard(path: Path) -> dict | None:
    """Text file import with a preview of the first lines (v2 §6.2)."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = [next(fh, "") for _ in range(20)]
    except OSError as exc:
        ui.notify(str(exc), type="negative")
        return None
    params = _load_params(TEXT_OPTIONS)
    defaults = {p.name: p.default for p in params}
    defaults["n_channels"] = 1
    with ui.dialog() as dialog, ui.card().classes("w-[760px] max-w-[94vw]"):
        ui.label(f"Import {path.name}").classes("text-h6")
        ui.label("First lines of the file").classes("text-caption text-grey-7")
        ui.code("".join(head) or "(empty file)").classes("w-full text-xs max-h-48 overflow-auto")
        form = ParamForm(params, defaults)
        form.build()
        ui.label("Without a time column, the sampling rate is mandatory.") \
            .classes("text-caption text-grey-7")

        def done() -> None:
            try:
                values = form.values()
            except ParameterError as exc:
                ui.notify(str(exc), type="negative")
                return
            values.setdefault("n_channels", 1)
            dialog.submit(values)

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button("Load", icon="upload_file", on_click=done).props("unelevated")
    dialog.open()
    answer = await dialog
    dialog.delete()
    return answer


# ---------------------------------------------------------------------------------- batches
BATCH_READ_OPTIONS = ("select", "gaps", "unit", "sensitivity", "n_channels", "time_col", "fs")


def _batch_decl(target: str) -> list[Param]:
    """Parameters of a batch target: ``noise`` (analysis) or ``script:<name>``."""
    from ...scripts import load_script

    if target.startswith("script:"):
        return list(load_script(target[7:]).params)
    return [p for p in get_command(target).params if p.name != "report"]


async def batch_dialog(wb: Workbench, pattern: str | None = None) -> Any:
    """Form of a batch (§8.5); returns :class:`~onthesignal.web.batch.BatchSettings`."""
    from datetime import datetime

    from ...scripts import list_scripts
    from ..batch import BatchSettings

    config = wb.state.config
    targets = {c.name: f"/{c.name} — {c.description}" for c in commands() if c.n_signals == 1}
    for name, description in list_scripts():
        targets[f"script:{name}"] = f"script {name}" + (f" — {description}" if description else "")
    holder: dict[str, Any] = {}
    with ui.dialog() as dialog, ui.card().classes("w-[680px] max-w-[94vw]"):
        ui.label("New batch").classes("text-h6")
        ui.label("Runs an analysis or a script on every signal of many files: one row per file "
                 "and signal; a failure is recorded and does not stop the batch.") \
            .classes("text-body2 text-grey-8")
        target = ui.select(targets, value="noise" if "noise" in targets else next(iter(targets)),
                           label="Analysis or script", with_input=True) \
            .props("dense outlined").classes("w-full")
        files = ui.input("Files (glob patterns of the project, separated by spaces)",
                         value=pattern or "data/*.mseed").props("dense outlined") \
            .classes("w-full")
        count = ui.label("").classes("text-caption text-grey-7")
        params_box = ui.column().classes("w-full gap-1")
        with ui.expansion("Reading options (files without metadata, text files)",
                          icon="upload_file").props("dense").classes("w-full"):
            read_params = _load_params(BATCH_READ_OPTIONS)
            read_form = ParamForm(read_params, {p.name: p.default for p in read_params})
            read_form.build()
        out = ui.input("Output table (.csv or .json; empty for none)",
                       value=f"results/batch_{datetime.now():%Y%m%d_%H%M}.csv") \
            .props("dense outlined").classes("w-full")

        def patterns() -> list[str]:
            return [p for p in (files.value or "").split() if p]

        def update_count() -> None:
            try:
                n = len(wb.state.confined_files(patterns()))
                count.text = f"{n} file(s) match"
            except ParameterError as exc:
                count.text = str(exc)

        def rebuild() -> None:
            params_box.clear()
            name = str(target.value or "")
            try:
                decl = _batch_decl(name)
            except ParameterError as exc:
                with params_box:
                    ui.label(str(exc)).classes("text-negative text-caption")
                holder.pop("form", None)
                return
            command = name[7:] if name.startswith("script:") else name
            form = ParamForm(decl, resolve_params(decl, {}, None, config, command),
                             param_origins(decl, {}, None, config))
            with params_box:
                ui.label("Parameters (resolved for each signal: signal attributes such as "
                         "full_scale apply)").classes("text-subtitle2")
                form.build()
            holder["form"] = form

        def run() -> None:
            form = holder.get("form")
            if form is None:
                ui.notify("Choose a valid analysis or script", type="warning")
                return
            try:
                params = form.values()
                read = read_form.values()
            except ParameterError as exc:
                ui.notify(str(exc), type="negative")
                return
            if not patterns():
                ui.notify("Give the files", type="warning")
                return
            name = str(target.value)
            dialog.submit(BatchSettings(name[7:] if name.startswith("script:") else name,
                                        patterns(), params, read, (out.value or "").strip()
                                        or None))

        target.on_value_change(lambda _: rebuild())
        files.on_value_change(lambda _: update_count())
        rebuild()
        update_count()
        with ui.row().classes("w-full justify-end items-center"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button("Run the batch", icon="play_arrow", on_click=run).props("unelevated")
    dialog.open()
    answer = await dialog
    dialog.delete()
    return answer


# ---------------------------------------------------------------------------------- comparison
async def compare_dialog(wb: Workbench, name: str) -> list[str] | None:
    """Choose the results of the same analysis to compare with ``name`` (§7.6)."""
    from ...plot.layouts import result_label

    session = wb.state.session
    base = session.get_result(name)
    others = [r for r in session.results if r.kind == base.kind and r.name != name]
    if not others:
        ui.notify(f"No other {base.kind} result to compare {name} with", type="warning")
        return None
    with ui.dialog() as dialog, ui.card().classes("min-w-[420px]"):
        ui.label(f"Compare {result_label(base)} ({base.kind}) with").classes("text-subtitle1")
        boxes = {r.name: ui.checkbox(f"{result_label(r)} — {r.title}", value=True)
                 .props("dense") for r in others}
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button("Compare", icon="compare_arrows", on_click=lambda: dialog.submit(
                [n for n, box in boxes.items() if box.value])).props("unelevated")
    dialog.open()
    answer = await dialog
    dialog.delete()
    return [name, *answer] if answer else None


__all__ = ["ask_text", "batch_dialog", "compare_dialog", "confirm", "launch_analysis",
           "load_file_dialog", "new_test_signal", "param_dialog", "run_script_dialog",
           "text_wizard"]
