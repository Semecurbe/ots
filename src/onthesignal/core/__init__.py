"""Core data model: signals, parameters, results, session, registry, configuration."""

from .config import Config
from .errors import (
    AnalysisError,
    FileFormatError,
    OnTheSignalError,
    OnTheSignalWarning,
    ParameterError,
    TimeRangeError,
    UnitError,
)
from .params import Param, resolve_params, safe_eval
from .registry import Command, commands, get_command, register
from .result import Curve, Result, Value
from .session import Session, get_session, set_session
from .signal import DEFAULT_FULL_SCALE, Signal

__all__ = [
    "AnalysisError",
    "Command",
    "Config",
    "Curve",
    "DEFAULT_FULL_SCALE",
    "FileFormatError",
    "OnTheSignalError",
    "OnTheSignalWarning",
    "Param",
    "ParameterError",
    "Result",
    "Session",
    "Signal",
    "TimeRangeError",
    "UnitError",
    "Value",
    "commands",
    "get_command",
    "get_session",
    "register",
    "resolve_params",
    "safe_eval",
    "set_session",
]
