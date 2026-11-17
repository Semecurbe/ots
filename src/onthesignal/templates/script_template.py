"""
Name        : my_analysis
Description : RMS of the signal in a study band (template example, replace with your processing)
Author      : <name>
Version     : 1.0 — YYYY-MM-DD
Inputs      : 1 signal (any unit)
"""

import numpy as np

from onthesignal import Curve, Param, Result, Signal
from onthesignal.processing import band_limit, detrend_data

# Declared parameters: console form, help, AI tool, (phase 2) web form
PARAMS = [
    Param("fmax", float, 100.0, unit="Hz", help="Upper bound of the analysis band"),
    Param("remove_mains", bool, False, help="Remove 50 Hz mains and its harmonics"),
]


def run(signals: list[Signal], **params) -> Result:
    """Pure computation: no display, no file output."""
    s = signals[0]
    band = band_limit(
        detrend_data(s.data, "constant"), s.sampling_rate,
        fmax=params["fmax"], remove_mains=params["remove_mains"],
    )
    rms = float(np.std(band.data))
    result = Result(kind="my_analysis", title=f"my_analysis — {s.name or s.id}",
                    signals=[s.identity()], params=params)
    result.add("rms", rms, "counts", "RMS in the band")
    result.add("rms_phys", rms * abs(s.sensitivity), s.unit, "RMS in the band")
    n = min(band.data.size, int(10 * s.sampling_rate))
    result.curves["band_limited"] = Curve(
        s.times()[:n], band.data[:n], label="band-limited signal", x_label="Time", x_unit="s",
        y_label="Amplitude", y_unit="counts",
    )
    return result


def plot(result: Result, fig):
    """Optional: fill a matplotlib figure from the result."""
    c = result.curves["band_limited"]
    ax = fig.add_subplot()
    ax.plot(c.x, c.y, lw=0.8)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude (counts)")
    ax.set_title(result.title)


if __name__ == "__main__":
    # Standalone run: python scripts/my_analysis.py --files data/*.mseed --out results.csv
    from onthesignal.scripts import main

    main(run, PARAMS, plot)
