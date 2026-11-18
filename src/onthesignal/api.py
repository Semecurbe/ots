"""Public API: the functions used in scripts and in the console (services layer).

Analysis functions are generated from the command registry: ``noise(S1, fmax=50)`` resolves
the signal, applies the parameter defaults (call > signal attribute > configuration >
declared default), runs the pure computation, stores the result in the current session,
displays it when appropriate and returns it.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import (
    analysis,  # noqa: F401  (registers the analysis commands)
    synthetic,
)
from .core.errors import ParameterError
from .core.params import resolve_params
from .core.registry import Command, get_command
from .core.result import Curve, Result
from .core.session import Session, get_session
from .core.signal import Signal
from .core.units import COUNTS, fmt_num, pretty_unit
from .io import read
from .processing.spectral import minmax_envelope


# ---------------------------------------------------------------------------------- display
def display(obj: Any, show: bool | None = None, save: str | None = None) -> None:
    """Display a result through the session display handler (console) or plain matplotlib."""
    session = get_session()
    if show is None:
        show = session.interactive
    if session.display_handler is not None:
        session.display_handler(obj, show, save)
        return
    if save:
        fig = obj.plot()
        if fig is not None:
            fig.savefig(save, dpi=150, bbox_inches="tight")
    if show:
        print(obj.to_text() if isinstance(obj, Result) else str(obj))
        import matplotlib.pyplot as plt

        fig = obj.plot(plt.figure(figsize=(10, 6)))
        if fig is not None:
            plt.show()


# ---------------------------------------------------------------------------------- commands
def run(name: str, *signals: Any, show: bool | None = None, save: str | None = None,
        **params: Any) -> Result:
    """Run the registered command ``name`` on ``signals`` (objects or names)."""
    cmd = get_command(name)
    session = get_session()
    sigs = [session.get_signal(s) for s in signals]
    main, extra = sigs[: cmd.n_signals], sigs[cmd.n_signals :]
    if len(main) < cmd.n_signals:
        raise ParameterError(f"{cmd.name} needs {cmd.n_signals} signal(s), got {len(main)}")
    if len(extra) > len(cmd.signal_params):
        raise ParameterError(f"Too many signals for {cmd.name}")
    for pname, s in zip(cmd.signal_params, extra, strict=False):
        params[pname] = s
    for pname in cmd.signal_params:
        if params.get(pname) is not None:
            params[pname] = session.get_signal(params[pname])
    declared = [q for q in cmd.params if q.name != "report"]
    want_report = bool(params.pop("report", False)) and len(declared) < len(cmd.params)
    p = resolve_params(declared, params, signal=main[0] if main else None,
                       config=session.config, command=cmd.name)
    t0 = time.perf_counter()
    result = cmd.func(*main, **p)
    result.meta["compute_time_s"] = round(time.perf_counter() - t0, 4)
    session.add_result(result)
    session.history.append(f"{cmd.name}({', '.join(s.name or s.id for s in main)})")
    display(result, show, save)
    if want_report:
        path = report([result])
        print(f"Report written to {path}")
    return result


def _make(name: str) -> Callable[..., Result]:
    cmd: Command = get_command(name)

    def api_function(*signals: Any, show: bool | None = None, save: str | None = None,
                     **params: Any) -> Result:
        return run(cmd.name, *signals, show=show, save=save, **params)

    params_doc = "\n".join(
        f"    {q.name} : {q.type.__name__}, default {q.describe_default()}"
        + (f" [{q.unit}]" if q.unit else "") + f"\n        {q.help}"
        for q in cmd.params
    )
    api_function.__name__ = api_function.__qualname__ = cmd.name
    api_function.__doc__ = (
        (inspect.cleandoc(cmd.func.__doc__ or cmd.description))
        + "\n\nParameters\n----------\n"
        + params_doc
        + "\n    show : bool, optional\n        Display the result (default: in the console)."
        + "\n    save : str, optional\n        Save the figure to this file."
    )
    sig_params = [
        inspect.Parameter("signal" if cmd.n_signals == 1 else f"signal{i + 1}",
                          inspect.Parameter.POSITIONAL_ONLY)
        for i in range(cmd.n_signals)
    ]
    sig_params += [
        inspect.Parameter(q.name, inspect.Parameter.KEYWORD_ONLY, default=q.default)
        for q in cmd.params
    ]
    sig_params += [
        inspect.Parameter("show", inspect.Parameter.KEYWORD_ONLY, default=None),
        inspect.Parameter("save", inspect.Parameter.KEYWORD_ONLY, default=None),
    ]
    api_function.__signature__ = inspect.Signature(sig_params)  # type: ignore[attr-defined]
    return api_function


noise = _make("noise")
noise_fft = _make("noise_fft")
noise_dsp = _make("noise_dsp")
lnm = _make("lnm")
sinefit = _make("sinefit")
sinad = _make("sinad")
sfdr = _make("sfdr")
thd = _make("thd")
dynamic = _make("dynamic")
frequency = _make("frequency")
period = _make("period")
delay50 = _make("delay50")
coherence = _make("coherence")
spectrogram = _make("spectrogram")
SINAD, SFDR, THD = sinad, sfdr, thd


# ---------------------------------------------------------------------------------- signals
def load(path: str | Path, fmt: str | None = None, name: str | Sequence[str] | None = None,
         **options: Any) -> Signal | list[Signal]:
    """Load a file and register its signals in the session (``S1``, ``S2``... by default).

    Parameters
    ----------
    path : str or Path
        miniSEED file (``.mseed``), text file (``.txt``, ``.csv``...) or any ObsPy format.
    fmt : str, optional
        Force the format (``mseed`` or ``txt``).
    name : str or list of str, optional
        Session name(s) of the loaded signal(s).
    **options
        Format options: ``select``, ``starttime``, ``endtime``, ``gaps`` for miniSEED;
        ``n_channels``, ``time_col``, ``fs``, ``delimiter``, ``decimal``... for text files;
        ``title`` (default: file name without extension), ``unit``, ``sensitivity``,
        ``full_scale``, ``metadata`` for both.

    Returns
    -------
    Signal or list of Signal
    """
    session = get_session()
    signals = read(path, fmt, **options)
    if name is None:
        names: list[str | None] = [None] * len(signals)
    elif isinstance(name, str):
        names = [name] if len(signals) == 1 else [f"{name}_{i + 1}" for i in range(len(signals))]
    else:
        names = list(name)
        if len(names) != len(signals):
            raise ParameterError(f"{len(signals)} signals loaded but {len(names)} names given")
    for sig, n in zip(signals, names, strict=True):
        session.add_signal(sig, n)
    session.history.append(f"load({str(path)!r})")
    return signals[0] if len(signals) == 1 else signals


def _registering(func: Callable[..., Signal]) -> Callable[..., Signal]:
    """Session version of a signal factory: the signal is registered as ``S1``, ``S2``..."""
    base = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(*args: Any, name: str | None = None, **kwargs: Any) -> Signal:
        sig = func(*args, **kwargs)
        session = get_session()
        session.add_signal(sig, name)
        call = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
        session.history.append(f"{func.__name__}({', '.join(call)})")
        return sig

    params = [*base.parameters.values(),
              inspect.Parameter("name", inspect.Parameter.KEYWORD_ONLY, default=None)]
    wrapper.__signature__ = base.replace(parameters=params)  # type: ignore[attr-defined]
    doc = inspect.cleandoc(func.__doc__ or "")
    wrapper.__doc__ = doc.replace(
        "\n\nReturns\n",
        "\nname : str, optional\n    Session name (default: next free name, ``S1``, ``S2``...)."
        "\n\nReturns\n", 1)
    return wrapper


make_sine = _registering(synthetic.make_sine)
make_noise = _registering(synthetic.make_noise)


def list_sig() -> None:
    """Print the table of the signals of the session."""
    session = get_session()
    if session.display_handler is not None:
        session.display_handler("signals", True, None)
    else:
        print(session.list_text())


def list_res() -> None:
    """Print the results computed in the session."""
    session = get_session()
    if not session.results:
        print("No result yet.")
    for i, r in enumerate(session.results, start=1):
        print(f"{i:3d}. {r.title or r.kind}")


def rename_sig(old: str, new: str) -> None:
    """Rename a signal of the session."""
    get_session().rename_signal(old, new)


def rm_sig(name: str) -> None:
    """Remove a signal from the session."""
    get_session().remove_signal(name)


def signal_result(signal: Signal, units: str = "physical", t_start: Any = None,
                  t_end: Any = None, max_points: int = 20000) -> Result:
    """Time series of a signal as a :class:`Result` (decimated for display)."""
    sig = signal.slice(t_start, t_end) if (t_start is not None or t_end is not None) else signal
    physical = units == "physical" and sig.unit != COUNTS
    y = sig.to_physical() if physical else sig.data
    idx, values = minmax_envelope(y, max_points)
    t = sig.times("matplotlib")[idx]
    r = Result("signal", title=f"{sig.label} — {sig.starttime}",
               signals=[sig.identity()], params={"units": units})
    unit = sig.unit if physical else COUNTS
    r.curves["signal"] = Curve(t, values, label=sig.name or sig.id, x_label="Time (UTC)",
                               y_label="Amplitude", y_unit=pretty_unit(unit))
    st = sig.stats()
    factor = abs(sig.sensitivity) if physical else 1.0
    r.add("duration", sig.duration, "s", "Duration", digits=6)
    r.add("std", st["std"] * factor, unit, "Standard deviation")
    r.add("pp", st["pp"] * factor, unit, "Peak-to-peak")
    if idx.size < sig.npts:
        r.extra["decimated"] = f"min/max envelope of {fmt_num(sig.npts)} samples"
    return r


def show(signal: Signal | str, units: str = "physical", t_start: Any = None, t_end: Any = None,
         save: str | None = None) -> Result:
    """Plot the time series of a signal (always displayed)."""
    sig = get_session().get_signal(signal)
    r = signal_result(sig, units, t_start, t_end)
    display(r, show=True, save=save)
    return r


# ---------------------------------------------------------------------------------- SeedLink
def _argv(**options: Any) -> list[str]:
    argv: list[str] = []
    for key, value in options.items():
        if value is None or value is False:
            continue
        flag = f"--{key.replace('_', '-')}"
        if value is True:
            argv.append(flag)
        elif isinstance(value, (list, tuple)):
            argv += [flag, *map(str, value)]
        else:
            argv += [flag, str(value)]
    return argv


def acquire(server: str, network: str, station: str, channels: Sequence[str] | None = None,
            duration: float | None = None, outdir: str = ".", load: bool = True,
            **options: Any) -> None:
    """SeedLink acquisition with live progress (same options as ``/acq``)."""
    from .seedlink.acquisition import main

    main(_argv(server=server, network=network, station=station, channels=channels,
               duration=duration, outdir=outdir, load=load, **options), session=get_session())


def realtime(server: str, network: str, station: str, channels: Sequence[str],
             mode: str = "stats", **options: Any) -> None:
    """Live statistics (mean, std, p-p) and FFT / Welch PSD of SeedLink streams (``/rt``)."""
    from .seedlink.realtime import main

    main(_argv(server=server, network=network, station=station, channels=channels, mode=mode,
               **options), session=get_session())


# ---------------------------------------------------------------------------------- reports
def report(results: Sequence[Result] | Result | None = None, title: str | None = None,
           output_dir: str | Path | None = None, formats: Sequence[str] = ("html", "pdf"),
           render: bool = False, author: str | None = None) -> Path:
    """Generate a Quarto report (``report.qmd`` + figures) from results.

    Without ``results``, the results of the last analysis command are used.
    """
    from .report import generate_report

    session = get_session()
    if results is None:
        if not session.results:
            raise ParameterError("No result to report: run an analysis first")
        results = [session.results[-1]]
    elif isinstance(results, Result):
        results = [results]
    return generate_report(list(results), title=title, output_dir=output_dir, formats=formats,
                           render=render, author=author, config=session.config)


__all__ = [
    "SFDR",
    "SINAD",
    "THD",
    "Session",
    "acquire",
    "coherence",
    "delay50",
    "display",
    "dynamic",
    "frequency",
    "period",
    "realtime",
    "spectrogram",
    "get_session",
    "list_res",
    "list_sig",
    "lnm",
    "load",
    "make_noise",
    "make_sine",
    "noise",
    "noise_dsp",
    "noise_fft",
    "rename_sig",
    "report",
    "rm_sig",
    "run",
    "sfdr",
    "show",
    "signal_result",
    "sinad",
    "sinefit",
    "thd",
]
