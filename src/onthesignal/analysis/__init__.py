"""Analyses. Importing this package registers every analysis command."""

from . import lnm, measures, noise, sine, sinefit, spectral  # noqa: F401
from .lnm import compute_lnm, peterson_models
from .measures import compute_delay50, compute_frequency, compute_period, crossings
from .noise import compute_noise, compute_noise_dsp, compute_noise_fft, dynamic_range
from .sine import compute_dynamic, compute_sfdr, compute_sinad, compute_thd
from .sinefit import SineFit, estimate_frequency, fit3, fit4, fit_harmonics
from .spectral import compute_coherence, compute_spectrogram

__all__ = [
    "SineFit",
    "compute_coherence",
    "compute_delay50",
    "compute_frequency",
    "compute_period",
    "compute_spectrogram",
    "crossings",
    "compute_dynamic",
    "compute_lnm",
    "compute_noise",
    "compute_noise_dsp",
    "compute_noise_fft",
    "compute_sfdr",
    "compute_sinad",
    "compute_thd",
    "dynamic_range",
    "estimate_frequency",
    "fit3",
    "fit4",
    "fit_harmonics",
    "peterson_models",
]
