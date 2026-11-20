"""Work area: tabs of signals, results, figures, variables, files and reports (§4.3)."""

from __future__ import annotations

import base64
import io
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from nicegui import run, ui
from obspy import UTCDateTime

from ...core.errors import ParameterError
from ...core.params import safe_eval
from ...core.result import Result
from ...core.units import CANONICAL_UNITS, fmt_num, normalize_unit, pretty_unit
from ...plot.layouts import comparison_spec, comparison_view, figure_specs, results_view
from ..components import MonacoEditor, UPlotChart, language_of
from ..figures import (
    DEFAULT_BINS,
    array_figure,
    figure_payload,
    palette,
    signal_figure,
    signal_payload,
    time_origin,
)
from ..security import confine

if TYPE_CHECKING:
    from .workbench import Workbench

UNITS = list(CANONICAL_UNITS)


# ---------------------------------------------------------------------------------- manager
class WorkArea:
    """Tabs of the work area; a tab is identified by a key such as ``signal:S1``."""

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.items: dict[str, dict[str, Any]] = {}

    def build(self) -> None:
        with ui.column().classes("w-full h-full gap-0"):
            self.tabs = ui.tabs(on_change=lambda _: self.wb.on_tab_change()) \
                .props("dense align=left no-caps inline-label outside-arrows mobile-arrows "
                       "active-color=primary indicator-color=primary") \
                .classes("w-full text-grey-8 bg-grey-1")
            self.panels = ui.tab_panels(self.tabs).props("keep-alive animated=false") \
                .classes("w-full grow overflow-auto")
            with self.panels:
                self.empty = ui.tab_panel("empty")
                with self.empty, ui.column().classes("w-full items-center q-pa-xl text-grey-7"):
                    ui.icon("insights", size="48px")
                    ui.label("Click an object of the Objects panel to display it.")
                    ui.label("Type / to search the commands, or use the Python terminal below.")
            self.tabs.set_value("empty")

    def open(self, key: str, title: str, builder: Callable[[], Any], icon: str = "") -> None:
        if key in self.items:
            self.tabs.set_value(key)
            return
        with self.tabs:
            tab = ui.tab(key, label=title, icon=icon or None)
            with tab:
                ui.icon("close", size="14px").classes("q-ml-sm text-grey-6 cursor-pointer") \
                    .on("click.stop", lambda key=key: self.close(key))
        with self.panels:
            panel = ui.tab_panel(key).classes("q-pa-sm")
            with panel:
                content = builder()
        self.items[key] = {"tab": tab, "panel": panel, "content": content, "title": title}
        self.tabs.set_value(key)

    def close(self, key: str) -> None:
        item = self.items.pop(key, None)
        if item is None:
            return
        closing = getattr(item["content"], "close", None)
        if callable(closing):
            closing()
        item["tab"].delete()
        item["panel"].delete()
        keys = list(self.items)
        self.tabs.set_value(keys[-1] if keys else "empty")

    def active(self) -> str | None:
        value = self.tabs.value
        return value if isinstance(value, str) and value in self.items else None

    def content(self, key: str) -> Any:
        item = self.items.get(key)
        return item["content"] if item else None

    def set_title(self, key: str, title: str) -> None:
        item = self.items.get(key)
        if item:
            item["tab"].props(f'label="{title}"')

    def refresh(self) -> None:
        """Session changed: let every tab update itself (removed signals close their tabs)."""
        for key in list(self.items):
            content = self.items[key]["content"]
            refresh = getattr(content, "refresh", None)
            if callable(refresh) and refresh() is False:
                self.close(key)


def _png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _copy(text: str) -> None:
    ui.clipboard.write(text)
    ui.notify(f"Copied: {text}", timeout=1200)


# ---------------------------------------------------------------------------------- signals
class SignalTab:
    """Time plot of one or several signals, statistics and properties below (§5.2, §6.2)."""

    def __init__(self, wb: Workbench, names: list[str]) -> None:
        self.wb = wb
        self.names = list(names)
        self.units = "physical"
        self.stacked = True
        self.window: tuple[float | None, float | None] = (None, None)
        self.selection: tuple[float, float] | None = None
        self.chart: UPlotChart | None = None
        self.versions = self._fingerprint()

    def signals(self) -> list[Any]:
        session = self.wb.state.session
        return [session.signals[n] for n in self.names if n in session.signals]

    def _fingerprint(self) -> tuple:
        return tuple((s.name, s.unit, s.sensitivity, s.full_scale, s.title, s.npts, id(s))
                     for s in self.signals())

    def build(self) -> SignalTab:
        with ui.column().classes("w-full gap-1"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.toggle({"physical": "Physical units", "counts": "Counts"}, value=self.units,
                          on_change=lambda e: self._set("units", e.value)).props("dense no-caps")
                if len(self.names) > 1:
                    ui.toggle({True: "Stacked", False: "Overlay"}, value=self.stacked,
                              on_change=lambda e: self._set("stacked", e.value)) \
                        .props("dense no-caps")
                ui.space()
                self.selection_label = ui.label("Shift+drag on the plot selects a window") \
                    .classes("text-caption text-grey-7")
                self.analyze_button = ui.button("Analyze selection…", icon="query_stats",
                                                on_click=self._analyze_selection) \
                    .props("flat dense no-caps")
                self.slice_button = ui.button("Slice to new signal", icon="content_cut",
                                              on_click=self._slice).props("flat dense no-caps")
                ui.button(icon="image", on_click=self._export_png).props("flat dense round") \
                    .tooltip("Export the plot as PNG")
            self.chart_box = ui.column().classes("w-full")
            self.below = ui.column().classes("w-full")
        self._update_buttons()
        self.render()
        return self

    def _export_png(self) -> None:
        if self.chart is not None:
            self.chart.export_png(f"{'_'.join(self.names)}.png")

    def _set(self, attr: str, value: Any) -> None:
        setattr(self, attr, value)
        self.window = (None, None)
        self.render()

    def render(self) -> None:
        sigs = self.signals()
        self.chart_box.clear()
        self.below.clear()
        if not sigs:
            with self.chart_box:
                ui.label("This signal is no longer in the session.").classes("text-grey-7")
            return
        self.spec = signal_figure(sigs, self.units, self.stacked,
                                  colors=self.wb.state.colors([s.name for s in sigs]))
        data, stats = signal_payload(sigs, self.spec, self.units, bins=DEFAULT_BINS)
        height = 380 if len(self.spec.panels) == 1 else min(720, 220 * len(self.spec.panels))
        with self.chart_box:
            self.chart = UPlotChart(self.spec.to_dict(), data, palette(), height=height,
                                    zoomable=True)
            self.chart.on("zoom", self._on_zoom)
            self.chart.on("select", self._on_select)
        with self.below:
            self.stats_box = ui.column().classes("w-full")
            self._render_stats(stats)
            for sig in sigs:
                self._properties(sig)

    async def _on_zoom(self, e: Any) -> None:
        args = e.args or {}
        self.window = (args.get("min"), args.get("max"))
        sigs = self.signals()
        if not sigs:
            return
        self._zoom_seq = seq = getattr(self, "_zoom_seq", 0) + 1
        # One window width on each side: the plot can be moved without waiting (§5.2).
        payload = await run.io_bound(signal_payload, sigs, self.spec, self.units,
                                     self.window[0], self.window[1], DEFAULT_BINS, 1.0)
        if self.chart is None or seq != self._zoom_seq:  # tab closed, or a newer window asked
            return
        data, stats = payload
        for panel_id, d in data.items():
            self.chart.set_panel_data(panel_id, d)
        self._render_stats(stats)

    def _on_select(self, e: Any) -> None:
        args = e.args or {}
        lo, hi = sorted((float(args.get("min", 0.0)), float(args.get("max", 0.0))))
        self.selection = (lo, hi)
        origin = time_origin(self.signals())
        self.selection_label.text = (f"Selection {(origin + lo).strftime('%H:%M:%S.%f')[:-3]} → "
                                     f"{(origin + hi).strftime('%H:%M:%S.%f')[:-3]} UTC "
                                     f"({fmt_num(hi - lo)} s)")
        self._update_buttons()

    def _update_buttons(self) -> None:
        enabled = self.selection is not None
        for button in (self.analyze_button, self.slice_button):
            button.set_enabled(enabled)

    def _selection_utc(self) -> tuple[UTCDateTime, UTCDateTime]:
        assert self.selection is not None
        origin = time_origin(self.signals())
        return origin + self.selection[0], origin + self.selection[1]

    async def _analyze_selection(self) -> None:
        if self.selection is None:
            return
        from .dialogs import launch_analysis

        t0, t1 = self._selection_utc()
        self.wb.pending_window = (str(t0), str(t1))
        name = await self.wb.choose_analysis()
        if name:
            await launch_analysis(self.wb, name, signals=self.names[:1])
        self.wb.pending_window = None

    def _slice(self) -> None:
        if self.selection is None:
            return
        t0, t1 = self._selection_utc()
        sig = self.signals()[0]
        session = self.wb.state.session
        new = sig.slice(t0, t1)
        name = session.add_signal(new)
        session.history.append(f"{name} = {sig.name}.slice('{t0}', '{t1}')")
        self.wb.state.terminal.console.sync()
        self.wb.open_signal(name)

    def _render_stats(self, stats: dict[str, dict]) -> None:
        self.stats_box.clear()
        sigs = {s.name: s for s in self.signals()}
        if not sigs:
            return
        origin = time_origin(list(sigs.values()))
        with self.stats_box:
            ui.label("Statistics of the visible window").classes("text-subtitle2")
            columns = [{"name": "k", "label": "", "field": "k", "align": "left"}]
            columns += [{"name": n, "label": n, "field": n, "align": "right"} for n in sigs]
            rows = []
            labels = [("mean", "Mean"), ("std", "Standard deviation"), ("pp", "Peak-to-peak"),
                      ("min", "Minimum"), ("max", "Maximum")]
            for key, label in labels:
                row = {"k": label}
                for n, s in sigs.items():
                    st = stats.get(n, {})
                    unit = "counts" if self.units == "counts" or s.unit == "counts" \
                        else pretty_unit(s.unit)
                    row[n] = f"{fmt_num(st.get(key, float('nan')))} {unit}"
                rows.append(row)
            row_n = {"k": "Samples"}
            row_w = {"k": "Window (UTC)"}
            for n in sigs:
                st = stats.get(n, {})
                row_n[n] = str(st.get("n", 0))
                start = (origin + st.get("start", 0.0)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                end = (origin + st.get("end", 0.0)).strftime("%H:%M:%S.%f")[:-3]
                row_w[n] = f"{start} → {end}"
            rows += [row_n, row_w]
            ui.table(columns=columns, rows=rows, row_key="k").props("dense flat bordered") \
                .classes("w-full")

    def _properties(self, sig: Any) -> None:
        with ui.expansion(f"Properties of {sig.name} — {sig.id}", icon="tune",
                          value=len(self.names) == 1).classes("w-full").props("dense"):
            with ui.row().classes("w-full gap-2"):
                name = ui.input("Name", value=sig.name).props("dense outlined")
                title = ui.input("Title", value=sig.title).props("dense outlined") \
                    .classes("grow")
            with ui.row().classes("w-full gap-2"):
                net = ui.input("Network", value=sig.network).props("dense outlined")
                sta = ui.input("Station", value=sig.station).props("dense outlined")
                loc = ui.input("Location", value=sig.location).props("dense outlined")
                cha = ui.input("Channel", value=sig.channel).props("dense outlined")
            with ui.row().classes("w-full gap-2 items-start"):
                unit = ui.select(UNITS if sig.unit in UNITS else [*UNITS, sig.unit],
                                 value=sig.unit, label="Unit").props("dense outlined")
                sens = ui.input("Sensitivity (physical unit per count)",
                                value=f"{sig.sensitivity:.10g}") \
                    .props('dense outlined hint="physical = counts × sensitivity; '
                           'e.g. 40 / 2**24"').classes("grow")
                if sig.full_scale is None:
                    full_text = ""
                elif sig.full_scale == 2**24:
                    full_text = "2**24"
                else:
                    full_text = f"{sig.full_scale:.10g}"
                full = ui.input("Full scale p-p (counts)", value=full_text,
                                placeholder="2**24 (default)").props("dense outlined")

            def apply() -> None:
                session = self.wb.state.session
                try:
                    sensitivity = float(safe_eval(sens.value))
                    full_scale = float(safe_eval(full.value)) if (full.value or "").strip() \
                        else sig.full_scale
                    changes = []
                    for attr, widget in (("title", title), ("network", net), ("station", sta),
                                         ("location", loc), ("channel", cha)):
                        if getattr(sig, attr) != widget.value:
                            setattr(sig, attr, widget.value)
                            changes.append(f"{sig.name}.{attr} = {widget.value!r}")
                    if sig.unit != unit.value:
                        sig.unit = normalize_unit(unit.value)
                        changes.append(f"{sig.name}.unit = {unit.value!r}")
                    if sig.sensitivity != sensitivity:
                        sig.sensitivity = sensitivity
                        changes.append(f"{sig.name}.sensitivity = {sensitivity:.6g}")
                    if full_scale is not None and sig.full_scale != full_scale:
                        sig.full_scale = full_scale
                        changes.append(f"{sig.name}.full_scale = {full_scale:.10g}")
                    renamed = name.value != sig.name
                    if renamed:
                        old = sig.name
                        self.wb.state.rename_signal(old, name.value)  # history included
                        self.names = [name.value if n == old else n for n in self.names]
                except (ParameterError, ValueError) as exc:
                    ui.notify(str(exc), type="negative")
                    return
                session.history.extend(changes)
                self.wb.state.terminal.console.sync()
                session.touch()
                ui.notify("Properties updated" if changes or renamed else "Nothing changed")

            with ui.row().classes("w-full"):
                ui.button("Apply", icon="check", on_click=apply).props("unelevated dense")
            with ui.expansion("S.print()", icon="description").props("dense").classes("w-full"):
                ui.code(sig.describe()).classes("w-full text-xs")

    def refresh(self) -> bool:
        if not self.signals():
            return False
        fingerprint = self._fingerprint()
        if fingerprint != self.versions:
            self.versions = fingerprint
            self.render()
        return True


# ---------------------------------------------------------------------------------- results
def render_results(result: Result, view: dict[str, Any]) -> None:
    """Results panel under a figure (§7.5)."""
    for warning in view["warnings"]:
        with ui.row().classes("w-full items-center gap-2 q-pa-xs bg-amber-1 rounded"):
            ui.icon("warning", color="amber-9")
            ui.label(warning).classes("text-body2 text-grey-9")
    if view["headline"]:
        with ui.row().classes("w-full gap-2 q-my-sm"):
            for item in view["headline"]:
                with ui.card().props("flat bordered").classes("q-pa-sm min-w-[150px]") \
                        .on("click", lambda item=item: _copy(item["value"])):
                    ui.label(item["label"]).classes("text-caption text-grey-7")
                    ui.label(item["value"]).classes("text-h6 text-grey-10")
                    if item["physical"]:
                        ui.label(item["physical"]).classes("text-caption text-grey-8")
    with ui.row().classes("w-full gap-4 items-start"):
        for group in view["groups"]:
            with ui.column().classes("gap-0 min-w-[300px]"):
                ui.label(group["title"]).classes("text-subtitle2 q-mt-xs")
                with ui.grid(columns=3).classes("gap-x-4 gap-y-0 items-baseline"):
                    for row in group["rows"]:
                        ui.label(row["label"]).classes("text-body2 text-grey-8")
                        ui.label(row["value"]).classes("text-body2 text-right cursor-pointer") \
                            .on("click", lambda row=row: _copy(row["value"]))
                        ui.label(f"({row['physical']})" if row["physical"] else "") \
                            .classes("text-caption text-grey-7")
    for table in view["tables"]:
        ui.label(table["name"].capitalize()).classes("text-subtitle2 q-mt-sm")
        columns = [{"name": c, "label": c, "field": c, "align": "right", "sortable": True}
                   for c in table["columns"]]
        rows = [dict(zip(table["columns"], r, strict=True)) for r in table["rows"]]
        ui.table(columns=columns, rows=rows).props("dense flat bordered").classes("max-w-[900px]")

    def tsv() -> str:
        lines = [f"{r['label']}\t{r['value']}\t{r['physical']}" for g in view["groups"]
                 for r in g["rows"]]
        return "\n".join(lines)

    def copy_table() -> None:
        ui.clipboard.write(tsv())
        ui.notify("Table copied")

    with ui.row().classes("w-full gap-2 q-mt-sm"):
        ui.button("Copy table", icon="content_copy", on_click=copy_table) \
            .props("flat dense no-caps")
    with ui.expansion("Parameters", icon="settings").props("dense").classes("w-full"):
        with ui.grid(columns=2).classes("gap-x-6 gap-y-0"):
            for key, value in result.params.items():
                ui.label(key).classes("text-body2 text-grey-8")
                ui.label(str(value)).classes("text-body2")
    with ui.expansion("Traceability", icon="fingerprint").props("dense").classes("w-full"):
        for s in result.signals:
            ui.label(f"{s.get('name', '')} — {s.get('id', '')} · {s.get('source', '') or '—'} "
                     f"· sha256 {str(s.get('sha256', ''))[:16]}…").classes("text-body2")
        meta = ", ".join(f"{k} {v}" for k, v in result.meta.items())
        ui.label(meta).classes("text-caption text-grey-7")


def _matplotlib_png(result: Result) -> bytes | None:
    from ...plot import plot_result

    fig = plot_result(result)
    if fig is None:
        return None
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110)
    return buffer.getvalue()


class ResultTab:
    """Figure(s) of a result with its results panel below (§7.4, §7.5)."""

    def __init__(self, wb: Workbench, name: str) -> None:
        self.wb = wb
        self.name = name

    def build(self) -> ResultTab:
        result = self.wb.state.session.get_result(self.name)
        self.result = result
        with ui.column().classes("w-full gap-1"):
            with ui.row().classes("w-full items-center gap-1"):
                ui.label(f"{result.name} · {result.title or result.kind}") \
                    .classes("text-subtitle1 text-weight-medium")
                ui.space()
                if result.kind in self.wb.registered:
                    ui.button("Edit parameters and re-run", icon="tune",
                              on_click=self._rerun).props("flat dense no-caps")
                ui.button("Add to report", icon="playlist_add",
                          on_click=lambda: self.wb.add_to_report(result.name)) \
                    .props("flat dense no-caps")
                with ui.button("Export", icon="download").props("flat dense no-caps"):
                    with ui.menu():
                        ui.menu_item("Result as JSON", lambda: ui.download.content(
                            result.to_json(), f"{result.name}_{result.kind}.json"))
                        ui.menu_item("Values as CSV", self._csv)
                        ui.menu_item("Interactive figure as PNG", lambda: self._chart_png())
                        ui.menu_item("Publication figure (matplotlib PNG)",
                                     lambda: self._publication("png"))
                        ui.menu_item("Publication figure (SVG)", lambda: self._publication("svg"))
                        ui.menu_item("Publication figure (PDF)", lambda: self._publication("pdf"))
                ui.button("Ask AI", icon="smart_toy",
                          on_click=lambda: self.wb.ask_ai_about(result)) \
                    .props("flat dense no-caps")
            self.charts: list[UPlotChart] = []
            specs = figure_specs(result)
            if len(specs) == 1:
                self._figure(result, specs[0][1])
            else:
                tabs = ui.tabs().props("dense no-caps align=left").classes("w-full")
                with tabs:
                    for title, _ in specs:
                        ui.tab(title)
                with ui.tab_panels(tabs, value=specs[0][0]).classes("w-full") \
                        .props("animated=false"):
                    for title, spec in specs:
                        with ui.tab_panel(title).classes("q-pa-none"):
                            self._figure(result, spec)
        return self

    def _figure(self, result: Result, spec: Any) -> None:
        if spec.static:
            png = _matplotlib_png(result)
            if png:
                ui.image(_png_data_url(png)).classes("w-full max-w-[1100px]")
        elif spec.panels:
            payload = figure_payload(result, spec)
            height = int(min(760, 260 * sum(p.height for p in spec.panels) + 40))
            chart = UPlotChart(payload["figure"], payload["data"], palette(), height=height)
            self.charts.append(chart)
        if spec.note:
            ui.label(spec.note).classes("text-caption text-grey-7")
        render_results(result, results_view(result, spec.results))

    def _chart_png(self) -> None:
        if self.charts:
            self.charts[0].export_png(f"{self.result.name}_{self.result.kind}.png")
        else:
            ui.notify("This result has no interactive figure", type="warning")

    def _csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{self.result.name}.csv"
            self.result.save(path)
            ui.download.content(path.read_bytes(), path.name)

    def _publication(self, fmt: str) -> None:
        from ...plot import plot_result

        fig = plot_result(self.result)
        if fig is None:
            ui.notify("This result is displayed as a table only", type="warning")
            return
        buffer = io.BytesIO()
        fig.savefig(buffer, format=fmt, dpi=200)
        ui.download.content(buffer.getvalue(), f"{self.result.name}_{self.result.kind}.{fmt}")

    async def _rerun(self) -> None:
        from .dialogs import launch_analysis

        names = [str(s["name"]) for s in self.result.signals if s.get("name")]
        await launch_analysis(self.wb, self.result.kind, signals=names)

    def refresh(self) -> bool:
        return any(r is self.result for r in self.wb.state.session.results)


# ---------------------------------------------------------------------------------- comparison
def _comparison_tsv(view: dict[str, Any]) -> str:
    lines = ["\t".join(["Group", "Quantity", *view["columns"]])]
    for group in view["groups"]:
        for row in group["rows"]:
            lines.append("\t".join([group["title"], row["label"], *row["values"]]))
    return "\n".join(lines)


class CompareTab:
    """Results of the same analysis overlaid, with a comparison table below (§7.6)."""

    def __init__(self, wb: Workbench, names: list[str]) -> None:
        self.wb = wb
        self.names = list(names)
        self.chart: UPlotChart | None = None
        self.kept: list[Result] = []

    def results(self) -> list[Result]:
        session = self.wb.state.session
        out = []
        for name in self.names:
            try:
                out.append(session.get_result(name))
            except ParameterError:
                continue
        return out

    def build(self) -> CompareTab:
        results = self.results()
        self.kept = results
        with ui.column().classes("w-full gap-1"):
            try:
                spec = comparison_spec(results, [self.wb.state.result_color(r) for r in results])
            except ParameterError as exc:
                ui.label(str(exc)).classes("text-body1 text-grey-8 q-pa-md")
                return self
            self.view = comparison_view(results, spec.results)
            with ui.row().classes("w-full items-center gap-1"):
                ui.label(spec.title).classes("text-subtitle1 text-weight-medium")
                ui.space()
                ui.button("Copy table", icon="content_copy", on_click=self._copy) \
                    .props("flat dense no-caps")
                with ui.button("Export", icon="download").props("flat dense no-caps"):
                    with ui.menu():
                        ui.menu_item("Table as CSV", self._csv)
                        ui.menu_item("Interactive figure as PNG", self._png)
            if spec.panels:
                payload = figure_payload(results, spec)
                height = int(min(760, 280 * sum(p.height for p in spec.panels) + 40))
                self.chart = UPlotChart(payload["figure"], payload["data"], palette(),
                                        height=height)
            else:
                ui.label("These results have no figure: the table compares their values.") \
                    .classes("text-caption text-grey-7")
            for warning in self.view["warnings"]:
                with ui.row().classes("w-full items-center gap-2 q-pa-xs bg-amber-1 rounded"):
                    ui.icon("warning", color="amber-9")
                    ui.label(warning).classes("text-body2 text-grey-9")
            for group in self.view["groups"]:
                ui.label(group["title"]).classes("text-subtitle2 q-mt-sm")
                columns = [{"name": "label", "label": "", "field": "label", "align": "left"}]
                columns += [{"name": f"c{i}", "label": c, "field": f"c{i}", "align": "right"}
                            for i, c in enumerate(self.view["columns"])]
                rows = [{"label": r["label"], **{f"c{i}": v for i, v in enumerate(r["values"])}}
                        for r in group["rows"]]
                ui.table(columns=columns, rows=rows, row_key="label") \
                    .props("dense flat bordered").classes("max-w-[1100px]")
        return self

    def _copy(self) -> None:
        ui.clipboard.write(_comparison_tsv(self.view))
        ui.notify("Comparison table copied")

    def _csv(self) -> None:
        import csv

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for line in _comparison_tsv(self.view).splitlines():
            writer.writerow(line.split("\t"))
        ui.download.content(buffer.getvalue(), f"comparison_{'_'.join(self.names)}.csv")

    def _png(self) -> None:
        if self.chart is not None:
            self.chart.export_png(f"comparison_{'_'.join(self.names)}.png")
        else:
            ui.notify("These results have no figure", type="warning")

    def refresh(self) -> bool:
        session = self.wb.state.session
        return all(any(r is s for s in session.results) for r in self.kept)


# ---------------------------------------------------------------------------------- batches
class BatchTab:
    """Progress and table of a batch (§8.5), updated while it runs."""

    def __init__(self, wb: Workbench, run_id: int) -> None:
        self.wb = wb
        self.run_id = run_id
        self.seen = -1

    def build(self) -> BatchTab:
        run = self.wb.state.batch(self.run_id)
        if run is None:
            ui.label("This batch is no longer available").classes("text-grey-7")
            return self
        self.run = run
        s = run.settings
        with ui.column().classes("w-full gap-1"):
            with ui.row().classes("w-full items-center gap-1"):
                ui.label(f"{run.title} · {' '.join(s.patterns)}") \
                    .classes("text-subtitle1 text-weight-medium")
                ui.space()
                self.stop_button = ui.button("Stop", icon="stop", on_click=run.stop) \
                    .props("flat dense no-caps")
                with ui.button("Export", icon="download").props("flat dense no-caps"):
                    with ui.menu():
                        ui.menu_item("Table as CSV", lambda: self._export("csv"))
                        ui.menu_item("Table as JSON", lambda: self._export("json"))
                ui.button("Global report", icon="article", on_click=self._report) \
                    .props("flat dense no-caps").tooltip("Quarto report with the table")
            params = ", ".join(f"{k}={v}" for k, v in {**s.params, **s.read_options}.items())
            ui.label(f"Parameters: {params or 'defaults'}"
                     + (f" · output {Path(s.out).name}" if s.out else "")) \
                .classes("text-caption text-grey-7")
            self.bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full")
            self.status = ui.label("").classes("text-body2 text-grey-8")
            self.table = ui.table(columns=[], rows=[], row_key="_row", pagination=50) \
                .props("dense flat bordered").classes("w-full")
            self.table.add_slot("body-cell-error", r"""
                <q-td :props="props"><span class="text-negative">{{ props.value }}</span></q-td>
            """)
        ui.timer(0.5, self.update)
        self.update()
        return self

    def update(self) -> None:
        run = self.run
        if run.version == self.seen:
            return
        self.seen = run.version
        self.bar.value = run.done / run.total if run.total else 0.0
        current = f" · reading {run.current}" if run.current and run.running else ""
        self.status.text = (f"{run.state} · {run.done}/{run.total} files · {len(run.rows)} "
                            f"signal(s), {run.failures} failure(s){current}"
                            + (f" · {run.error}" if run.error else "")
                            + (f" · table written to {self._shown(run.out)}" if run.out else ""))
        self.stop_button.set_visibility(run.running)
        columns, rows = run.table()
        self.table.columns = columns
        self.table.rows = rows
        self.table.update()

    def _shown(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.wb.root).as_posix()
        except ValueError:
            return str(path)

    def _export(self, fmt: str) -> None:
        from ...scripts import write_table

        with tempfile.TemporaryDirectory() as tmp:
            path = write_table(list(self.run.rows), Path(tmp) / f"batch_{self.run.id}.{fmt}")
            ui.download.content(path.read_bytes(), path.name)

    def _report(self) -> None:
        from ...report import generate_report, render_report

        if not self.run.rows:
            ui.notify("The batch has no row yet", type="warning")
            return
        summary = self.run.summary()
        wb = self.wb

        def work(job: Any) -> Any:
            qmd = generate_report([summary], title=summary.title, formats=["html"],
                                  output_dir=wb.reports_dir, config=wb.state.config)
            job.message = "rendering with Quarto"
            render_report(Path(qmd), ["html"])
            return qmd

        def done(job: Any) -> None:
            wb.report_failure(job)
            if job.state == "done":
                wb.channel.push({"type": "notify", "level": "positive",
                                 "text": f"Report written: {Path(job.result).parent.name}"})
            wb.channel.push({"type": "reports"})

        wb.state.jobs.start("batch report", work, kind="report", client=wb.id, on_done=done)
        ui.notify("Generating the report of the batch…")


# ---------------------------------------------------------------------------------- real time
class RealtimeTab:
    """Real-time dashboard (§8.2): statistics, trace, FFT and PSD of every channel."""

    STAT_COLUMNS = [("channel", "Channel"), ("samples", "Samples"), ("rate", "Rate"),
                    ("latency", "Latency"), ("gaps", "Gaps"), ("mean", "Mean"),
                    ("std", "Standard deviation"), ("pp", "Peak-to-peak"), ("note", "")]

    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.run: Any = None
        self.seen = (-1, -1)

    def build(self) -> RealtimeTab:
        self.box = ui.column().classes("w-full gap-1")
        self.render()
        ui.timer(0.5, self.update)
        return self

    def render(self) -> None:
        run = self.wb.state.realtime
        self.run, self.seen = run, (-1, -1)
        self.box.clear()
        with self.box:
            if run is None:
                ui.label("No real-time session: choose the streams in the Real time view, "
                         "then Start.").classes("text-body1 text-grey-7 q-pa-md")
                ui.button("Open the Real time view", icon="monitor_heart",
                          on_click=lambda: self.wb.show_view("realtime")).props("flat no-caps")
                return
            s = run.settings
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(f"Real time · {s.server} · {len(run.ids)} channel(s)") \
                    .classes("text-subtitle1 text-weight-medium")
                self.state_label = ui.label("").classes("text-caption text-grey-8")
                ui.space()
                self.record = ui.switch("Record to miniSEED", value=run.recording,
                                        on_change=self._record)
                self.stop_button = ui.button("Stop", icon="stop", on_click=run.stop) \
                    .props("flat dense no-caps")
            ui.label(f"Statistics over the last {fmt_num(s.window)} s"
                     + (f" · physical unit {run.unit} (sensitivity {s.sensitivity:.6g})"
                        if run.physical else " · counts")).classes("text-caption text-grey-7")
            columns = [{"name": k, "label": label, "field": k,
                        "align": "left" if k in ("channel", "note") else "right"}
                       for k, label in self.STAT_COLUMNS]
            self.table = ui.table(columns=columns, rows=[], row_key="channel") \
                .props("dense flat bordered").classes("w-full")
            height = min(640, 150 * len(run.ids) + 40)
            self.trace = UPlotChart(run.trace_figure().to_dict(), {}, palette(), height=height,
                                    live=True)
            with ui.row().classes("w-full no-wrap gap-2"):
                with ui.column().classes("w-1/2 min-w-0"):
                    ui.label(run.spectrum_figure("fft").title).classes("text-subtitle2")
                    self.fft = UPlotChart(run.spectrum_figure("fft").to_dict(), {}, palette(),
                                          height=300, live=True)
                with ui.column().classes("w-1/2 min-w-0"):
                    ui.label(run.spectrum_figure("dsp").title).classes("text-subtitle2")
                    self.dsp = UPlotChart(run.spectrum_figure("dsp").to_dict(), {}, palette(),
                                          height=300, live=True)
            ui.label("Ctrl + wheel or drag to zoom (the axes stop following the data), "
                     "double-click to follow again.").classes("text-caption text-grey-7")

    def _record(self, e: Any) -> None:
        run = self.run
        if run is None:
            return
        folder = None
        if e.value:
            try:
                folder = confine(run.settings.record_dir or "data/realtime", self.wb.roots)
            except PermissionError as exc:
                ui.notify(str(exc), type="negative")
                return
        run.set_recording(folder)
        ui.notify(f"Recording in {folder}" if folder else "Recording stopped")

    def update(self) -> None:
        run = self.wb.state.realtime
        if run is not self.run:
            self.render()
            return
        if run is None:
            return
        view = run.view
        self.state_label.text = (f"{run.state}" + (f" · {run.error}" if run.error else "")
                                 + (" · recording" if run.recording else ""))
        self.stop_button.set_visibility(run.running)
        if view.version != self.seen[0]:
            self.table.rows = view.stats
            self.table.update()
            for panel_id, data in view.trace.items():
                self.trace.set_panel_data(panel_id, data)
        if view.spectra_version != self.seen[1] and view.fft:
            self.fft.set_panel_data("spectrum", view.fft["spectrum"])
            self.dsp.set_panel_data("spectrum", view.dsp["spectrum"])
        self.seen = (view.version, view.spectra_version)


# ---------------------------------------------------------------------------------- others
class FigureTab:
    def __init__(self, wb: Workbench, name: str) -> None:
        self.wb, self.name = wb, name

    def build(self) -> FigureTab:
        record = next((f for f in self.wb.state.figures if f.name == self.name), None)
        if record is None:
            ui.label("Figure not found").classes("text-grey-7")
            return self
        if record.title:
            ui.label(record.title).classes("text-subtitle1")
        ui.image(record.data_url()).classes("w-full max-w-[1100px]")
        ui.button("Download PNG", icon="download",
                  on_click=lambda: ui.download.content(record.png, f"{record.name}.png")) \
            .props("flat dense no-caps")
        return self


class VariableTab:
    """Display of a variable of the Python terminal (``Variables`` group)."""

    def __init__(self, wb: Workbench, name: str) -> None:
        self.wb, self.name = wb, name

    def build(self) -> VariableTab:
        self.box = ui.column().classes("w-full")
        self.render()
        return self

    def render(self) -> None:
        self.box.clear()
        ns = self.wb.state.terminal.console.ns
        if self.name not in ns:
            with self.box:
                ui.label(f"{self.name} no longer exists in the terminal").classes("text-grey-7")
            return
        value = ns[self.name]
        with self.box:
            ui.label(f"{self.name} — {type(value).__name__}").classes("text-subtitle1")
            if isinstance(value, np.ndarray) and value.ndim == 1 and \
                    np.issubdtype(value.dtype, np.number) and value.size:
                spec, data = array_figure(self.name, value)
                UPlotChart(spec.to_dict(), data, palette(), height=320)
                finite = value[np.isfinite(value)] if np.issubdtype(value.dtype, np.floating) \
                    else value
                with ui.grid(columns=2).classes("gap-x-6"):
                    for label, v in (("Size", value.size), ("Mean", np.mean(finite)),
                                     ("Standard deviation", np.std(finite)),
                                     ("Minimum", np.min(finite)), ("Maximum", np.max(finite))):
                        ui.label(label).classes("text-grey-8")
                        ui.label(fmt_num(float(v)))
            else:
                text = repr(value)
                ui.code(text[:20000] + ("…" if len(text) > 20000 else "")).classes("w-full")

    def refresh(self) -> bool:
        if self.name not in self.wb.state.terminal.console.ns:
            return False
        self.render()
        return True


class EditorTab:
    """Text file in Monaco (§9): save, syntax check, run script, run selection."""

    def __init__(self, wb: Workbench, path: Path) -> None:
        self.wb, self.path = wb, path
        self.dirty = False
        self.mtime = path.stat().st_mtime if path.exists() else 0.0

    def build(self) -> EditorTab:
        text = self.path.read_text(encoding="utf-8", errors="replace") if self.path.exists() \
            else ""
        with ui.column().classes("w-full h-full gap-1"):
            with ui.row().classes("w-full items-center gap-1"):
                ui.label(str(self.path.relative_to(self.wb.root))
                         if self.path.is_relative_to(self.wb.root) else str(self.path)) \
                    .classes("text-caption text-grey-8")
                self.dirty_label = ui.label("").classes("text-caption text-amber-9")
                ui.space()
                ui.button("Save", icon="save", on_click=self._save_clicked) \
                    .props("flat dense no-caps").tooltip("Ctrl+S")
                if self.path.suffix == ".py" and self.wb.state.code_execution:
                    ui.button("Run", icon="play_arrow", on_click=self._run_clicked) \
                        .props("flat dense no-caps").tooltip("F5")
                    ui.button("Run selection", icon="playlist_play",
                              on_click=self._run_selection_clicked) \
                        .props("flat dense no-caps").tooltip("Shift+Enter")
                if self.path.suffix == ".qmd":
                    ui.button("Render", icon="picture_as_pdf",
                              on_click=lambda: self.wb.render_report(self.path)) \
                        .props("flat dense no-caps")
            self.editor = MonacoEditor(text, language_of(self.path)) \
                .classes("w-full").style("height: calc(100vh - 330px); min-height: 260px")
            self.editor.on("save", lambda e: self.save(e.args))
            self.editor.on("run", lambda e: self.run(e.args))
            self.editor.on("run_selection", self._run_selection_event)
            self.editor.on("dirty", lambda e: self._set_dirty(bool(e.args)))
        return self

    def _set_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self.dirty_label.text = "● modified" if dirty else ""

    async def _save_clicked(self) -> None:
        self.save(await self.editor.get_value())

    async def _run_clicked(self) -> None:
        self.run(await self.editor.get_value())

    def _run_selection_event(self, e: Any) -> None:
        if self.wb.state.code_execution and e.args:
            self.wb.state.terminal.submit(str(e.args))

    async def _run_selection_clicked(self) -> None:
        text = await self.editor.run_method("selectionOrCell", timeout=5)
        if text:
            self.wb.state.terminal.submit(str(text))

    def save(self, text: Any) -> None:
        text = str(text if text is not None else "")
        try:
            path = confine(self.path, self.wb.roots)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except OSError as exc:
            ui.notify(f"Cannot save {self.path.name}: {exc}", type="negative")
            return
        self.mtime = self.path.stat().st_mtime
        self.editor.mark_saved()
        self._set_dirty(False)
        markers = []
        if self.path.suffix == ".py":
            try:
                compile(text, str(self.path), "exec")
            except SyntaxError as exc:
                markers.append({"line": exc.lineno or 1, "column": exc.offset or 1,
                                "message": exc.msg})
                ui.notify(f"Syntax error line {exc.lineno}: {exc.msg}", type="warning")
        self.editor.set_markers(markers)
        self.wb.state.log("editor", f"saved {self.path.name}")
        if not markers:
            ui.notify(f"Saved {self.path.name}", timeout=1200)

    def run(self, text: Any) -> None:
        from ...scripts import scripts_dir

        if self.path.suffix != ".py" or not self.wb.state.code_execution:
            return
        if self.dirty:
            self.save(text)
        if self.path.parent.resolve() == scripts_dir().resolve():
            from .dialogs import run_script_dialog

            ui.timer(0.01, lambda: run_script_dialog(self.wb, self.path.stem), once=True)
        else:
            self.wb.state.terminal.submit(f"exec(open({str(self.path)!r}).read())")

    def check_disk(self) -> None:
        """Reload a file changed on disk (terminal, scripts) unless it is being edited."""
        if not self.path.exists():
            return
        mtime = self.path.stat().st_mtime
        if mtime == self.mtime:
            return
        self.mtime = mtime
        if self.dirty:
            ui.notify(f"{self.path.name} changed on disk; your changes are kept",
                      type="warning")
        else:
            self.editor.set_value(self.path.read_text(encoding="utf-8", errors="replace"))

    def close(self) -> None:
        if self.dirty:
            ui.notify(f"{self.path.name} was closed with unsaved changes", type="warning")


class ReportTab:
    """HTML preview of a rendered report."""

    def __init__(self, wb: Workbench, url: str, title: str) -> None:
        self.wb, self.url, self.title = wb, url, title

    def build(self) -> ReportTab:
        ui.element("iframe").props(f'src="{self.url}"').classes("w-full") \
            .style("height: calc(100vh - 260px); border: 1px solid #e1e0d9")
        return self


__all__ = ["BatchTab", "CompareTab", "EditorTab", "FigureTab", "RealtimeTab", "ReportTab",
           "ResultTab", "SignalTab", "VariableTab", "WorkArea", "render_results"]
