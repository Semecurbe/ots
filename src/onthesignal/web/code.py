"""Help for writing Python in the editor (web specification §9.4): Jedi and ruff.

Jedi analyses the code of the file together with the live namespace of the Python terminal,
so that after ``S1.`` the editor proposes ``sensitivity``, ``lnm``… and documents the API of
onthesignal. ruff checks the file (its rules and configuration are those of the project:
``pyproject.toml`` or ``ruff.toml`` near the file, ruff's defaults otherwise).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

#: Completion items sent to the browser (the first ones carry their documentation).
MAX_ITEMS, DOCUMENTED = 200, 30

# Jedi warns about modules it cannot analyse ("numpy._core.array not importable"): those are
# not problems of the user, and the web interface would show them as notifications.
warnings.filterwarnings("ignore", module=r"jedi(\.|$)")


def _script(code: str, namespace: dict | None, path: str | Path | None) -> Any:
    import jedi

    return jedi.Interpreter(code, [namespace or {}], path=str(path) if path else None)


def complete(code: str, line: int, column: int, namespace: dict | None = None,
             path: str | Path | None = None) -> list[dict[str, str]]:
    """Completions at ``line`` (from 1) and ``column`` (from 0)."""
    try:
        items = _script(code, namespace, path).complete(line, column)
    except Exception:  # an incomplete line must never break the editor
        return []
    lines = code.splitlines() or [""]
    before = lines[min(line, len(lines)) - 1][:column]
    typed = before[len(before.rstrip("_" + "".join(map(chr, range(48, 123))))):]
    if not typed.startswith("_"):  # private names only when asked for
        items = [item for item in items if not item.name.startswith("_")]
    out = []
    for i, item in enumerate(items[:MAX_ITEMS]):
        entry = {"label": item.name, "kind": item.type, "detail": item.description}
        if i < DOCUMENTED:
            try:
                entry["doc"] = item.docstring(fast=True)[:1500]
            except Exception:
                pass
        out.append(entry)
    return out


def signature(code: str, line: int, column: int, namespace: dict | None = None,
              path: str | Path | None = None) -> dict | None:
    """Signature of the call around the cursor, with the parameter being typed."""
    try:
        signatures = _script(code, namespace, path).get_signatures(line, column)
    except Exception:
        return None
    if not signatures:
        return None
    sig = signatures[0]
    return {"label": sig.to_string(), "parameters": [p.to_string() for p in sig.params],
            "active": sig.index or 0, "doc": sig.docstring(raw=True)[:2000]}


def hover(code: str, line: int, column: int, namespace: dict | None = None,
          path: str | Path | None = None) -> str | None:
    """Documentation of the name under the cursor, in Markdown."""
    try:
        names = _script(code, namespace, path).help(line, column)
    except Exception:
        return None
    for name in names:
        try:
            doc = name.docstring()
        except Exception:
            continue
        if doc:
            head, _, body = doc.partition("\n\n")
            if "(" in head and not body:
                return f"```python\n{head}\n```"
            return f"```python\n{head}\n```\n\n{body[:3000]}" if "(" in head \
                else doc[:3000]
    return None


def ruff_binary() -> str | None:
    """The ruff executable (``[web]`` dependency), or ``None`` when it is not installed."""
    try:
        from ruff.__main__ import find_ruff_bin

        return str(find_ruff_bin())
    except Exception:
        found = shutil.which("ruff", path=str(Path(sys.executable).parent)) or shutil.which("ruff")
        return found


def ruff_markers(text: str, path: str | Path, cwd: str | Path | None = None,
                 timeout: float = 15.0, defined: list[str] | None = None) -> list[dict] | None:
    """Findings of ``ruff check`` on ``text`` as editor markers; ``None`` without ruff.

    ``defined``: names known when the code runs in the Python terminal (``S1``, ``noise``…),
    not reported as undefined.
    """
    binary = ruff_binary()
    if binary is None:
        return None
    command = [binary, "check", "--output-format", "json", "--no-cache", "--exit-zero",
               "--stdin-filename", str(path)]
    if defined:
        names = sorted(n for n in defined if n.isidentifier() and not n.startswith("_"))
        command += ["--config", f"builtins = {json.dumps(names)}"]
    try:
        proc = subprocess.run(
            [*command, "-"], input=text, capture_output=True, text=True, cwd=cwd,
            timeout=timeout, check=False)
        findings = json.loads(proc.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    markers = []
    for item in findings:
        code = item.get("code") or "syntax"
        start, end = item.get("location") or {}, item.get("end_location") or {}
        markers.append({
            "line": int(start.get("row", 1)), "column": int(start.get("column", 1)),
            "end_line": int(end.get("row", start.get("row", 1))),
            "end_column": int(end.get("column", start.get("column", 1) + 1)),
            "message": f"{code}: {item.get('message', '')}", "source": "ruff",
            "severity": "error" if code in ("syntax", "invalid-syntax") or code.startswith("E9")
            else "warning",
        })
    return markers


__all__ = ["complete", "hover", "ruff_binary", "ruff_markers", "signature"]
