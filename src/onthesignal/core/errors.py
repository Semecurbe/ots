"""Exception hierarchy of onthesignal.

Every error raised on purpose by the library derives from :class:`OnTheSignalError`, so that
user interfaces can display a short message instead of a traceback.
"""


class OnTheSignalError(Exception):
    """Base class for all errors raised by onthesignal."""


class UnitError(OnTheSignalError):
    """Incompatible or unsupported physical unit."""


class TimeRangeError(OnTheSignalError):
    """Invalid time window, or signals that do not overlap in time."""


class ParameterError(OnTheSignalError):
    """Invalid analysis or command parameter."""


class FileFormatError(OnTheSignalError):
    """File that cannot be read or written with the requested options."""


class AnalysisError(OnTheSignalError):
    """Analysis that cannot be carried out on the given data."""


class OnTheSignalWarning(UserWarning):
    """Warning emitted by onthesignal (interpolation, gaps, reduced band...)."""
