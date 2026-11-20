"""Custom NiceGUI elements: µPlot chart and Monaco editor (web specification §5, §9).

The JavaScript libraries are vendored in ``web/static/vendor`` (pinned versions, licenses
included) and served by the application: the interface works offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nicegui import ui

VENDOR = Path(__file__).resolve().parent.parent / "static" / "vendor"
#: URL of the vendored files (Monaco is loaded with its AMD loader from there).
VENDOR_URL = "/_ots/vendor"


class UPlotChart(ui.element, component="uplot_chart.js",
                 esm={"onthesignal-uplot": "../static/vendor/uplot"}):
    """Interactive chart of a :class:`~onthesignal.plot.spec.FigureSpec`.

    Parameters
    ----------
    figure : dict
        ``FigureSpec.to_dict()``.
    data : dict
        Panel data from :func:`onthesignal.web.figures.figure_payload`.
    palette : dict
        Color tokens (:func:`onthesignal.web.figures.palette`).
    height : int
        Total height of the panels in pixels.
    zoomable : bool
        Emit ``zoom`` events so that the server reloads the visible window (time plots).
    live : bool
        Real-time dashboard: new panel data re-scale the axes until the user zooms in.
    """

    def __init__(self, figure: dict, data: dict, palette: dict, height: int = 420,
                 zoomable: bool = False, live: bool = False) -> None:
        super().__init__()
        self.add_resource(VENDOR / "uplot")
        self._props["figure"] = figure
        self._props["data"] = data
        self._props["palette"] = palette
        self._props["height"] = height
        self._props["zoomable"] = zoomable
        self._props["live"] = live

    def set_figure(self, figure: dict, data: dict) -> None:
        self._props["figure"] = figure
        self._props["data"] = data
        self.update()

    def set_panel_data(self, panel_id: str, data: dict) -> None:
        """Replace the data of one panel, keeping the current zoom."""
        self.run_method("setPanelData", panel_id, data)

    def export_png(self, filename: str = "figure.png") -> None:
        self.run_method("exportPng", filename)


#: File extensions and Monaco languages (TOML is shown with the INI highlighting).
LANGUAGES = {".py": "python", ".md": "markdown", ".qmd": "markdown", ".toml": "ini",
             ".ini": "ini", ".cfg": "ini", ".yml": "yaml", ".yaml": "yaml", ".json": "json",
             ".sh": "shell", ".bash": "shell", ".txt": "plaintext", ".csv": "plaintext",
             ".j2": "plaintext", ".log": "plaintext", ".xml": "xml", ".sql": "sql"}


def language_of(path: str | Path) -> str:
    return LANGUAGES.get(Path(path).suffix.lower(), "plaintext")


class MonacoEditor(ui.element, component="monaco_editor.js"):
    """Monaco editor; events ``ready``, ``dirty``, ``save``, ``run``, ``run_selection``."""

    def __init__(self, value: str = "", language: str = "plaintext",
                 read_only: bool = False) -> None:
        super().__init__()
        self._props["value"] = value
        self._props["language"] = language
        self._props["readOnly"] = read_only
        self._props["baseUrl"] = f"{VENDOR_URL}/monaco"

    async def get_value(self) -> Any:
        return await self.run_method("getValue", timeout=5)

    def set_value(self, text: str) -> None:
        self.run_method("setValue", text)

    def mark_saved(self) -> None:
        self.run_method("markSaved")

    def set_markers(self, markers: list[dict]) -> None:
        self.run_method("setMarkers", markers)


__all__ = ["LANGUAGES", "MonacoEditor", "UPlotChart", "VENDOR", "VENDOR_URL", "language_of"]
