"""Console rendering: rich tables for results and signals, non-blocking matplotlib windows."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..core.result import Result
from ..core.session import Session
from ..core.signal import Signal


class ConsoleDisplay:
    """Display handler installed on the console session (``session.display_handler``)."""

    def __init__(self, session: Session, console: Console | None = None) -> None:
        self.session = session
        self.console = console or Console()
        self.displayed: set[int] = set()
        self._pyplot_ready = False

    # ------------------------------------------------------------------ entry point
    def __call__(self, obj: Any, show: bool, save: str | None) -> None:
        if obj == "signals":
            self.print_signals()
            return
        if isinstance(obj, Signal):
            obj.print()
            return
        if isinstance(obj, Result):
            if show:
                self.print_result(obj)
                self.displayed.add(id(obj))
            if show or save:
                self.figure(obj, show, save)

    # ------------------------------------------------------------------ text
    def print_result(self, result: Result) -> None:
        if result.kind == "signal":
            return
        table = Table(title=result.title or result.kind, title_justify="left",
                      show_header=False, box=None, pad_edge=False, title_style="bold")
        table.add_column(style="dim")
        table.add_column(justify="right")
        table.add_column(style="dim")
        for label, value, phys in result.rows():
            table.add_row(label, value, f"({phys})" if phys else "")
        self.console.print(table)
        for name, rows in result.tables.items():
            if not rows:
                continue
            sub = Table(title=name.replace("_", " "), title_justify="left", box=None)
            for key in rows[0]:
                sub.add_column(str(key), justify="right")
            for row in rows:
                sub.add_row(*[self._cell(v) for v in row.values()])
            self.console.print(sub)
        for w in result.warnings:
            self.console.print(Text(f"Warning: {w}", style="yellow"))

    @staticmethod
    def _cell(value: Any) -> str:
        from ..core.units import fmt_num

        return fmt_num(value) if isinstance(value, (int, float)) else str(value)

    def print_signals(self) -> None:
        rows = self.session.list_rows()
        if not rows:
            self.console.print("No signal loaded. Use [bold]/load file.mseed[/bold].")
            return
        table = Table(box=None, header_style="bold")
        for key in rows[0]:
            table.add_column(key)
        for row in rows:
            table.add_row(*row.values())
        self.console.print(table)

    def error(self, message: str) -> None:
        self.console.print(Text(message, style="red"))

    def warning(self, message: str) -> None:
        self.console.print(Text(f"Warning: {message}", style="yellow"))

    def info(self, message: str, markup: bool = False) -> None:
        """Print a message; ``markup=True`` interprets rich tags such as ``[bold]``."""
        self.console.print(message, markup=markup, highlight=False)

    # ------------------------------------------------------------------ figures
    def _pyplot(self) -> Any:
        import matplotlib

        if not self._pyplot_ready:
            backend = self.session.config.get("console.mpl_backend")
            if backend:
                matplotlib.use(backend)
        import matplotlib.pyplot as plt

        if not self._pyplot_ready:
            plt.ion()
            self._pyplot_ready = True
        return plt

    def figure(self, result: Result, show: bool, save: str | None) -> None:
        from ..plot import has_figure, plot_result

        if not has_figure(result.kind):
            if save:
                self.warning(f"{result.kind} has no figure to save")
            return
        if show:
            plt = self._pyplot()
            fig = plt.figure(figsize=(10, 6.5))
            plot_result(result, fig)
            manager = getattr(fig.canvas, "manager", None)
            if manager is not None:
                manager.set_window_title(result.title or result.kind)
            fig.show()
            plt.pause(0.001)
        else:
            fig = plot_result(result)
        if save:
            fig.savefig(save, dpi=150)
            self.info(f"Figure saved to {save}")
