"""Command registry (specification rule R8).

Every feature exposed to users is registered once with its name, description, parameters and
computation function. The console (``/`` commands, forms, help), the public Python API and the
AI tools are all generated from this registry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import ParameterError
from .params import Param, params_schema


@dataclass
class Command:
    """A registered command.

    Attributes
    ----------
    name : str
        Command and function name (``noise``).
    func : callable
        Pure computation ``func(*signals, **params) -> Result``.
    params : tuple of Param
        Declared parameters.
    n_signals : int
        Number of mandatory signal arguments.
    signal_params : tuple of str
        Optional parameters holding extra signals (``dynamic(S, noise=S_noise)``); in the
        console they can be given as additional positional signal names.
    description : str
        One-line description shown in the ``/`` menu.
    category : str
        Group in the help (``noise``, ``sine``, ``measure``...).
    read_only : bool
        True when the command neither writes files nor changes the session (AI auto-execution).
    aliases : tuple of str
        Alternative names (``SFDR`` for ``sfdr``).
    """

    name: str
    func: Callable
    params: tuple[Param, ...]
    n_signals: int = 1
    signal_params: tuple[str, ...] = ()
    description: str = ""
    category: str = "analysis"
    read_only: bool = True
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def param(self, name: str) -> Param:
        for p in self.params:
            if p.name == name:
                return p
        raise ParameterError(f"Command '{self.name}' has no parameter '{name}'")

    def schema(self) -> dict:
        """JSON schema of the arguments (signals by name, then parameters)."""
        schema = params_schema(p for p in self.params if p.name not in self.signal_params)
        props: dict[str, dict[str, Any]] = {}
        for i in range(self.n_signals):
            key = "signal" if self.n_signals == 1 else f"signal{i + 1}"
            props[key] = {"type": "string", "description": "Name of a loaded signal (e.g. S1)"}
        for name in self.signal_params:
            props[name] = {"type": ["string", "null"], "description": self.param(name).help}
        schema["properties"] = {**props, **schema["properties"]}
        schema["required"] = list(props)[: self.n_signals]
        return schema


_REGISTRY: dict[str, Command] = {}
_ALIASES: dict[str, str] = {}


def register(
    name: str,
    params: tuple[Param, ...] | list[Param],
    *,
    n_signals: int = 1,
    signal_params: tuple[str, ...] = (),
    description: str = "",
    category: str = "analysis",
    read_only: bool = True,
    aliases: tuple[str, ...] = (),
) -> Callable[[Callable], Callable]:
    """Decorator registering a computation function as a command."""

    def decorator(func: Callable) -> Callable:
        _REGISTRY[name] = Command(
            name=name,
            func=func,
            params=tuple(params),
            n_signals=n_signals,
            signal_params=tuple(signal_params),
            description=description or (func.__doc__ or "").strip().splitlines()[0],
            category=category,
            read_only=read_only,
            aliases=tuple(aliases),
        )
        for alias in aliases:
            _ALIASES[alias] = name
        return func

    return decorator


def get_command(name: str) -> Command:
    """Command by name or alias."""
    key = _ALIASES.get(name, name)
    if key not in _REGISTRY:
        raise ParameterError(f"Unknown command: {name}")
    return _REGISTRY[key]


def commands(category: str | None = None) -> list[Command]:
    """Registered commands, optionally restricted to one category."""
    return [c for c in _REGISTRY.values() if category is None or c.category == category]
