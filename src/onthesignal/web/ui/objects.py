"""Objects panel: every object of the session, displayed with one click (§6.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

from ...core.session import format_duration
from ...core.units import COUNTS, pretty_unit
from ...plot.layouts import figure_spec

if TYPE_CHECKING:
    from .workbench import Workbench


def _headline(result: Any) -> str:
    """First key figure of a result (``RMS 2.43 µV``)."""
    try:
        keys = figure_spec(result).results.headline
    except Exception:  # a broken script result must not break the panel
        keys = []
    for key in keys or list(result.values)[:1]:
        if key in result.values:
            value = result.values[key]
            phys = result.values.get(key + "_phys")
            return f"{value.label} {(phys or value).text()}"
    return ""


class ObjectsPanel:
    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.filter = ""
        self.selected: set[str] = set()

    def build(self) -> None:
        with ui.column().classes("w-full h-full gap-0"):
            with ui.row().classes("w-full items-center no-wrap q-px-sm q-py-xs gap-1"):
                ui.label("OBJECTS").classes("text-caption text-weight-bold text-grey-8")
                ui.input(placeholder="filter", on_change=lambda e: self._set_filter(e.value)) \
                    .props("dense borderless clearable").classes("grow text-xs")
                with ui.button(icon="add").props("flat dense round size=sm"):
                    with ui.menu():
                        ui.menu_item("Load a file…", lambda: self.wb.show_view("files"))
                        ui.menu_item("Upload…", lambda: self.wb.show_view("files"))
                        ui.menu_item("New test sine…", lambda: self.wb.new_test_signal("sine"))
                        ui.menu_item("New test noise…", lambda: self.wb.new_test_signal("noise"))
                        ui.menu_item("New signal from expression…", self.wb.signal_expression)
            # Actions on the checked objects (several signals in one plot, comparison).
            with ui.row().classes("w-full items-center no-wrap gap-0 q-px-sm bg-blue-1") \
                    as self.actions:
                self.selection_label = ui.label("").classes("text-caption text-grey-9 grow")
                self.overlay = ui.button("Overlay", icon="stacked_line_chart",
                                         on_click=lambda: self._plot_selected(True)) \
                    .props("flat dense no-caps size=sm") \
                    .tooltip("Plot the checked signals in one panel")
                self.stack = ui.button("Stack", icon="view_agenda",
                                       on_click=lambda: self._plot_selected(False)) \
                    .props("flat dense no-caps size=sm") \
                    .tooltip("One panel per checked signal, on a common time axis")
                self.compare = ui.button("Compare", icon="compare_arrows",
                                         on_click=self._compare_selected) \
                    .props("flat dense no-caps size=sm") \
                    .tooltip("Overlay the checked results of the same analysis")
                ui.button(icon="close", on_click=self._clear_selection) \
                    .props("flat dense round size=sm").tooltip("Uncheck everything")
            self.actions.set_visibility(False)
            self.box = ui.column().classes("w-full gap-0 overflow-auto grow")
        self.refresh()

    def _set_filter(self, value: str | None) -> None:
        self.filter = (value or "").lower()
        self.refresh()

    def _match(self, *texts: str) -> bool:
        return not self.filter or any(self.filter in t.lower() for t in texts)

    # ------------------------------------------------------------------ rows
    def _group(self, title: str, count: int) -> None:
        ui.label(f"{title} ({count})").classes(
            "text-caption text-weight-bold text-grey-7 q-px-sm q-pt-sm")

    def _row(self, key: str, name: str, subtitle: str, on_click: Any, menu: list[tuple],
             drag: str = "", active: bool = False, checkable: bool = False) -> None:
        classes = "w-full q-px-sm q-py-none cursor-pointer rounded-borders"
        if active or key in self.selected:
            classes += " bg-blue-1"
        item = ui.item().classes(classes).props("dense clickable")
        item.on("click", lambda e, key=key: self._clicked(e, key, on_click),
                ["ctrlKey", "metaKey"])
        if drag:
            item.props("draggable")
            item.on("dragstart", js_handler=(
                f"(e) => e.dataTransfer.setData('text/plain', {drag!r})"))
        with item:
            if checkable:
                with ui.item_section().props("side").classes("q-pr-xs"):
                    box = ui.checkbox(value=key in self.selected,
                                      on_change=lambda e, key=key: self._check(key, e.value)) \
                        .props("dense size=xs").tooltip("Check several signals to overlay them, "
                                                        "or results to compare them")
                    # Checking does not open the object.
                    box.on("click", js_handler="(e) => e.stopPropagation()")
            with ui.item_section():
                ui.item_label(name).classes("text-body2 text-weight-medium")
                if subtitle:
                    ui.item_label(subtitle).props("caption lines=1")
            with ui.context_menu():
                for label, action in menu:
                    ui.menu_item(label, action)

    def _clicked(self, e: Any, key: str, action: Any) -> None:
        args = e.args or {}
        if (args.get("ctrlKey") or args.get("metaKey")) and key.startswith(("signal:", "result:")):
            self.selected ^= {key}
            self._update_buttons()
            self.refresh()
            return
        action()

    def _check(self, key: str, value: bool) -> None:
        if value:
            self.selected.add(key)
        else:
            self.selected.discard(key)
        self._update_buttons()

    def _clear_selection(self) -> None:
        self.selected.clear()
        self._update_buttons()
        self.refresh()

    def _chosen(self, group: str) -> list[str]:
        """Selected names of a group (``signal`` or ``result``), in the order of the session."""
        session = self.wb.state.session
        names = list(session.signals) if group == "signal" else [r.name for r in session.results]
        return [n for n in names if f"{group}:{n}" in self.selected]

    def _update_buttons(self) -> None:
        signals, results = len(self._chosen("signal")), len(self._chosen("result"))
        parts = [f"{signals} signal{'s' if signals > 1 else ''}" if signals else "",
                 f"{results} result{'s' if results > 1 else ''}" if results else ""]
        self.selection_label.text = " · ".join(p for p in parts if p) + " checked"
        self.overlay.set_visibility(signals > 1)
        self.stack.set_visibility(signals > 1)
        self.compare.set_visibility(results > 1)
        self.actions.set_visibility(bool(signals or results))

    def _plot_selected(self, overlay: bool = True) -> None:
        names = self._chosen("signal")
        self.selected -= {f"signal:{n}" for n in names}
        self._update_buttons()
        self.wb.open_signal(*names, overlay=overlay)
        self.refresh()

    def _compare_selected(self) -> None:
        names = self._chosen("result")
        self.selected -= {f"result:{n}" for n in names}
        self._update_buttons()
        self.wb.open_compare(names)
        self.refresh()

    # ------------------------------------------------------------------ refresh
    def refresh(self) -> None:
        state, session = self.wb.state, self.wb.state.session
        active = self.wb.work.active() if hasattr(self.wb, "work") else None
        present = {f"signal:{n}" for n in session.signals} | \
            {f"result:{r.name}" for r in session.results}
        if self.selected - present:  # deleted objects leave the selection
            self.selected &= present
            self._update_buttons()
        self.box.clear()
        with self.box:
            signals = [(n, s) for n, s in session.signals.items()
                       if self._match(n, s.id, s.title)]
            self._group("SIGNALS", len(signals))
            for name, s in signals:
                unit = "counts" if s.unit == COUNTS else pretty_unit(s.unit)
                subtitle = (f"{s.title or s.id} · {s.sampling_rate:g} Hz · "
                            f"{format_duration(s.duration)} · {unit}")
                key = f"signal:{name}"
                self._row(key, name, subtitle, lambda name=name: self.wb.open_signal(name), [
                    ("Show", lambda name=name: self.wb.open_signal(name)),
                    ("Analyze…", lambda name=name: self.wb.choose_and_launch([name])),
                    ("Rename…", lambda name=name: self.wb.rename_signal(name)),
                    ("Copy name", lambda name=name: ui.clipboard.write(name)),
                    ("Export…", lambda name=name: self.wb.export_signal(name)),
                    ("Send to AI", lambda name=name: self.wb.chat.attach(f"@{name}")),
                    ("Delete", lambda name=name: self.wb.delete_signal(name)),
                ], drag=name, active=active == key, checkable=True)
            aliases: dict[int, list[str]] = {}
            for var, value in list(state.terminal.console.ns.items()):
                if hasattr(value, "kind") and hasattr(value, "values") and not var.startswith("_"):
                    aliases.setdefault(id(value), []).append(var)
            results = [r for r in session.results if self._match(r.name, r.kind, r.title)]
            self._group("RESULTS", len(results))
            for r in reversed(results):
                names = ", ".join(s.get("name", "") for s in r.signals)
                alias = [a for a in aliases.get(id(r), []) if a != r.name]
                label = r.name + (f" · {', '.join(alias)}" if alias else "")
                subtitle = f"{r.kind} {names} · {_headline(r)}"
                key = f"result:{r.name}"
                self._row(key, label, subtitle, lambda n=r.name: self.wb.open_result(n), [
                    ("Show", lambda n=r.name: self.wb.open_result(n)),
                    ("Compare with…", lambda n=r.name: self.wb.compare_with(n)),
                    ("Add to report", lambda n=r.name: self.wb.add_to_report(n)),
                    ("Copy name", lambda n=r.name: ui.clipboard.write(n)),
                    ("Ask AI about it", lambda r=r: self.wb.ask_ai_about(r)),
                    ("Delete", lambda n=r.name: self.wb.delete_result(n)),
                ], drag=r.name, active=active == key, checkable=True)
            figures = [f for f in state.figures if self._match(f.name, f.title)]
            if figures:
                self._group("FIGURES", len(figures))
                for f in reversed(figures):
                    key = f"figure:{f.name}"
                    self._row(key, f.name, f.title, lambda n=f.name: self.wb.open_figure(n), [
                        ("Show", lambda n=f.name: self.wb.open_figure(n)),
                        ("Delete", lambda n=f.name: self.wb.delete_figure(n)),
                    ], active=active == key)
            variables = [v for v in state.variables if self._match(v.name, v.type)]
            if variables:
                self._group("VARIABLES", len(variables))
                for v in variables:
                    key = f"variable:{v.name}"
                    self._row(key, v.name, f"{v.type} {v.summary}",
                              lambda n=v.name: self.wb.open_variable(n), [
                                  ("Show", lambda n=v.name: self.wb.open_variable(n)),
                                  ("Copy name", lambda n=v.name: ui.clipboard.write(n)),
                                  ("Delete (del)", lambda n=v.name: self.wb.state.terminal
                                   .submit(f"del {n}")),
                              ], drag=v.name, active=active == key)
            if not session.signals and not session.results:
                ui.label("No object yet: load a file (Files view), create a test signal (+) "
                         "or type in the Python terminal.") \
                    .classes("text-caption text-grey-7 q-pa-sm")


__all__ = ["ObjectsPanel"]
