"""Tools exposed to the AI model, generated from the command registry (rule R8).

Analysis and inspection tools run without confirmation by default (``[ai] auto_execute =
"read_only"``). Tools that write files or run user code always require the user's consent.
The model only receives summaries (values, warnings), never the raw samples.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..core.registry import Command, commands
from ..core.result import Result, jsonable
from ..core.session import Session
from .providers import ToolSpec


@dataclass
class Tool:
    spec: ToolSpec
    func: Callable[[dict], Any]
    confirm: bool = False


def summarize(result: Result, index: int | None = None) -> dict:
    """Compact, serializable summary of a result for the model."""
    out = {
        "result_index": index,
        "kind": result.kind,
        "title": result.title,
        "values": {k: (f"{v.text()}" + (f" ({result.values[k + '_phys'].text()})"
                                        if k + "_phys" in result.values else ""))
                   for k, v in result.values.items() if not k.endswith("_phys")},
        "warnings": result.warnings,
    }
    for name, rows in result.tables.items():
        out[f"table_{name}"] = jsonable(rows[:20])
    return out


def _signal_args(cmd: Command, args: dict) -> tuple[list[str], dict]:
    args = dict(args)
    keys = ["signal"] if cmd.n_signals == 1 else [f"signal{i + 1}" for i in range(cmd.n_signals)]
    signals = [args.pop(k) for k in keys if k in args]
    return signals, args


def build_tools(session: Session) -> dict[str, Tool]:
    """Every tool available to the assistant."""
    from .. import api

    tools: dict[str, Tool] = {}

    for cmd in commands():
        def run(args: dict, cmd: Command = cmd) -> dict:
            signals, params = _signal_args(cmd, args)
            params.pop("report", None)
            result = api.run(cmd.name, *signals, show=True, **params)
            return summarize(result, len(session.results))

        doc = (cmd.func.__doc__ or "").strip().split("\n\n")[0]
        description = cmd.description + (". " + " ".join(doc.split()) if doc else "")
        tools[cmd.name] = Tool(ToolSpec(cmd.name, description[:1000], cmd.schema()), run,
                               confirm=not cmd.read_only)

    def list_signals(args: dict) -> Any:
        return session.list_rows()

    def signal_info(args: dict) -> Any:
        return jsonable(session.get_signal(args["signal"]).to_dict())

    def list_results(args: dict) -> Any:
        return [{"result_index": i, "kind": r.kind, "title": r.title}
                for i, r in enumerate(session.results, start=1)]

    def get_result(args: dict) -> Any:
        index = int(args.get("index") or len(session.results))
        return summarize(session.results[index - 1], index)

    def load_file(args: dict) -> Any:
        options = dict(args.get("options") or {})
        loaded = api.load(args["path"], **options)
        loaded = loaded if isinstance(loaded, list) else [loaded]
        return [{"name": s.name, "title": s.title, "id": s.id} for s in loaded]

    def sds_channels(args: dict) -> Any:
        return api.sds_channels(args["folder"])

    def load_sds(args: dict) -> Any:
        options = {k: args[k] for k in ("gaps", "unit", "sensitivity") if args.get(k) is not None}
        loaded = api.load_sds(args["folder"], args.get("channel") or "*", args.get("starttime"),
                              args.get("endtime"), **options)
        loaded = loaded if isinstance(loaded, list) else [loaded]
        return [{"name": s.name, "title": s.title, "id": s.id, "start": str(s.starttime),
                 "duration_s": s.duration, "gaps": len(s.gaps)} for s in loaded]

    def make_signal(args: dict, func: Callable[..., Any]) -> Any:
        args = dict(args)
        sig = func(name=args.pop("name", None), **args)
        return {"name": sig.name, "title": sig.title, "id": sig.id}

    def run_script(args: dict) -> Any:
        from ..scripts import run_script as run

        result = run(args["name"], *args.get("signals", []), show=True,
                     **dict(args.get("params") or {}))
        return summarize(result, len(session.results))

    def make_report(args: dict) -> Any:
        last = int(args.get("last") or 1)
        path = api.report(session.results[-last:], title=args.get("title"))
        return {"report": str(path)}

    def list_scripts(args: dict) -> Any:
        from ..scripts import list_scripts as ls

        return [{"name": n, "description": d} for n, d in ls()]

    obj = {"type": "object", "additionalProperties": False}
    signal = {"type": "string", "description": "Signal name (S1...)"}
    extra = [
        ("list_signals", "List the signals of the session", {**obj, "properties": {}},
         list_signals, False),
        ("signal_info", "Every attribute and basic statistics of one signal",
         {**obj, "properties": {"signal": signal}, "required": ["signal"]}, signal_info, False),
        ("list_results", "List the results computed in the session", {**obj, "properties": {}},
         list_results, False),
        ("get_result", "Values of a result (default: the last one)",
         {**obj, "properties": {"index": {"type": "integer"}}}, get_result, False),
        ("load_file", "Load a miniSEED or text file into the session",
         {**obj, "properties": {"path": {"type": "string"},
                                "options": {"type": "object", "description": "load options"}},
          "required": ["path"]}, load_file, False),
        ("sds_channels", "Channels of the day files (NET.STA.LOC.CHA.D.YEAR.DAY) of an SDS "
         "archive folder: first and last day, missing days, size",
         {**obj, "properties": {"folder": {"type": "string"}}, "required": ["folder"]},
         sds_channels, False),
        ("load_sds", "Load channels of an SDS archive over a time window: several days merged "
         "into one signal per channel (a missing day is a gap: gaps=longest keeps the longest "
         "continuous segment, split gives one signal per segment). Useful for lnm over days",
         {**obj, "properties": {
             "folder": {"type": "string"},
             "channel": {"type": "string", "description": "NET.STA.LOC.CHA or a pattern"},
             "starttime": {"type": "string", "description": "UTC, e.g. 2026-09-21"},
             "endtime": {"type": "string", "description": "UTC, e.g. 2026-09-24"},
             "gaps": {"type": "string", "enum": ["longest", "split", "fill", "error"]},
             "unit": {"type": "string"},
             "sensitivity": {"type": "number", "description": "unit per count"}},
          "required": ["folder", "channel"]}, load_sds, False),
        ("list_scripts", "List the user scripts", {**obj, "properties": {}}, list_scripts,
         False),
        ("run_script", "Run a user script on signals (asks the user)",
         {**obj, "properties": {"name": {"type": "string"},
                                "signals": {"type": "array", "items": {"type": "string"}},
                                "params": {"type": "object"}},
          "required": ["name", "signals"]}, run_script, True),
        ("report", "Write a Quarto report of the last results (asks the user)",
         {**obj, "properties": {"title": {"type": "string"},
                                "last": {"type": "integer", "description": "number of results"}}},
         make_report, True),
    ]
    from ..synthetic import NOISE_PARAMS, SINE_PARAMS

    for tool_name, decl, func, desc in (
        ("make_sine", SINE_PARAMS, api.make_sine,
         "Create a test sine digitized by an ideal N-bit converter (amplitude as a fraction "
         "of full scale or in dBFS, optional noise, harmonics and mains line)"),
        ("make_noise", NOISE_PARAMS, api.make_noise,
         "Create a random test noise (white, pink or brown) digitized by an ideal N-bit "
         "converter"),
    ):
        props = {p.name: p.json_schema() for p in decl}
        props["name"] = {"type": "string", "description": "Session name (default: next S name)"}
        extra.append((tool_name, desc, {**obj, "properties": props},
                      functools.partial(make_signal, func=func), False))
    for name, desc, schema, func, confirm in extra:
        tools[name] = Tool(ToolSpec(name, desc, schema), func, confirm)
    return tools
