"""Parameter forms generated from the ``Param`` declarations (rule R3, web specification §7.2).

The form shows every parameter with its default, unit, help and the origin of its value
(call > signal attribute > configuration > default). Like the console forms, only the values
changed by the user are returned, so that the precedence rules still apply.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from typing import Any

from nicegui import ui

from ..cli.forms import _default_text
from ..core.errors import ParameterError
from ..core.params import Param

ORIGIN_TEXT = {"signal": "from the signal", "config": "from onthesignal.toml",
               "call": "given", "default": "default"}


class ParamForm:
    """Widgets for a list of parameters.

    Parameters
    ----------
    params : sequence of Param
        Declarations (parameters holding extra signals are listed in ``signal_params``).
    defaults : dict
        Values resolved for the selected signal (``resolve_params`` with no given value).
    origins : dict, optional
        ``param_origins`` of the same resolution.
    signal_params : sequence of str
        Parameters that take a signal of the session (``dynamic(S, noise=S2)``).
    signal_names : sequence of str
        Signals offered for those parameters.
    preset : dict, optional
        Values shown in the fields and always returned (time window of a plot selection).
    """

    def __init__(self, params: Sequence[Param], defaults: dict[str, Any],
                 origins: dict[str, str] | None = None, signal_params: Sequence[str] = (),
                 signal_names: Sequence[str] = (), preset: dict[str, Any] | None = None) -> None:
        self.params = [p for p in params if p.name != "report"]
        self.preset = dict(preset or {})
        self.defaults = {**defaults, **self.preset}
        self.origins = origins or {}
        self.signal_params = set(signal_params)
        self.signal_names = list(signal_names)
        self.fields: dict[str, Any] = {}
        self.errors: dict[str, str] = {}

    # ------------------------------------------------------------------ building
    def build(self) -> None:
        primary = [p for p in self.params if not p.advanced or p.name in self.preset]
        advanced = [p for p in self.params if p.advanced and p.name not in self.preset]
        with ui.column().classes("w-full gap-1"):
            for p in primary:
                self._field(p)
            if advanced:
                with ui.expansion("Advanced", icon="tune").classes("w-full").props("dense"):
                    for p in advanced:
                        self._field(p)

    def _label(self, p: Param) -> str:
        return p.help or p.name

    def _field(self, p: Param) -> None:
        default = self.defaults.get(p.name, p.default)
        origin = "from the plot selection" if p.name in self.preset else \
            ORIGIN_TEXT.get(self.origins.get(p.name, "default"), "")
        hint = f"{p.name} · {origin}"
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            if p.name in self.signal_params:
                options = {"": "none", **{n: n for n in self.signal_names}}
                widget: Any = ui.select(options, value="", label=self._label(p)) \
                    .props(f'dense outlined hint="{hint}"').classes("grow")
            elif p.type is bool:
                widget = ui.switch(self._label(p), value=bool(default))
                ui.label(hint).classes("text-xs text-grey-7")
            elif p.choices:
                options = {c: str(c) for c in p.choices}
                if p.nullable:
                    options = {"": "none", **options}
                widget = ui.select(options, value=default if default is not None else "",
                                   label=self._label(p)) \
                    .props(f'dense outlined hint="{hint}"').classes("grow")
            else:
                text = "" if default is None else _default_text(p, default)
                widget = ui.input(self._label(p), value=text,
                                  placeholder="none" if p.nullable or default is None else "",
                                  validation=functools.partial(self._validate, p)) \
                    .props(f'dense outlined hint="{hint}"'
                           + (f' suffix="{p.unit}"' if p.unit else "")).classes("grow")
            widget.tooltip(f"{p.name}: {p.help}" + (f" [{p.unit}]" if p.unit else ""))
            self.fields[p.name] = widget

    def _validate(self, p: Param, text: str) -> str | None:
        try:
            p.coerce(text)
        except ParameterError as exc:
            self.errors[p.name] = str(exc)
            return str(exc)
        self.errors.pop(p.name, None)
        return None

    # ------------------------------------------------------------------ values
    def values(self) -> dict[str, Any]:
        """Values that differ from the defaults, converted and checked.

        Raises
        ------
        ParameterError
            When a field is invalid (the message names the field).
        """
        out: dict[str, Any] = {}
        for p in self.params:
            widget = self.fields.get(p.name)
            if widget is None:
                continue
            raw = widget.value
            default = self.defaults.get(p.name, p.default)
            if p.name in self.signal_params:
                if raw:
                    out[p.name] = raw
                continue
            if p.name in self.preset and raw not in (None, ""):
                out[p.name] = p.coerce(raw)
                continue
            if isinstance(raw, str):
                if raw.strip() == ("" if default is None else _default_text(p, default)):
                    continue
                value = p.coerce(raw)
            else:
                value = p.coerce(raw)
            if value != default:
                out[p.name] = value
        return out


__all__ = ["ParamForm"]
