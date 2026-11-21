"""Formulas of the chat (web specification §11.2): LaTeX turned into MathML on the server.

The answers of the models write formulas as ``$…$`` or ``\\(…\\)`` (inline) and ``$$…$$`` or
``\\[…\\]`` (display). They are converted by latex2mathml (``[web]`` dependency) and drawn by
the browser itself (MathML Core): no script and no font to load. A formula that cannot be
converted keeps its LaTeX text, and code (fenced blocks, inline code) is never touched. A
single ``$`` is a formula only when it is followed by a non-space and its closing ``$`` is
preceded by a non-space and not followed by a digit, so that "costs $5 and $10" stays text.
"""

from __future__ import annotations

import re
from functools import lru_cache

from nicegui import ui
from nicegui.elements.markdown import prepare_content

CODE = re.compile(r"(```.*?```|~~~.*?~~~|`[^`\n]+`)", re.DOTALL)
MATH = re.compile(
    r"\$\$(?P<d1>.+?)\$\$"
    r"|\\\[(?P<d2>.+?)\\\]"
    r"|\\\((?P<i1>.+?)\\\)"
    r"|(?<![\\$\w])\$(?=\S)(?P<i2>[^$\n]+?)(?<=\S)\$(?![\w$])",
    re.DOTALL,
)


@lru_cache(maxsize=2048)
def to_mathml(latex: str, display: bool = False) -> str | None:
    """MathML of a LaTeX formula, or ``None`` (latex2mathml missing, formula not understood)."""
    try:
        from latex2mathml.converter import convert
    except ImportError:
        return None
    try:
        return str(convert(latex.strip(), display="block" if display else "inline"))
    except Exception:  # an unknown command must not break the message
        return None


def split_math(text: str) -> tuple[str, dict[str, str]]:
    """Markdown with its formulas replaced by placeholders, and the MathML of each one."""
    found: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        display = match.group("d1") is not None or match.group("d2") is not None
        latex = next(g for g in match.groups() if g is not None)
        mathml = to_mathml(latex, display)
        if mathml is None:
            return match.group(0)
        key = f"OTSMATH{len(found)}Z"
        found[key] = mathml
        return key

    parts = CODE.split(text)
    for i in range(0, len(parts), 2):  # even parts are outside code
        parts[i] = MATH.sub(replace, parts[i])
    return "".join(parts), found


def render(content: str, extras: str = "fenced-code-blocks tables") -> str:
    """HTML of a chat message: its Markdown (as ``ui.markdown``) with MathML formulas."""
    text, found = split_math(content)
    html = prepare_content(text, extras)
    for key, mathml in found.items():
        html = html.replace(key, mathml)
    return html


class ChatMarkdown(ui.markdown):
    """``ui.markdown`` that also draws LaTeX formulas (``$…$``, ``$$…$$``, ``\\(…\\)``,
    ``\\[…\\]``)."""

    def _handle_content_change(self, content: str) -> None:
        html = render(content, " ".join(self.extras))
        if callable(self._sanitize):
            html = self._sanitize(html)
        if self._props.get("innerHTML") != html:
            self._props["innerHTML"] = html


__all__ = ["ChatMarkdown", "render", "split_math", "to_mathml"]
