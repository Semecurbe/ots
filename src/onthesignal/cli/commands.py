"""Slash commands of the console (specification §15.4).

Analysis commands (``/noise``, ``/lnm``...) come from the command registry; the commands
below manage signals, reports, scripts, acquisition and the console itself.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .. import api
from ..core.errors import ParameterError
from ..core.params import Param, resolve_params
from ..core.registry import Command, commands, get_command
from ..io import GAP_POLICIES, detect_format
from ..synthetic import NOISE_PARAMS, SINE_PARAMS

if TYPE_CHECKING:
    from .console import OnTheSignalConsole


@dataclass
class Slash:
    name: str
    func: Callable[..., None]
    description: str
    usage: str = ""
    category: str = "General"
    complete: str = ""  # "signal", "file", "script", "command"


SLASH: dict[str, Slash] = {}
ALIASES = {"exit": "quit", "q": "quit", "ls": "list", "h": "help", "?": "help"}
CATEGORY_TITLES = {
    "noise": "Noise analyses",
    "sine": "Sine analyses",
    "measure": "Measurements",
    "spectral": "Spectral analyses",
}


def slash(name: str, description: str, usage: str = "", category: str = "General",
          complete: str = "") -> Callable[[Callable], Callable]:
    def decorator(func: Callable) -> Callable:
        SLASH[name] = Slash(name, func, description, usage or f"/{name}", category, complete)
        return func

    return decorator


def parse(text: str) -> tuple[str, list[str], dict[str, str], set[str]]:
    """Split ``/name a b key=value --flag`` into its parts."""
    try:
        tokens = shlex.split(text.lstrip("/"))
    except ValueError as exc:
        raise ParameterError(f"Cannot parse the command: {exc}") from exc
    if not tokens:
        return "help", [], {}, set()
    name, positional, kv, flags = tokens[0], [], {}, set()
    for tok in tokens[1:]:
        if tok.startswith("--"):
            key, _, value = tok[2:].partition("=")
            if value:
                kv[key.replace("-", "_")] = value
            else:
                flags.add(key)
        elif "=" in tok and tok.split("=", 1)[0].isidentifier():
            key, value = tok.split("=", 1)
            kv[key] = value
        else:
            positional.append(tok)
    return ALIASES.get(name, name), positional, kv, flags


def command_list() -> list[tuple[str, str]]:
    """Every command with its description (built-in and registered analyses)."""
    items = [(s.name, s.description) for s in SLASH.values()]
    items += [(c.name, c.description) for c in commands()]
    return sorted(items)


def execute(console: OnTheSignalConsole, text: str) -> None:
    name, positional, kv, flags = parse(text)
    if name in SLASH:
        SLASH[name].func(console, positional, kv, flags)
        return
    try:
        cmd = get_command(name)
    except ParameterError:
        raise ParameterError(f"Unknown command /{name} — type / or /help") from None
    run_analysis(console, cmd, positional, kv, flags)


# ---------------------------------------------------------------------------------- analyses
def run_analysis(console: OnTheSignalConsole, cmd: Command, positional: list[str],
                 kv: dict[str, str], flags: set[str]) -> None:
    session = console.session
    names = list(positional)
    last = list(session.signals)[-1] if session.signals else ""
    while len(names) < cmd.n_signals:
        label = "Signal" if cmd.n_signals == 1 else f"Signal {len(names) + 1}"
        answer = console.ask(label, last).strip() or last
        if not answer:
            raise ParameterError("No signal given")
        names.append(answer)
    signals = [session.get_signal(n) for n in names[: cmd.n_signals]]
    params: dict[str, Any] = dict(kv)
    display_opts = {k: params.pop(k) for k in ("show", "save") if k in params}
    if not params and "defaults" not in flags and console.forms:
        from .forms import ask_params

        declared = [p for p in cmd.params if p.name != "report"]
        defaults = resolve_params(declared, {}, signals[0], session.config, cmd.name)
        params = ask_params(cmd.params, defaults, console.ask, skip=cmd.signal_params)
    show = display_opts.get("show")
    api.run(cmd.name, *names, show=None if show is None else show.lower() != "false",
            save=display_opts.get("save"), **params)


# ---------------------------------------------------------------------------------- signals
LOAD_OPTIONS = (
    Param("fmt", str, None, nullable=True),
    Param("name", str, None, nullable=True),
    Param("title", str, None, nullable=True),
    Param("select", str, None, nullable=True),
    Param("gaps", str, "longest", choices=GAP_POLICIES),
    Param("starttime", object, None),
    Param("endtime", object, None),
    Param("unit", str, None, nullable=True),
    Param("sensitivity", float, None, nullable=True),
    Param("full_scale", float, None, nullable=True),
    Param("n_channels", int, None, nullable=True, min=1),
    Param("time_col", int, None, nullable=True, min=0),
    Param("fs", float, None, nullable=True, min=0.0),
    Param("delimiter", str, None, nullable=True),
    Param("decimal", str, ".", choices=(".", ",")),
    Param("skiprows", int, None, nullable=True, min=0),
    Param("time_format", str, "relative", choices=("relative", "epoch", "iso")),
    Param("resample", bool, False),
)


@slash("load", "Load a miniSEED or text file", "/load <file> [key=value...]",
       "Signals", "file")
def cmd_load(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], flags: set[str]
             ) -> None:
    path = pos[0] if pos else console.ask("File", "").strip()
    if not path:
        raise ParameterError("No file given")
    decl = {p.name: p for p in LOAD_OPTIONS}
    unknown = set(kv) - set(decl)
    if unknown:
        raise ParameterError(f"Unknown load option(s): {', '.join(sorted(unknown))}")
    options = {k: decl[k].coerce(v) for k, v in kv.items()}
    if detect_format(path) == "txt" and options.get("n_channels") is None and console.forms:
        options["n_channels"] = decl["n_channels"].coerce(console.ask("Number of channels", "1"))
        tc = console.ask("Time column index (none = no time column)", "none")
        options["time_col"] = decl["time_col"].coerce(tc or "none")
        if options["time_col"] is None:
            options["fs"] = decl["fs"].coerce(console.ask("Sampling rate (Hz)", ""))
        options["decimal"] = decl["decimal"].coerce(console.ask("Decimal separator", ".") or ".")
    fmt = options.pop("fmt", None)
    name = options.pop("name", None)
    signals = api.load(path, fmt=fmt, name=name, **options)
    console.sync()
    loaded = signals if isinstance(signals, list) else [signals]
    console.display.info(f"Loaded {len(loaded)} signal(s): "
                         + ", ".join(f"{s.name} ({s.id})" for s in loaded))


def _make_signal(console: OnTheSignalConsole, func: Callable[..., Any],
                 decl: tuple[Param, ...], pos: list[str], kv: dict[str, str],
                 flags: set[str]) -> None:
    """Create a test signal: positional values follow the declaration order."""
    names = [p.name for p in decl]
    if len(pos) > len(names):
        raise ParameterError(f"Too many values: {' '.join(pos)}")
    given = {**dict(zip(names, pos, strict=False)), **kv}
    name = given.pop("name", None)
    by_name = {p.name: p for p in decl}
    unknown = set(given) - set(by_name)
    if unknown:
        raise ParameterError(f"Unknown parameter(s): {', '.join(sorted(unknown))}. "
                             f"Valid parameters: {', '.join(names)}")
    params = {k: by_name[k].coerce(v) for k, v in given.items()}
    if not given and "defaults" not in flags and console.forms:
        from .forms import ask_params

        params = ask_params(decl, {}, console.ask)
    sig = func(name=name, **params)
    console.sync()
    console.display.info(f"Created {sig.name}: {sig.title}")


@slash("make_sine", "Create a test sine (ideal N-bit digitizer)",
       "/make_sine [frequency] [ratio] [bits] [key=value...]", "Signals")
def cmd_make_sine(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str],
                  flags: set[str]) -> None:
    _make_signal(console, api.make_sine, SINE_PARAMS, pos, kv, flags)


@slash("make_noise", "Create a random test noise (ideal N-bit digitizer)",
       "/make_noise [rms] [color] [bits] [key=value...]", "Signals")
def cmd_make_noise(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str],
                   flags: set[str]) -> None:
    _make_signal(console, api.make_noise, NOISE_PARAMS, pos, kv, flags)


@slash("list", "List the signals of the session", "/list", "Signals")
def cmd_list(console: OnTheSignalConsole, *_: Any) -> None:
    api.list_sig()


@slash("info", "Show every parameter of a signal", "/info <S>", "Signals", "signal")
def cmd_info(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    for name in pos or [console.ask("Signal", "")]:
        console.display.info(console.session.get_signal(name).describe())


@slash("show", "Plot the time series of a signal", "/show <S> [units=counts] [save=file.png]",
       "Signals", "signal")
def cmd_show(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], *_: Any) -> None:
    name = pos[0] if pos else console.ask("Signal", "")
    api.show(name, units=kv.get("units", "physical"), t_start=kv.get("t_start"),
             t_end=kv.get("t_end"), save=kv.get("save"))


@slash("rename", "Rename a signal", "/rename <old> <new>", "Signals", "signal")
def cmd_rename(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    if len(pos) != 2:
        raise ParameterError("Usage: /rename <old> <new>")
    console.ns.pop(pos[0], None)
    api.rename_sig(pos[0], pos[1])
    console.ns[pos[1]] = console.session.signals[pos[1]]
    console.sync()


@slash("rm", "Remove signals from the session", "/rm <S> [S...]", "Signals", "signal")
def cmd_rm(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    for name in pos:
        api.rm_sig(name)
        console.ns.pop(name, None)
    console.sync()


@slash("export", "Export a signal (miniSEED, text, CSV)", "/export <S> <file>", "Signals", "file")
def cmd_export(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    if len(pos) != 2:
        raise ParameterError("Usage: /export <S> <file.mseed|file.txt|file.csv>")
    path = console.session.get_signal(pos[0]).save(pos[1])
    console.display.info(f"Written {path}")


# ---------------------------------------------------------------------------------- results
@slash("results", "List the results of the session", "/results", "Reports")
def cmd_results(console: OnTheSignalConsole, *_: Any) -> None:
    api.list_res()


@slash("report", "Quarto report of the last results", "/report [n|all] [title=...] "
       "[render=true] [formats=html,pdf]", "Reports")
def cmd_report(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], *_: Any) -> None:
    results = console.session.results
    if not results:
        raise ParameterError("No result to report: run an analysis first")
    which = pos[0] if pos else "1"
    selected = results if which == "all" else results[-int(which):]
    formats = [f.strip() for f in kv.get("formats", "html,pdf").split(",") if f.strip()]
    render = Param("render", bool, False).coerce(kv.get("render", "false"))
    path = api.report(selected, title=kv.get("title"), formats=formats, render=render,
                      author=kv.get("author"))
    console.display.info(f"Report written to {path}")
    if render:
        outputs = [path.with_suffix(s) for s in (".html", ".pdf") if path.with_suffix(s).exists()]
        console.display.info("Rendered: " + ", ".join(str(o) for o in outputs))


# ---------------------------------------------------------------------------------- scripts
@slash("scripts", "List the user scripts", "/scripts", "Scripts")
def cmd_scripts(console: OnTheSignalConsole, *_: Any) -> None:
    from ..scripts import list_scripts, scripts_dir

    items = list_scripts()
    if not items:
        console.display.info(f"No script in {scripts_dir()}/ — create one with /edit_script <name>")
    for name, desc in items:
        console.display.info(f"  {name:<24} {desc}")


@slash("edit_script", "Create or edit a script with the configured editor (vi, nano)",
       "/edit_script <name>", "Scripts", "script")
def cmd_edit_script(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    from ..scripts import check_syntax, create_script
    from .editor import open_in_editor

    name = pos[0] if pos else console.ask("Script name", "").strip()
    path = create_script(name)
    while True:
        open_in_editor(path, console.session.config)
        error = check_syntax(path)
        if error is None:
            console.display.info(f"{path} saved — run it with /run_script {name} <S>")
            return
        console.display.error(f"Syntax error: {error}")
        if console.ask("Edit again? (Y/n)", "y").strip().lower() in ("n", "no", "non"):
            return


@slash("run_script", "Run a user script on signals", "/run_script <name> <S...> [key=value...]",
       "Scripts", "script")
def cmd_run_script(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], *_: Any
                   ) -> None:
    from ..scripts import run_script

    if not pos:
        raise ParameterError("Usage: /run_script <name> <S...> [key=value...]")
    save = kv.pop("save", None)
    params: dict[str, Any] = dict(kv)
    run_script(pos[0], *pos[1:], save=save, **params)


@slash("batch", "Run an analysis or a script on many files", "/batch <analysis|script> "
       "<files...> [key=value...] [out=results.csv]", "Scripts", "file")
def cmd_batch(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], *_: Any) -> None:
    from ..scripts import batch

    if len(pos) < 2:
        raise ParameterError("Usage: /batch <analysis|script> <files...> [key=value] [out=...]")
    out = kv.pop("out", None)
    read_keys = {"unit", "sensitivity", "n_channels", "time_col", "fs", "gaps", "select"}
    decl = {p.name: p for p in LOAD_OPTIONS}
    read_options = {k: decl[k].coerce(kv.pop(k)) for k in list(kv) if k in read_keys}
    params: dict[str, Any] = dict(kv)
    rows = batch(pos[0], pos[1:], out=out, read_options=read_options, **params)
    failed = sum(1 for r in rows if "error" in r)
    console.display.info(f"{len(rows)} signal(s) processed, {failed} failure(s)"
                         + (f" — table written to {out}" if out else ""))
    for r in rows:
        if "error" in r:
            console.display.error(f"  {r['file']} {r['signal']}: {r['error']}")


# ---------------------------------------------------------------------------------- acquisition
@slash("acq", "SeedLink acquisition to miniSEED (see /acq --help)",
       "/acq --server HOST --network NET --station STA [--channels ...] [--duration s] [--load]",
       "Acquisition")
def cmd_acq(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], flags: set[str]
            ) -> None:
    from ..seedlink.acquisition import main as acq_main

    argv = [*pos]
    for k, v in kv.items():
        argv += [f"--{k.replace('_', '-')}", v]
    argv += [f"--{f}" for f in sorted(flags)]
    acq_main(argv, session=console.session)
    console.sync()


@slash("rt", "Real-time statistics, FFT or PSD of SeedLink streams (see /rt --help)",
       "/rt --server HOST --network NET --station STA --channels FHZ [--mode stats|fft|dsp]",
       "Acquisition")
def cmd_rt(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], flags: set[str]
           ) -> None:
    from ..seedlink.realtime import main as rt_main

    argv = [*pos]
    for k, v in kv.items():
        argv += [f"--{k.replace('_', '-')}", *v.split()]
    argv += [f"--{f}" for f in sorted(flags)]
    rt_main(argv, session=console.session)


# ---------------------------------------------------------------------------------- console
@slash("help", "List the commands, or describe one", "/help [command]", complete="command")
def cmd_help(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    if pos:
        console.display.info(help_text(pos[0].lstrip("/")))
        return
    groups: dict[str, list[tuple[str, str]]] = {}
    for s in SLASH.values():
        groups.setdefault(s.category, []).append((s.usage, s.description))
    for c in commands():
        title = CATEGORY_TITLES.get(c.category, c.category.capitalize())
        groups.setdefault(title, []).append((f"/{c.name} <S>", c.description))
    order = ["Signals", *CATEGORY_TITLES.values(), "Reports", "Scripts", "Acquisition", "AI",
             "General"]
    for title in sorted(groups, key=lambda t: order.index(t) if t in order else 99):
        console.display.info(f"[bold]{title}[/bold]", markup=True)
        for usage, desc in groups[title]:
            console.display.info(f"  {usage.split(' ')[0]:<16} {desc}")
    console.display.info("Python expressions are also accepted: noise(S1, fmax=50), "
                         "S3 = S1 + S2, list_sig(). /help <command> for details.")


def help_text(name: str) -> str:
    name = ALIASES.get(name, name)
    if name in SLASH:
        s = SLASH[name]
        return f"/{s.name} — {s.description}\nUsage: {s.usage}"
    cmd = get_command(name)
    lines = [f"/{cmd.name} — {cmd.description}",
             f"Usage: /{cmd.name} {' '.join('<S>' for _ in range(cmd.n_signals))} "
             "[key=value ...] [--defaults] [save=file.png]   ·   Python: "
             f"{cmd.name}({', '.join('S' for _ in range(cmd.n_signals))}, key=value)",
             "", "Parameters:"]
    for p in cmd.params:
        unit = f" [{p.unit}]" if p.unit else ""
        adv = " (advanced)" if p.advanced else ""
        lines.append(f"  {p.name:<16} default {p.describe_default():<10} {p.help}{unit}{adv}")
    doc = (cmd.func.__doc__ or "").strip().split("\n\n")
    if len(doc) > 1:
        lines += ["", " ".join(line.strip() for line in doc[1].splitlines())]
    return "\n".join(lines)


@slash("config", "Show the configuration or change a value for this session",
       "/config [section.key=value]")
def cmd_config(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], *_: Any) -> None:
    config = console.session.config
    if kv:
        for key, value in kv.items():
            config.set(key, value)
        return
    for section, values in config.to_dict().items():
        console.display.info(f"[bold]\\[{section}][/bold]", markup=True)
        for key, value in values.items():
            console.display.info(f"  {key} = {value!r}")
    sources = ", ".join(str(s) for s in config.sources) or "defaults only"
    console.display.info(f"Loaded from: {sources}")


@slash("debug", "Show full tracebacks on errors", "/debug on|off")
def cmd_debug(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    console.debug = (pos[0].lower() if pos else "on") in ("on", "true", "1")
    console.display.info(f"Debug {'on' if console.debug else 'off'}")


@slash("clear", "Clear the screen", "/clear")
def cmd_clear(console: OnTheSignalConsole, *_: Any) -> None:
    console.display.console.clear()


@slash("quit", "Quit onthesignal", "/quit")
def cmd_quit(console: OnTheSignalConsole, *_: Any) -> None:
    console.running = False


# ---------------------------------------------------------------------------------- AI
@slash("ai", "Toggle the AI mode, or ask one question", "/ai [question]", "AI")
def cmd_ai(console: OnTheSignalConsole, pos: list[str], kv: dict[str, str], *_: Any) -> None:
    question = " ".join([*pos, *(f"{k}={v}" for k, v in kv.items())]).strip()
    if question:
        console.ask_ai(question)
        return
    console.mode = "python" if console.mode == "ai" else "ai"
    console.display.info(
        "AI mode: your inputs go to the assistant (/ai to come back to Python)."
        if console.mode == "ai" else "Python mode.")


@slash("init", "Summarize every signal for the AI context", "/init [folder]", "AI", "file")
def cmd_init(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    from ..ai.context import init_context

    path = init_context(console.session, pos[0] if pos else None)
    console.display.info(f"AI context written to {path}")


@slash("context", "Edit the user context file (context.md) for the AI", "/context", "AI")
def cmd_context(console: OnTheSignalConsole, *_: Any) -> None:
    from ..ai.context import edit_context_path
    from .editor import open_in_editor

    open_in_editor(edit_context_path(), console.session.config)


@slash("model", "Show or choose the AI provider and model", "/model [anthropic|openai|ollama] "
       "[model]", "AI")
def cmd_model(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    from ..ai.context import provider_label

    config = console.session.config
    if pos:
        config.set("ai.provider", pos[0].lower())
        config.set("ai.model", pos[1] if len(pos) > 1 else "")
        console.assistant = None
    console.display.info(f"AI provider: {provider_label(config)}")


@slash("ai_script", "Generate a script from a description with the AI",
       '/ai_script <name> "<description>"', "AI", "script")
def cmd_ai_script(console: OnTheSignalConsole, pos: list[str], *_: Any) -> None:
    from ..ai import get_assistant

    if len(pos) < 2:
        raise ParameterError('Usage: /ai_script <name> "<description>"')
    if console.assistant is None:
        console.assistant = get_assistant(console)
    path = console.assistant.generate_script(pos[0], " ".join(pos[1:]))
    console.display.info(f"Script written to {path} — review it with /edit_script {pos[0]} "
                         "before running it")


@slash("gen_ai_doc", "Regenerate docs/ai/agent.md from the commands and docstrings",
       "/gen_ai_doc", "AI")
def cmd_gen_ai_doc(console: OnTheSignalConsole, *_: Any) -> None:
    from ..ai.context import write_agent_doc

    console.display.info(f"Written {write_agent_doc()}")
