"""Declarative parameters (specification rule R3).

Each analysis declares its parameters once with :class:`Param`. The same declaration drives
the Python signature defaults, the console forms, the ``/help`` text, the JSON schema given
to AI tools and, later, the web forms.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ParameterError

_TRUE = {"true", "yes", "y", "on", "1", "oui"}
_FALSE = {"false", "no", "n", "off", "0", "non"}
_NONE = {"none", "null", ""}

_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type, Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_eval(expr: str) -> int | float:
    """Evaluate a simple arithmetic expression such as ``2**24`` or ``1e-3 * 5``.

    Only numeric literals, ``+ - * / // % **`` and parentheses are allowed; anything else
    (names, calls, attributes) raises :class:`ParameterError`. This is the evaluator used by
    the console forms, so that no arbitrary code can be executed from a form field.
    """
    try:
        tree = ast.parse(str(expr).strip(), mode="eval")
    except SyntaxError as exc:
        raise ParameterError(f"Invalid number or expression: {expr!r}") from exc

    def ev(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1024:
                raise ParameterError(f"Exponent too large in {expr!r}")
            return _BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        raise ParameterError(f"Unsupported expression: {expr!r} (numbers and + - * / ** only)")

    return ev(tree)


@dataclass(frozen=True)
class Param:
    """Declaration of one analysis parameter.

    Parameters
    ----------
    name : str
        Keyword name used in Python calls and ``/command name=value``.
    type : type
        ``float``, ``int``, ``bool``, ``str`` or ``object`` (passed through unchanged).
    default : Any
        Default value used when nothing else provides one.
    unit : str
        Physical unit of the value, shown in forms and help.
    help : str
        One-line description.
    choices : tuple, optional
        Allowed values (for ``str`` parameters).
    min, max : float, optional
        Inclusive bounds for numeric parameters.
    nullable : bool
        Whether ``None`` is an accepted value.
    advanced : bool
        Advanced parameters are only asked in console forms on request.
    from_signal : str, optional
        Signal attribute supplying the default (e.g. ``"full_scale"``).
    """

    name: str
    type: type = float
    default: Any = None
    unit: str = ""
    help: str = ""
    choices: tuple | None = None
    min: float | None = None
    max: float | None = None
    nullable: bool = False
    advanced: bool = False
    from_signal: str | None = None

    # ------------------------------------------------------------------ conversion
    def coerce(self, value: Any) -> Any:
        """Convert ``value`` (possibly a string typed by the user) and validate it."""
        if value is None or (isinstance(value, str) and value.strip().lower() in _NONE):
            if self.nullable or self.type is object:
                return None
            if self.default is None:
                return None
            raise ParameterError(f"Parameter '{self.name}' cannot be empty")
        try:
            out = self._convert(value)
        except ParameterError:
            raise
        except (TypeError, ValueError) as exc:
            raise ParameterError(f"Invalid value for '{self.name}': {value!r}") from exc
        self._check(out)
        return out

    def _convert(self, value: Any) -> Any:
        if self.type is bool:
            if isinstance(value, str):
                text = value.strip().lower()
                if text in _TRUE:
                    return True
                if text in _FALSE:
                    return False
                raise ParameterError(f"'{self.name}' expects true or false, got {value!r}")
            return bool(value)
        if self.type is int:
            number = safe_eval(value) if isinstance(value, str) else value
            if float(number) != int(number):
                raise ParameterError(f"'{self.name}' expects an integer, got {value!r}")
            return int(number)
        if self.type is float:
            number = safe_eval(value) if isinstance(value, str) else value
            return float(number)
        if self.type is str:
            return str(value).strip()
        return value

    def _check(self, value: Any) -> None:
        if value is None:
            return
        if self.choices is not None and value not in self.choices:
            allowed = ", ".join(repr(c) for c in self.choices)
            raise ParameterError(f"'{self.name}' must be one of {allowed}, got {value!r}")
        if self.type in (int, float):
            if self.min is not None and value < self.min:
                raise ParameterError(f"'{self.name}' must be >= {self.min}, got {value}")
            if self.max is not None and value > self.max:
                raise ParameterError(f"'{self.name}' must be <= {self.max}, got {value}")

    # ------------------------------------------------------------------ descriptions
    def describe_default(self) -> str:
        """Default value as typed in a form (``2**24`` for full scale)."""
        if self.default is None:
            return "none"
        if self.name == "full_scale" and self.default == 2**24:
            return "2**24"
        if isinstance(self.default, bool):
            return "true" if self.default else "false"
        return str(self.default)

    def json_schema(self) -> dict:
        """JSON schema of the parameter (used for AI tool definitions)."""
        kind = {bool: "boolean", int: "integer", float: "number", str: "string"}.get(
            self.type, "string"
        )
        schema: dict[str, Any] = {"type": [kind, "null"] if self.nullable else kind}
        desc = self.help + (f" [{self.unit}]" if self.unit else "")
        if desc:
            schema["description"] = desc
        if self.default is not None:
            schema["default"] = self.default
        if self.choices is not None:
            schema["enum"] = list(self.choices)
        if self.min is not None:
            schema["minimum"] = self.min
        if self.max is not None:
            schema["maximum"] = self.max
        return schema


def resolve_params(
    decl: Iterable[Param],
    given: Mapping[str, Any],
    signal: Any = None,
    config: Any = None,
    command: str = "",
) -> dict[str, Any]:
    """Apply defaults and validation to user-supplied parameters.

    Precedence: value passed in the call > signal attribute (``Param.from_signal``) >
    configuration file (``[analysis]`` section) > declared default.
    """
    decl = list(decl)
    names = {p.name for p in decl}
    unknown = sorted(set(given) - names)
    if unknown:
        raise ParameterError(
            f"Unknown parameter(s) for {command or 'this command'}: {', '.join(unknown)}. "
            f"Valid parameters: {', '.join(sorted(names))}"
        )
    out: dict[str, Any] = {}
    for p in decl:
        if p.name in given:
            value = given[p.name]
        elif p.from_signal and getattr(signal, p.from_signal, None) is not None:
            value = getattr(signal, p.from_signal)
        elif config is not None and config.get(f"analysis.{p.name}") is not None:
            value = config.get(f"analysis.{p.name}")
        else:
            value = p.default
        out[p.name] = p.coerce(value)
    return out


def params_schema(decl: Iterable[Param]) -> dict:
    """JSON schema (object) for a list of parameters."""
    return {
        "type": "object",
        "properties": {p.name: p.json_schema() for p in decl},
        "additionalProperties": False,
    }
