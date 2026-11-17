"""Comparison with the Peterson (1993) noise models — ``lnm`` (specification §9)."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..core.errors import AnalysisError, UnitError
from ..core.params import Param, resolve_params
from ..core.registry import register
from ..core.result import Curve, Result
from ..core.signal import Signal
from ..core.units import fmt_num, motion_quantity, pretty_unit
from ..processing.checks import gaps_warning
from ..processing.params import TIME_PARAMS, WELCH_PARAMS, window_param
from ..processing.spectral import octave_smooth, welch_psd
from ._common import clean_params, signal_label, window_signal

LNM_PARAMS = (
    window_param("hann"),
    *WELCH_PARAMS,
    Param("smoothing", int, 8, nullable=True, min=1,
          help="PSD smoothing in 1/n octave bands (none = no smoothing)"),
    Param("show_nhnm", bool, True, help="Also show the high-noise model (NHNM)"),
    Param("x", str, "period", choices=("period", "freq"), help="Abscissa: period or frequency"),
    *TIME_PARAMS,
)

#: Frequency range covered by the Peterson models (periods 0.1 s to 100 000 s).
MODEL_FMIN, MODEL_FMAX = 1e-5, 10.0


def peterson_models(quantity: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """NLNM and NHNM converted to ``displacement``, ``velocity`` or ``acceleration``.

    The models are defined for acceleration in dB re 1 (m/s²)²/Hz. Velocity and displacement
    PSDs are obtained by dividing by (2πf)² and (2πf)⁴, i.e. subtracting 20·log10(2πf) and
    40·log10(2πf) dB.

    Returns
    -------
    periods, nlnm, nhnm
        Periods in seconds (increasing) and model levels in dB.
    """
    from obspy.signal.spectral_estimation import get_nhnm, get_nlnm

    periods, nlnm = get_nlnm()
    periods_h, nhnm = get_nhnm()
    nhnm = np.interp(np.log10(periods), np.log10(periods_h), nhnm)
    power = {"acceleration": 0, "velocity": 2, "displacement": 4}[quantity]
    correction = 10.0 * power * np.log10(2.0 * np.pi / periods)
    return np.asarray(periods), np.asarray(nlnm) - correction, np.asarray(nhnm) - correction


@register("lnm", LNM_PARAMS, category="noise",
          description="PSD compared with the Peterson low-noise model (NLNM)")
def compute_lnm(signal: Signal, **params: Any) -> Result:
    """Welch PSD of the signal in physical units compared with the Peterson NLNM.

    The quantity follows ``signal.unit``: displacement (``m``), velocity (``m/s``) or
    acceleration (``m/s**2``). The PSD is smoothed in 1/n octave bands before computing the
    difference ``PSD_dB - NLNM_dB`` over the frequency range common to the PSD and the model.
    """
    p = resolve_params(LNM_PARAMS, params, signal, command="lnm")
    quantity = motion_quantity(signal.unit)
    if quantity is None:
        raise UnitError(
            f"lnm needs a ground-motion unit (m, m/s or m/s**2); "
            f"{signal.name or signal.id} is in {pretty_unit(signal.unit)}. Set the unit and the "
            "sensitivity of the complete chain, e.g. S.unit = 'm/s' and "
            "S.sensitivity = 1 / (1500 V/(m/s) × 419430 counts/V)."
        )
    sig = window_signal(signal, p)
    x = sig.to_physical()
    f, psd, info = welch_psd(
        x, sig.sampling_rate, p["window"], p["nperseg"], p["seg_duration"], p["overlap"],
        p["average"],
    )
    keep = f > 0
    f, psd = f[keep], psd[keep]
    psd_db = 10.0 * np.log10(np.maximum(psd, 1e-300))
    if p["smoothing"]:
        fc, ps = octave_smooth(f, psd, p["smoothing"])
    else:
        fc, ps = f, psd
    ps_db = 10.0 * np.log10(np.maximum(ps, 1e-300))

    periods, nlnm, nhnm = peterson_models(quantity)
    f_model = 1.0 / periods
    in_range = (fc >= MODEL_FMIN) & (fc <= MODEL_FMAX)
    if not np.any(in_range):
        raise AnalysisError(
            f"The PSD ({fmt_num(fc[0])}–{fmt_num(fc[-1])} Hz) does not overlap the model range "
            "(1e-5–10 Hz, periods 0.1–100000 s)"
        )
    log_t = np.log10(1.0 / fc[in_range])
    model_at = np.interp(log_t, np.log10(periods), nlnm)
    diff = ps_db[in_range] - model_at
    f_diff = fc[in_range]
    i_max = int(np.argmax(diff))

    unit = pretty_unit(sig.unit)
    title = f"PSD vs NLNM — {signal_label(sig)} · {quantity} · {fmt_num(sig.duration)} s"
    r = Result("lnm", title=title, signals=[sig.identity()], params=clean_params(p))
    r.add("quantity", quantity, "", "Quantity")
    r.add("diff_min", float(np.min(diff)), "dB", "Minimum PSD − NLNM")
    r.add("diff_max", float(np.max(diff)), "dB", "Maximum PSD − NLNM")
    r.add("diff_mean", float(np.mean(diff)), "dB", "Mean PSD − NLNM")
    r.add("period_max", float(1.0 / f_diff[i_max]), "s", "Period of the maximum difference")
    r.add("below_nlnm", float(100.0 * np.mean(diff < 0)), "%", "Share of the range below NLNM")
    r.add("range", [float(f_diff[0]), float(f_diff[-1])], "Hz", "Compared frequency range",
          kind="range")
    r.add("nperseg", info["nperseg"], "", "Welch segment (samples)")
    r.add("n_averages", info["n_averages"], "", "Welch averages")
    y_unit = f"dB re 1 ({unit})²/Hz"
    r.curves["psd"] = Curve(f, psd_db, label="PSD", x_label="Frequency", x_unit="Hz",
                            y_label="PSD", y_unit=y_unit, xscale="log")
    r.curves["psd_smooth"] = Curve(
        fc, ps_db, label=f"PSD (1/{p['smoothing']} octave)" if p["smoothing"] else "PSD",
        x_label="Frequency", x_unit="Hz", y_label="PSD", y_unit=y_unit, xscale="log",
    )
    r.curves["nlnm"] = Curve(f_model, nlnm, label="NLNM", x_label="Frequency", x_unit="Hz",
                             y_label="PSD", y_unit=y_unit, xscale="log")
    if p["show_nhnm"]:
        r.curves["nhnm"] = Curve(f_model, nhnm, label="NHNM", x_label="Frequency", x_unit="Hz",
                                 y_label="PSD", y_unit=y_unit, xscale="log")
    r.curves["diff"] = Curve(f_diff, diff, label="PSD − NLNM", x_label="Frequency", x_unit="Hz",
                             y_label="Difference", y_unit="dB", xscale="log")
    r.extra["x"] = p["x"]
    w = gaps_warning(sig)
    if w:
        r.warn(w)
    return r
