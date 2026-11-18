"""onthesignal — signal processing for the characterization of seismic acquisition chains.

Typical use::

    from onthesignal import load, noise, lnm, dynamic
    s1 = load("acquisition_FHZ.mseed")
    s1.sensitivity = 2.384e-6   # V/count
    s1.unit = "V"
    r = noise(s1, remove_mains=True)
    print(r["rms"], r["dr"])
"""

from ._version import __version__
from .api import (
    SFDR,
    SINAD,
    THD,
    coherence,
    delay50,
    display,
    dynamic,
    frequency,
    list_res,
    list_sig,
    lnm,
    load,
    make_noise,
    make_sine,
    noise,
    noise_dsp,
    noise_fft,
    period,
    rename_sig,
    report,
    rm_sig,
    run,
    sfdr,
    show,
    sinad,
    sinefit,
    spectrogram,
    thd,
)
from .core import (
    Config,
    Curve,
    OnTheSignalError,
    Param,
    Result,
    Session,
    Signal,
    Value,
    get_session,
    set_session,
)

__all__ = [
    "SFDR",
    "SINAD",
    "THD",
    "Config",
    "Curve",
    "OnTheSignalError",
    "Param",
    "Result",
    "Session",
    "Signal",
    "Value",
    "__version__",
    "coherence",
    "delay50",
    "display",
    "dynamic",
    "frequency",
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
    "period",
    "rename_sig",
    "report",
    "rm_sig",
    "run",
    "set_session",
    "sfdr",
    "show",
    "sinad",
    "sinefit",
    "spectrogram",
    "thd",
]
