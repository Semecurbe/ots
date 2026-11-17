"""Quarto report generation (specification §14).

A report is a folder ``reports/YYYY-MM-DD_hhmm_<title>/`` holding ``report.qmd`` and the
figures (PNG). It can be rendered to HTML and PDF with Quarto (Typst by default, LaTeX as an
option).
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jinja2

from .._version import __version__
from ..core.config import Config
from ..core.errors import ParameterError
from ..core.result import Result
from ..core.units import fmt_num

TEMPLATE_NAME = "report.qmd.j2"


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:40] or "report"


def _md(value: Any) -> str:
    """Escape a value for a Markdown table cell."""
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def _num(value: Any) -> str:
    return fmt_num(value) if isinstance(value, (int, float)) else _md(value)


def template_path(name: str = TEMPLATE_NAME) -> Path:
    """Project template (``templates/<name>``) if present, else the packaged default."""
    local = Path.cwd() / "templates" / name
    if local.is_file():
        return local
    return Path(__file__).resolve().parent.parent / "templates" / name


def software_versions() -> dict[str, str]:
    import matplotlib
    import numpy
    import obspy
    import scipy

    return {
        "onthesignal": __version__,
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "obspy": obspy.__version__,
        "matplotlib": matplotlib.__version__,
    }


def generate_report(
    results: Sequence[Result],
    title: str | None = None,
    output_dir: str | Path | None = None,
    formats: Sequence[str] = ("html", "pdf"),
    render: bool = False,
    author: str | None = None,
    context: str | None = None,
    conclusion: str | None = None,
    config: Config | None = None,
) -> Path:
    """Write ``report.qmd`` and its figures; optionally render it with Quarto.

    Parameters
    ----------
    results : sequence of Result
        Results to include, in order.
    title : str, optional
        Report title (default: title of the first result).
    output_dir : str or Path, optional
        Parent folder (default: ``reports/`` or ``[paths] reports`` from the configuration).
    formats : sequence of {"html", "pdf"}
        Output formats declared in the document.
    render : bool
        Run ``quarto render`` for each format.
    author, context, conclusion : str, optional
        Free text inserted in the report.

    Returns
    -------
    Path
        Path of ``report.qmd``.
    """
    from ..plot import plot_result

    if not results:
        raise ParameterError("No result to report")
    config = config or Config()
    formats = [f.lower() for f in formats]
    unknown = set(formats) - {"html", "pdf"}
    if unknown:
        raise ParameterError(f"Unknown report format(s): {', '.join(sorted(unknown))}")
    engine = str(config.get("report.pdf_engine", "typst")).lower()
    quarto_formats = ["html" if f == "html" else ("typst" if engine == "typst" else "pdf")
                      for f in formats]
    title = title or results[0].title or "onthesignal report"
    root = Path(output_dir or config.get("paths.reports", "reports"))
    folder = root / f"{datetime.now():%Y-%m-%d_%H%M}_{_slug(title)}"
    n = 2
    while folder.exists():
        folder = root / f"{datetime.now():%Y-%m-%d_%H%M}_{_slug(title)}-{n}"
        n += 1
    (folder / "figures").mkdir(parents=True)

    entries = []
    signals: dict[str, dict] = {}
    for i, r in enumerate(results, start=1):
        figure = None
        fig = plot_result(r)
        if fig is not None:
            figure = f"figures/{i:02d}_{r.kind}.png"
            fig.savefig(folder / figure, dpi=200)
        entries.append({
            "title": r.title or r.kind,
            "figure": figure,
            "rows": r.rows(),
            "tables": r.tables,
            "warnings": r.warnings,
            "params": {k: v for k, v in r.params.items() if v is not None},
        })
        for s in r.signals:
            key = f"{s.get('id')}|{s.get('sha256')}|{s.get('name')}"
            entry = dict(s)
            entry["source_name"] = os.path.basename(s.get("source", "")) or "—"
            entry.setdefault("gaps", [])
            entry.setdefault("history", [])
            signals.setdefault(key, entry)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_path().parent)),
        undefined=jinja2.ChainableUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["md"] = _md
    env.filters["num"] = _num
    text = env.get_template(template_path().name).render(
        title=title.replace('"', "'"),
        author=author or config.get("report.author", ""),
        date=datetime.now().strftime("%Y-%m-%d"),
        generated=datetime.now(UTC).isoformat(timespec="seconds"),
        formats=quarto_formats,
        context=context,
        conclusion=conclusion,
        results=entries,
        signals=list(signals.values()),
        versions=software_versions(),
    )
    qmd = folder / "report.qmd"
    qmd.write_text(text, encoding="utf-8")
    if render:
        render_report(qmd, quarto_formats)
    return qmd


def render_report(qmd: Path, formats: Sequence[str]) -> list[Path]:
    """Render ``qmd`` with Quarto for each format; returns the produced files."""
    quarto = shutil.which("quarto")
    if quarto is None:
        raise ParameterError(
            f"Quarto is not installed: render the report with 'quarto render {qmd}'"
        )
    produced = []
    for fmt in formats:
        proc = subprocess.run(
            [quarto, "render", qmd.name, "--to", fmt], cwd=qmd.parent, capture_output=True,
            text=True, check=False,
        )
        if proc.returncode != 0:
            raise ParameterError(f"quarto render --to {fmt} failed:\n{proc.stderr[-2000:]}")
        suffix = ".html" if fmt == "html" else ".pdf"
        produced.append(qmd.with_suffix(suffix))
    return produced


__all__ = ["generate_report", "render_report", "software_versions", "template_path"]
