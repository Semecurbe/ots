"""Context given to the AI model: rules, ``agent.md``, user context, ``/init`` summary.

``agent.md`` is generated from the command registry and the docstrings, so it always matches
the code (specification §17.2).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .._version import __version__
from ..core.errors import OnTheSignalError
from ..core.registry import Command, commands
from ..core.session import Session
from ..core.signal import Signal
from ..core.units import COUNTS, fmt_num, pretty_unit

AGENT_DOC = Path("docs/ai/agent.md")
USER_CONTEXT = Path("context.md")
GLOBAL_CONTEXT = Path("~/.config/onthesignal/context.md").expanduser()

#: Typical requests mapped to each command ("when to use it").
INTENTS: dict[str, list[str]] = {
    "noise": ["measure the noise of a record without signal (inputs shorted)",
              "noise RMS, peak-to-peak, mean, dynamic range in a band"],
    "noise_fft": ["show the noise spectrum (FFT) with the noise results"],
    "noise_dsp": ["noise power spectral density (Welch PSD)", "noise level per √Hz"],
    "lnm": ["compare the noise with the LNM / NLNM / Peterson low-noise model",
            "is the noise of the sensor or digitizer below the low-noise model?"],
    "sinefit": ["fit a sine: amplitude, frequency, phase and offset of a test sine"],
    "sinad": ["SINAD", "ENOB / effective number of bits", "noise on a sine (4-parameter fit)"],
    "sfdr": ["SFDR", "largest spurious line"],
    "thd": ["THD", "harmonic distortion of a test sine"],
    "dynamic": ["complete dynamic test of a sine: SINAD, ENOB, SFDR, THD, SNR at once",
                "dynamic report"],
    "frequency": ["measure the frequency of a periodic signal"],
    "period": ["measure the period and its jitter"],
    "delay50": ["delay / time offset between two signals at 50 % of their edges",
                "synchronization between two digitizers"],
    "coherence": ["coherence between two channels or two instruments"],
    "spectrogram": ["time-frequency view of a signal (spectrogram)"],
}

RULES = f"""You are the assistant of onthesignal {__version__}, a toolkit for the characterization
of seismic acquisition chains (digitizer self-noise, dynamic range, sine tests, comparison with
the Peterson noise models).

Rules:
- Never invent measurement values: call the tools, then interpret the values they return.
- Signals are referred to by their session name (S1, S2...). Use list_signals or signal_info
  when you need their unit, sensitivity or duration.
- Conventions: physical value = counts × sensitivity (unit per count); PSD one-sided in
  dB re 1 unit²/Hz; dBFS relative to a full-scale sine; delay = t(S2) − t(S1).
- `lnm` needs a ground-motion unit (m, m/s or m/s**2) and the sensitivity of the whole chain.
- Tools that write files or run scripts require the user's confirmation; the application asks.
- Be concise; answer in the language of the user's question."""


def _params_line(cmd: Command) -> str:
    return ", ".join(f"{p.name}={p.describe_default()}" for p in cmd.params
                     if not p.advanced and p.name not in cmd.signal_params)


def agent_doc(brief: bool = False) -> str:
    """Markdown description of every command for the AI (``agent.md``)."""
    lines = ["# onthesignal — functions available to the assistant", "",
             "Generated from the command registry and the docstrings "
             f"(onthesignal {__version__}). Do not edit by hand: run `/gen_ai_doc`.", ""]
    for cmd in sorted(commands(), key=lambda c: (c.category, c.name)):
        args = ", ".join("S" if cmd.n_signals == 1 else f"S{i + 1}"
                         for i in range(cmd.n_signals))
        lines.append(f"## `{cmd.name}({args}, ...)` — {cmd.description}")
        intents = INTENTS.get(cmd.name, [])
        if intents:
            lines.append("When to use: " + "; ".join(f"“{i}”" for i in intents) + ".")
        if brief:
            lines.append(f"Main parameters: {_params_line(cmd)}.")
            lines.append("")
            continue
        doc = (cmd.func.__doc__ or "").strip()
        if doc:
            lines += ["", "\n".join(line.strip() for line in doc.split("\n\n")[0].splitlines())]
        lines += ["", "| Parameter | Type | Default | Unit | Description |",
                  "|---|---|---|---|---|"]
        for p in cmd.params:
            lines.append(f"| `{p.name}` | {p.type.__name__} | {p.describe_default()} | {p.unit} | "
                         f"{p.help}{' (advanced)' if p.advanced else ''} |")
        lines += ["", f"Example: `{cmd.name}({args}{', ' if args else ''}{_params_line(cmd)})`",
                  ""]
    return "\n".join(lines)


def write_agent_doc(path: Path = AGENT_DOC) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(agent_doc(), encoding="utf-8")
    return path


def user_context() -> str:
    """Contents of the global and project context files."""
    parts = []
    for path in (GLOBAL_CONTEXT, USER_CONTEXT):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(p for p in parts if p)


def describe_signal(sig: Signal, full_scale: float = 2.0**24) -> list[str]:
    """Summary lines of a signal for the AI context (no samples)."""
    from ..analysis.sinefit import fit4
    from ..processing.spectral import amplitude_spectrum

    st = sig.stats()
    lines = [f"### {sig.name} — {sig.id}",
             f"- {sig.sampling_rate:g} Hz, {fmt_num(sig.duration)} s, start {sig.starttime}",
             f"- unit {pretty_unit(sig.unit)}"
             + ("" if sig.unit == COUNTS else f", sensitivity {sig.sensitivity:.4g}/count"),
             f"- counts: mean {fmt_num(st['mean'])}, std {fmt_num(st['std'])}, "
             f"p-p {fmt_num(st['pp'])}"]
    if sig.gaps:
        lines.append(f"- {len(sig.gaps)} gap(s) in the source file")
    if np.max(np.abs(sig.data)) >= 0.999 * full_scale / 2:
        lines.append("- probable saturation")
    x = sig.data[: min(sig.npts, 1 << 20)]
    f, a, _ = amplitude_spectrum(x - np.mean(x), sig.sampling_rate, "hann", "amplitude")
    peaks = np.argsort(a[1:])[::-1][:5] + 1
    lines.append("- main spectral lines: " + ", ".join(
        f"{fmt_num(f[k])} Hz ({fmt_num(a[k])} counts)" for k in sorted(peaks)))
    nature = "noise or other"
    try:
        fit = fit4(x, sig.sampling_rate, maxiter=30)
        if fit.amplitude > 10 * fit.rms_residual and fit.frequency * sig.duration >= 3:
            nature = (f"sine, f0 ≈ {fmt_num(fit.frequency, 6)} Hz, amplitude ≈ "
                      f"{fmt_num(fit.amplitude)} counts")
    except OnTheSignalError:
        pass
    if nature == "noise or other":
        hist, _ = np.histogram(x, bins=64)
        if hist[0] + hist[-1] > 0.6 * x.size:
            nature = "step / square wave (bimodal)"
    lines.append(f"- probable nature: {nature}")
    return lines


def init_context(session: Session, folder: str | None = None,
                 path: Path | None = None) -> Path:
    """``/init``: summarize every signal (and the files of ``folder``) for the AI."""
    from ..io import detect_format, read

    path = path or Path(session.config.get("paths.state", ".onthesignal")) / "init_context.md"
    lines = ["# Signals context (generated by /init)", ""]
    for sig in session.signals.values():
        lines += describe_signal(sig) + [""]
    if folder:
        for entry in sorted(Path(folder).iterdir()):
            if entry.is_file() and detect_format(entry) == "mseed":
                try:
                    for sig in read(entry):
                        sig.name = entry.name
                        lines += describe_signal(sig) + [""]
                except OnTheSignalError as exc:
                    lines.append(f"- {entry.name}: unreadable ({exc})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def session_summary(session: Session) -> str:
    lines = ["Signals loaded:"]
    for name, s in session.signals.items():
        unit = pretty_unit(s.unit)
        lines.append(f"- {name}: {s.id}, {s.sampling_rate:g} Hz, {fmt_num(s.duration)} s, {unit}"
                     + ("" if s.unit == COUNTS else f", sensitivity {s.sensitivity:.4g}"))
    if not session.signals:
        lines.append("- none")
    if session.results:
        lines.append("Last results: " + "; ".join(
            f"#{i} {r.title or r.kind}" for i, r in enumerate(session.results, start=1)
        )[-1500:])
    return "\n".join(lines)


def system_prompt(session: Session) -> str:
    """Full system prompt: rules, functions, user context, /init summary, session state."""
    parts = [RULES, agent_doc(brief=True)]
    context = user_context()
    if context:
        parts.append("# User context\n" + context)
    init = Path(session.config.get("paths.state", ".onthesignal")) / "init_context.md"
    if init.is_file():
        parts.append(init.read_text(encoding="utf-8"))
    parts.append("# Session\n" + session_summary(session))
    return "\n\n".join(parts)


def edit_context_path() -> Path:
    """``context.md`` (created with a skeleton when missing)."""
    if not USER_CONTEXT.exists():
        USER_CONTEXT.write_text(
            "# Measurement context\n\n"
            "- Test bench:\n- Digitizer (model, gain, sampling rate, filters):\n"
            "- Sensor:\n- Expected performance (e.g. DR > 135 dB):\n- Procedure:\n"
            "- Naming conventions:\n", encoding="utf-8")
    return USER_CONTEXT


def provider_label(config: object) -> str:
    getter = getattr(config, "get", None)
    if getter is None:
        return "?"
    return f"{getter('ai.provider', 'ollama')} ({getter('ai.model', '') or 'default model'})"


__all__ = [
    "AGENT_DOC",
    "INTENTS",
    "agent_doc",
    "describe_signal",
    "edit_context_path",
    "init_context",
    "provider_label",
    "session_summary",
    "system_prompt",
    "user_context",
    "write_agent_doc",
]
