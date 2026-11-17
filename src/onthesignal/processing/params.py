"""Parameter declarations shared by several analyses (specification §7.1 and §8.4)."""

from __future__ import annotations

from ..core.params import Param

TIME_PARAMS = (
    Param("t_start", object, None, advanced=True,
          help="Start of the analysed window (UTC time or seconds from start)"),
    Param("t_end", object, None, advanced=True,
          help="End of the analysed window (UTC time or seconds from start)"),
)

BAND_PARAMS = (
    Param("fmin", float, 0.0, unit="Hz", min=0.0,
          help="Lower bound of the study band (0 = no high-pass)"),
    Param("fmax", float, 100.0, unit="Hz", min=0.0,
          help="Upper bound of the study band (low-pass)"),
    Param("remove_mains", bool, False, help="Remove the mains line and its harmonics"),
    Param("mains_freq", float, 50.0, unit="Hz", min=1.0, help="Mains frequency", advanced=True),
    Param("mains_width", float, 1.0, unit="Hz", min=0.0,
          help="Total width removed around each mains line", advanced=True),
    Param("mains_harmonics", int, None, nullable=True, min=1,
          help="Number of mains lines removed (none = all up to fmax)", advanced=True),
    Param("filter_method", str, "fft", choices=("fft", "iir"),
          help="Band limitation: ideal FFT mask or zero-phase Butterworth", advanced=True),
    Param("filter_order", int, 4, min=1, max=12, help="Butterworth order (iir method)",
          advanced=True),
    Param("detrend", str, "constant", choices=("constant", "linear", "none"),
          help="Trend removal before analysis", advanced=True),
)

FULL_SCALE_PARAM = Param(
    "full_scale", float, float(2**24), unit="counts", min=1.0, from_signal="full_scale",
    help="Digitizer full scale, peak-to-peak",
)

UNITS_PARAM = Param("units", str, "physical", choices=("physical", "counts"),
                    help="Display units", advanced=True)


def window_param(default: str = "hann") -> Param:
    """Spectral window parameter with an analysis-specific default."""
    return Param("window", str, default, advanced=True,
                 help="Spectral window (hann, blackmanharris, flattop, boxcar...)")


WELCH_PARAMS = (
    Param("nperseg", int, None, nullable=True, min=8, advanced=True,
          help="Welch segment length in samples (default: largest power of 2 <= N/8)"),
    Param("seg_duration", float, None, nullable=True, unit="s", min=0.0, advanced=True,
          help="Welch segment duration (alternative to nperseg)"),
    Param("overlap", float, 0.5, min=0.0, max=0.95, advanced=True, help="Segment overlap ratio"),
    Param("average", str, "mean", choices=("mean", "median"), advanced=True,
          help="Averaging of the Welch periodograms"),
)

XSCALE_PARAM = Param("xscale", str, "log", choices=("log", "linear"), advanced=True,
                     help="Frequency axis scale")
