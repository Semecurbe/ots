"""Parameter forms generated from the parameter declarations (specification §15.3)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..core.errors import ParameterError
from ..core.params import Param

Ask = Callable[[str, str], str]


def _default_text(p: Param, value: Any) -> str:
    if value is None:
        return "none"
    if p.name == "full_scale" and float(value) == 2.0**24:
        return "2**24"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def ask_params(
    params: Sequence[Param],
    defaults: dict[str, Any],
    ask: Ask,
    skip: Sequence[str] = (),
) -> dict[str, Any]:
    """Ask every non-advanced parameter, then the advanced ones on request.

    ``ask(label, default_text)`` returns the typed text ("" keeps the default). Values that
    stay at their default are not returned, so the normal precedence rules still apply.
    """
    values: dict[str, Any] = {}

    def ask_one(p: Param) -> None:
        default = defaults.get(p.name, p.default)
        unit = f" ({p.unit})" if p.unit else ""
        choices = f" {{{', '.join(p.choices)}}}" if p.choices else ""
        label = f"{p.help}{unit}{choices} — {p.name}"
        while True:
            text = ask(label, _default_text(p, default)).strip()
            if text == "":
                return
            try:
                values[p.name] = p.coerce(text)
                return
            except ParameterError as exc:
                ask(f"  ✗ {exc} — press Enter to retry", "")

    primary = [p for p in params if not p.advanced and p.name not in skip]
    advanced = [p for p in params if p.advanced and p.name not in skip]
    for p in primary:
        ask_one(p)
    if advanced and ask("Advanced parameters? (y/N)", "n").strip().lower() in ("y", "yes", "o"):
        for p in advanced:
            ask_one(p)
    return values


def prompt_ask(label: str, default: str) -> str:
    """Interactive question with prompt_toolkit (the default value is shown in brackets)."""
    from prompt_toolkit import prompt

    suffix = f" [{default}]" if default else ""
    return prompt(f"  {label}{suffix}: ")
