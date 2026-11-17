"""Standardized user scripts and batch processing (specification §16).

A script is a Python file in ``scripts/`` (configurable) built from the template: a
``PARAMS`` list of :class:`~onthesignal.Param`, a pure ``run(signals, **params) -> Result``
function and an optional ``plot(result, fig)`` function. Scripts are discovered
automatically, run from the console (``/run_script``), in batches (``/batch``), or standalone
(``python scripts/name.py --files ... --out results.csv``).
"""

from __future__ import annotations

import argparse
import csv
import glob
import importlib.util
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from ..core.errors import OnTheSignalError, ParameterError
from ..core.params import Param, resolve_params
from ..core.result import Result, jsonable
from ..core.session import get_session
from ..core.signal import Signal

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "script_template.py"


@dataclass
class Script:
    """A loaded user script."""

    name: str
    path: Path
    module: ModuleType
    params: tuple[Param, ...]
    description: str

    @property
    def run(self) -> Callable[..., Result]:
        return self.module.run

    @property
    def plot(self) -> Callable | None:
        return getattr(self.module, "plot", None)


def scripts_dir() -> Path:
    """Folder of the user scripts (``[paths] scripts``, default ``scripts/``)."""
    return Path(get_session().config.get("paths.scripts", "scripts"))


def script_path(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ParameterError(f"Invalid script name {name!r} (letters, digits, underscores)")
    return scripts_dir() / f"{name}.py"


def describe_file(path: Path) -> str:
    """``Description :`` line of the script header."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:20]:
            match = re.match(r"\s*Description\s*:\s*(.+)", line)
            if match:
                return match.group(1).strip()
    except OSError:
        pass
    return ""


def list_scripts() -> list[tuple[str, str]]:
    """Available scripts as ``(name, description)``."""
    folder = scripts_dir()
    if not folder.is_dir():
        return []
    return [(p.stem, describe_file(p)) for p in sorted(folder.glob("*.py"))
            if not p.name.startswith("_")]


def create_script(name: str) -> Path:
    """Create ``scripts/<name>.py`` from the template (unless it exists) and return its path."""
    path = script_path(name)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        local = Path.cwd() / "templates" / "script_template.py"
        source = (local if local.is_file() else TEMPLATE).read_text(encoding="utf-8")
        path.write_text(source.replace("my_analysis", name), encoding="utf-8")
    return path


def check_syntax(path: Path) -> str | None:
    """Syntax error message of a script, or ``None``."""
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    except SyntaxError as exc:
        return f"{path.name}, line {exc.lineno}: {exc.msg}"
    return None


def load_script(name: str) -> Script:
    """Import ``scripts/<name>.py`` and check that it follows the template."""
    path = script_path(name)
    if not path.is_file():
        raise ParameterError(f"Script not found: {path} (create it with /edit_script {name})")
    error = check_syntax(path)
    if error:
        raise ParameterError(f"Syntax error in {error}")
    spec = importlib.util.spec_from_file_location(f"onthesignal_user_scripts.{name}", path)
    if spec is None or spec.loader is None:
        raise ParameterError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ParameterError(f"Error while importing {path.name}: {exc}") from exc
    if not callable(getattr(module, "run", None)):
        raise ParameterError(f"{path.name} has no run(signals, **params) function")
    params = tuple(getattr(module, "PARAMS", ()))
    if not all(isinstance(p, Param) for p in params):
        raise ParameterError(f"PARAMS of {path.name} must be a list of Param")
    return Script(name, path, module, params, describe_file(path))


def run_script(name: str, *signals: Any, show: bool | None = None, save: str | None = None,
               **params: Any) -> Result:
    """Run a user script on signals of the session and display its result."""
    from ..api import display

    session = get_session()
    script = load_script(name)
    sigs = [session.get_signal(s) for s in signals]
    if not sigs:
        raise ParameterError(f"Script {name} needs at least one signal")
    p = resolve_params(script.params, params, sigs[0], session.config, command=name)
    result = script.run(sigs, **p)
    if not isinstance(result, Result):
        raise ParameterError(f"run() of {name} must return a Result")
    if script.plot is not None:
        from ..plot import plotter

        plotter(result.kind)(script.plot)
    session.add_result(result)
    display(result, show, save)
    return result


# ---------------------------------------------------------------------------------- batches
def expand_files(patterns: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) or ([pattern] if Path(pattern).exists() else [])
        files.extend(Path(m) for m in matches)
    if not files:
        raise ParameterError(f"No file matches {' '.join(patterns)}")
    return files


def batch(target: str | Callable, files: Sequence[str], out: str | Path | None = None,
          params_decl: Sequence[Param] | None = None, read_options: dict | None = None,
          **params: Any) -> list[dict]:
    """Run an analysis or a script on every signal of every file and aggregate the values.

    Parameters
    ----------
    target : str or callable
        Registered analysis (``noise``), script name, or a ``run(signals, **params)``
        function.
    files : sequence of str
        Files or glob patterns.
    out : str or Path, optional
        Output table (``.csv`` or ``.json``).
    read_options : dict, optional
        Options passed to the file reader (``unit``, ``sensitivity``, ``n_channels``...).

    Returns
    -------
    list of dict
        One row per file and signal; failures are recorded in an ``error`` column and do not
        stop the batch.
    """
    from ..core.registry import get_command
    from ..io import read

    if callable(target):
        func, decl, name = target, list(params_decl or ()), getattr(target, "__name__", "run")

        def runner(sig: Signal, p: dict) -> Result:
            return func([sig], **p)
    else:
        try:
            cmd = get_command(target)
            decl, name = [q for q in cmd.params if q.name != "report"], cmd.name

            def runner(sig: Signal, p: dict) -> Result:
                return cmd.func(sig, **p)
        except ParameterError:
            script = load_script(target)
            decl, name = list(script.params), script.name

            def runner(sig: Signal, p: dict) -> Result:
                return script.run([sig], **p)

    rows: list[dict] = []
    for path in expand_files(files):
        try:
            signals = read(path, **(read_options or {}))
        except OnTheSignalError as exc:
            rows.append({"file": str(path), "signal": "", "error": str(exc)})
            continue
        for sig in signals:
            row: dict[str, Any] = {"file": str(path), "signal": sig.id}
            try:
                p = resolve_params(decl, params, sig, get_session().config, command=name)
                result = runner(sig, p)
                for key, value in result.values.items():
                    row[key] = jsonable(value.value)
                    if value.unit:
                        row.setdefault("units", {})[key] = value.unit
                row["warnings"] = " | ".join(result.warnings)
            except Exception as exc:  # one failing signal must not stop the batch
                row["error"] = str(exc)
            rows.append(row)
    if out is not None:
        write_table(rows, out)
    return rows


def write_table(rows: list[dict], out: str | Path) -> Path:
    """Write batch rows to CSV (units in the header) or JSON."""
    out = Path(out)
    if out.suffix.lower() == ".json":
        out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        return out
    units: dict[str, str] = {}
    keys: list[str] = []
    for row in rows:
        units.update(row.get("units", {}))
        for k in row:
            if k != "units" and k not in keys:
                keys.append(k)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([f"{k} [{units[k]}]" if k in units else k for k in keys])
        for row in rows:
            writer.writerow([
                ", ".join(map(str, row[k])) if isinstance(row.get(k), list) else row.get(k, "")
                for k in keys
            ])
    return out


def main(run: Callable, params: Sequence[Param] = (), plot: Callable | None = None,
         argv: Sequence[str] | None = None) -> int:
    """Command-line entry point of a standalone script built from the template."""
    parser = argparse.ArgumentParser(description=(sys.modules["__main__"].__doc__ or "").strip(),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--files", nargs="+", required=True, help="Input files or glob patterns")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                        help="Parameter value (repeatable)")
    parser.add_argument("--out", help="Output table (.csv or .json)")
    parser.add_argument("--unit", help="Physical unit of the signals")
    parser.add_argument("--sensitivity", type=float, help="Physical unit per count")
    parser.add_argument("--n-channels", type=int, help="Number of data columns (text files)")
    parser.add_argument("--fs", type=float, help="Sampling rate (text files without time column)")
    args = parser.parse_args(argv)
    values = {}
    for item in args.param:
        if "=" not in item:
            parser.error(f"--param expects NAME=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        values[key.strip()] = value.strip()
    options = {k: v for k, v in {"unit": args.unit, "sensitivity": args.sensitivity,
                                 "n_channels": args.n_channels, "fs": args.fs}.items()
               if v is not None}
    rows = batch(run, args.files, args.out, params_decl=params, read_options=options, **values)
    for row in rows:
        status = row.get("error") or ", ".join(
            f"{k}={v}" for k, v in row.items()
            if k not in ("file", "signal", "units", "warnings")
        )[:200]
        print(f"{row['file']} {row['signal']}: {status}")
    if args.out:
        print(f"Results written to {args.out}")
    return 0 if not any("error" in r for r in rows) else 1
