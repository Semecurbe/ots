"""Common preprocessing: study band, mains removal, spectral estimation, checks."""

from .band import BandResult, band_limit, detrend_data, mains_lines
from .spectral import (
    amplitude_spectrum,
    default_nperseg,
    interp_peak,
    lobe_half_width,
    make_window,
    minmax_envelope,
    octave_smooth,
    rms_from_psd,
    welch_psd,
)

__all__ = [
    "BandResult",
    "amplitude_spectrum",
    "band_limit",
    "default_nperseg",
    "detrend_data",
    "interp_peak",
    "lobe_half_width",
    "make_window",
    "mains_lines",
    "minmax_envelope",
    "octave_smooth",
    "rms_from_psd",
    "welch_psd",
]
