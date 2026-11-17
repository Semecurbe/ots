"""The :class:`Signal` object: samples plus acquisition metadata.

Samples are stored in raw digitizer units (counts) as float64. The physical value is
``counts * sensitivity`` (sensitivity in physical unit per count). Every operation returns a
new signal; the original is never modified, and each derived signal records its processing
history.
"""

from __future__ import annotations

import hashlib
import warnings
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
from obspy import Trace, UTCDateTime

from .errors import OnTheSignalWarning, ParameterError, TimeRangeError, UnitError
from .units import COUNTS, fmt_num, normalize_unit, pretty_unit

DEFAULT_FULL_SCALE = 2**24
#: Two time grids are considered aligned when they differ by less than this fraction of a sample.
ALIGN_TOLERANCE = 0.01


def to_utc(value: Any, reference: UTCDateTime | None = None) -> UTCDateTime:
    """Convert a time to :class:`~obspy.UTCDateTime`.

    Accepts a ``UTCDateTime``, an ISO string, a ``datetime``, or a number of seconds. Numbers
    are relative to ``reference`` when it is given (e.g. ``S.slice(10, 20)``), absolute
    (epoch seconds) otherwise.
    """
    if isinstance(value, UTCDateTime):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        return reference + float(value) if reference is not None else UTCDateTime(float(value))
    try:
        return UTCDateTime(value)
    except Exception as exc:  # obspy raises TypeError or ValueError
        raise TimeRangeError(f"Invalid time: {value!r}") from exc


def file_sha256(path: str | Path) -> str:
    """SHA-256 digest of a file (traceability, rule R9)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class Signal:
    """Time series with its acquisition metadata.

    Parameters
    ----------
    data : array_like
        Samples in raw units (counts). Stored as float64; the original dtype is kept in
        ``metadata["dtype"]``.
    sampling_rate : float
        Sampling rate in Hz.
    starttime : UTCDateTime or str, optional
        Time of the first sample (default 1970-01-01T00:00:00).
    network, station, location, channel : str
        SEED codes (NSLC).
    unit : str
        Physical unit after conversion (``counts``, ``V``, ``m``, ``m/s``, ``m/s**2``).
    sensitivity : float
        Physical unit per count: ``physical = counts * sensitivity``.
    full_scale : float, optional
        Digitizer full scale, peak-to-peak, in counts. ``None`` means "use the configured
        default" (``2**24``).
    name : str, optional
        Name in the session (``S1``, ``S2``...).

    Examples
    --------
    >>> import numpy as np
    >>> s = Signal(np.zeros(100), 100.0, station="TEST", channel="HHZ")
    >>> s.npts, s.duration
    (100, 1.0)
    >>> (2 * s).history[-1]
    'amplitude × 2'
    """

    def __init__(
        self,
        data: Any,
        sampling_rate: float,
        starttime: Any = None,
        network: str = "XX",
        station: str = "",
        location: str = "",
        channel: str = "",
        unit: str = COUNTS,
        sensitivity: float = 1.0,
        full_scale: float | None = None,
        name: str | None = None,
        source: str = "",
        sha256: str = "",
        metadata: dict | None = None,
        history: list[str] | None = None,
        gaps: list[dict] | None = None,
    ) -> None:
        arr = np.asarray(data)
        if arr.ndim != 1:
            raise ParameterError("Signal data must be a one-dimensional array")
        if arr.size == 0:
            raise ParameterError("Signal data is empty")
        if not float(sampling_rate) > 0:
            raise ParameterError(f"Sampling rate must be positive, got {sampling_rate}")
        self.metadata: dict = dict(metadata or {})
        self.metadata.setdefault("dtype", str(arr.dtype))
        self.data = np.array(arr, dtype=np.float64)
        self.sampling_rate = float(sampling_rate)
        self.starttime = to_utc(starttime) if starttime is not None else UTCDateTime(0)
        self.network = str(network)
        self.station = str(station)
        self.location = str(location)
        self.channel = str(channel)
        self.unit = unit
        self.sensitivity = sensitivity
        self.full_scale = full_scale
        self.name = name
        self.source = str(source)
        self.sha256 = str(sha256)
        self.history: list[str] = list(history or [])
        self.gaps: list[dict] = list(gaps or [])

    # ------------------------------------------------------------------ attributes
    @property
    def unit(self) -> str:
        """Physical unit (normalized spelling)."""
        return self._unit

    @unit.setter
    def unit(self, value: str) -> None:
        self._unit = normalize_unit(value)

    @property
    def sensitivity(self) -> float:
        """Physical unit per count (``physical = counts * sensitivity``)."""
        return self._sensitivity

    @sensitivity.setter
    def sensitivity(self, value: float) -> None:
        value = float(value)
        if value == 0 or not np.isfinite(value):
            raise ParameterError(f"Sensitivity must be finite and non-zero, got {value}")
        self._sensitivity = value

    @property
    def full_scale(self) -> float | None:
        """Full scale, peak-to-peak, in counts (``None`` = configured default)."""
        return self._full_scale

    @full_scale.setter
    def full_scale(self, value: float | None) -> None:
        if value is not None:
            value = float(value)
            if value <= 0:
                raise ParameterError(f"Full scale must be positive, got {value}")
        self._full_scale = value

    @property
    def delta(self) -> float:
        """Sampling interval in seconds."""
        return 1.0 / self.sampling_rate

    @property
    def npts(self) -> int:
        """Number of samples."""
        return int(self.data.size)

    @property
    def duration(self) -> float:
        """Record length in seconds (``npts * delta``)."""
        return self.npts / self.sampling_rate

    @property
    def endtime(self) -> UTCDateTime:
        """Time of the last sample."""
        return self.starttime + (self.npts - 1) / self.sampling_rate

    @property
    def nyquist(self) -> float:
        """Nyquist frequency in Hz."""
        return self.sampling_rate / 2.0

    @property
    def id(self) -> str:
        """SEED identifier ``NET.STA.LOC.CHA``."""
        return f"{self.network}.{self.station}.{self.location}.{self.channel}"

    def __len__(self) -> int:
        return self.npts

    # ------------------------------------------------------------------ data access
    def times(self, kind: str = "relative") -> np.ndarray:
        """Sample times: ``relative`` (s from start), ``timestamp`` (epoch s) or ``matplotlib``."""
        t = np.arange(self.npts) / self.sampling_rate
        if kind == "relative":
            return t
        if kind == "timestamp":
            return self.starttime.timestamp + t
        if kind == "matplotlib":
            return self.starttime.matplotlib_date + t / 86400.0
        raise ParameterError(f"Unknown time kind: {kind!r}")

    def to_physical(self) -> np.ndarray:
        """Samples in physical units (``data * sensitivity``)."""
        return self.data * self.sensitivity

    def stats(self) -> dict[str, float]:
        """Basic statistics in counts: mean, std, peak-to-peak, min, max."""
        d = self.data
        return {
            "mean": float(np.mean(d)),
            "std": float(np.std(d)),
            "pp": float(np.ptp(d)),
            "min": float(np.min(d)),
            "max": float(np.max(d)),
        }

    def identity(self) -> dict:
        """Identity used in results and reports (rule R9)."""
        return {
            "name": self.name or "",
            "id": self.id,
            "source": self.source,
            "sha256": self.sha256,
            "starttime": str(self.starttime),
            "sampling_rate": self.sampling_rate,
            "npts": self.npts,
            "unit": self.unit,
            "sensitivity": self.sensitivity,
            "gaps": [dict(g) for g in self.gaps],
            "history": list(self.history),
        }

    def to_dict(self, samples: bool = False) -> dict:
        """Serializable description; samples are included only on request."""
        out = self.identity()
        out.update(
            {
                "endtime": str(self.endtime),
                "duration": self.duration,
                "full_scale": self.full_scale,
                "stats": self.stats(),
                "metadata": {k: str(v) for k, v in self.metadata.items()},
            }
        )
        if samples:
            out["data"] = self.data.tolist()
        return out

    # ------------------------------------------------------------------ display
    def describe(self) -> str:
        """Multi-line description of all attributes (what :meth:`print` displays)."""
        st = self.stats()
        fs_eff = self.full_scale if self.full_scale is not None else DEFAULT_FULL_SCALE
        bits = np.log2(fs_eff)
        fs_text = f"{fmt_num(fs_eff, 8)} counts p-p"
        if abs(bits - round(bits)) < 1e-9:
            fs_text += f" (2**{int(round(bits))})"
        if self.full_scale is None:
            fs_text += " [default]"
        if self.unit == COUNTS:
            sens_text = "— (data in counts)"
        else:
            sens_text = f"{self.sensitivity:.4g} {pretty_unit(self.unit)}/count"
        source = self.source or "—"
        if self.sha256:
            source += f" (sha256 {self.sha256[:4]}…{self.sha256[-4:]})"
        if self.gaps:
            total = sum(g.get("duration", 0.0) for g in self.gaps)
            gaps_text = f"{len(self.gaps)} gap(s), {fmt_num(total)} s in total"
            actions = sorted({g.get("action", "") for g in self.gaps} - {""})
            if actions:
                gaps_text += f" — {', '.join(actions)}"
        else:
            gaps_text = "none"
        rows = [
            ("Source", source),
            ("Start → end (UTC)", f"{self.starttime} → {self.endtime}"),
            ("Duration", f"{self.duration:.3f} s · {self.npts} samples"),
            ("Sampling rate", f"{self.sampling_rate:.1f} Hz (Nyquist {self.nyquist:.1f} Hz)"),
            ("Unit", pretty_unit(self.unit)),
            ("Sensitivity", sens_text),
            ("Full scale", fs_text),
            (
                "Statistics",
                f"mean {fmt_num(st['mean'])} · std {fmt_num(st['std'])} · p-p {fmt_num(st['pp'])}"
                f" · min {fmt_num(st['min'])} · max {fmt_num(st['max'])} (counts)",
            ),
            ("Gaps", gaps_text),
        ]
        meta = {k: v for k, v in self.metadata.items() if k != "dtype"}
        if meta:
            rows.append(("Metadata", ", ".join(f"{k}={v}" for k, v in meta.items())))
        rows.append(("History", " → ".join(self.history) if self.history else "—"))
        title = f"Signal {self.name} — {self.id}" if self.name else f"Signal {self.id}"
        return title + "\n" + "\n".join(f"  {k:<19}{v}" for k, v in rows)

    def print(self) -> None:
        """Print every attribute of the signal and its basic statistics."""
        print(self.describe())

    def __str__(self) -> str:
        return self.describe()

    def __repr__(self) -> str:
        label = f"{self.name} " if self.name else ""
        return (
            f"<Signal {label}{self.id} {self.sampling_rate:g} Hz "
            f"{self.duration:g} s {pretty_unit(self.unit)}>"
        )

    def show(self, **params: Any) -> Any:
        """Plot the time series (see :func:`onthesignal.show`)."""
        from .. import api

        return api.show(self, **params)

    # ------------------------------------------------------------------ derivation
    def copy(self, **changes: Any) -> Signal:
        """Copy of the signal, with optional attribute changes (``data``, ``starttime``...)."""
        attrs = {
            "data": self.data,
            "sampling_rate": self.sampling_rate,
            "starttime": self.starttime,
            "network": self.network,
            "station": self.station,
            "location": self.location,
            "channel": self.channel,
            "unit": self.unit,
            "sensitivity": self.sensitivity,
            "full_scale": self.full_scale,
            "name": None,
            "source": self.source,
            "sha256": self.sha256,
            "metadata": dict(self.metadata),
            "history": list(self.history),
            "gaps": list(self.gaps),
        }
        attrs.update(changes)
        return Signal(**attrs)

    def _derive(self, data: np.ndarray, note: str, **changes: Any) -> Signal:
        history = [*self.history, note]
        return self.copy(data=data, history=history, **changes)

    def slice(self, t_start: Any = None, t_end: Any = None) -> Signal:
        """Extract the samples between ``t_start`` and ``t_end`` (inclusive).

        Times may be absolute (``UTCDateTime``, ISO string) or seconds from the start.
        """
        if t_start is None and t_end is None:
            return self.copy()
        t0 = to_utc(t_start, self.starttime) if t_start is not None else self.starttime
        t1 = to_utc(t_end, self.starttime) if t_end is not None else self.endtime
        if t1 < t0:
            raise TimeRangeError(f"End time {t1} is before start time {t0}")
        eps = 1e-6
        i0 = max(0, int(np.ceil((t0 - self.starttime) * self.sampling_rate - eps)))
        i1 = min(self.npts - 1, int(np.floor((t1 - self.starttime) * self.sampling_rate + eps)))
        if i1 < i0:
            raise TimeRangeError(
                f"Time window {t0} – {t1} is outside the signal ({self.starttime} – {self.endtime})"
            )
        return self._derive(
            self.data[i0 : i1 + 1],
            f"slice {self.starttime + i0 * self.delta} – {self.starttime + i1 * self.delta}",
            starttime=self.starttime + i0 * self.delta,
        )

    def detrend(self, kind: str = "constant") -> Signal:
        """Remove the mean (``constant``) or a straight line (``linear``)."""
        from scipy.signal import detrend

        if kind not in ("constant", "linear"):
            raise ParameterError("detrend kind must be 'constant' or 'linear'")
        return self._derive(detrend(self.data, type=kind), f"detrend {kind}")

    def filter(self, fmin: float = 0.0, fmax: float | None = None, **params: Any) -> Signal:
        """Band-limit the signal (same options as the study band, see ``processing.band``)."""
        from ..processing.band import band_limit

        fmax = self.nyquist if fmax is None else fmax
        out = band_limit(self.data, self.sampling_rate, fmin=fmin, fmax=fmax, **params)
        note = f"band {fmt_num(out.fmin)}–{fmt_num(out.fmax)} Hz ({out.method})"
        if out.removed_lines:
            note += f", mains removed ({', '.join(fmt_num(f) for f in out.removed_lines)} Hz)"
        return self._derive(out.data, note)

    def resample(self, sampling_rate: float) -> Signal:
        """Resample with an anti-aliasing filter (polyphase method)."""
        from scipy.signal import resample_poly

        ratio = Fraction(float(sampling_rate) / self.sampling_rate).limit_denominator(1000)
        if ratio == 1:
            return self.copy()
        new_fs = self.sampling_rate * ratio.numerator / ratio.denominator
        data = resample_poly(self.data, ratio.numerator, ratio.denominator)
        return self._derive(data, f"resample {self.sampling_rate:g} → {new_fs:g} Hz",
                            sampling_rate=new_fs)

    # ------------------------------------------------------------------ ObsPy interop
    def to_trace(self) -> Trace:
        """Convert to an ObsPy :class:`~obspy.Trace` (integer data when samples are integral)."""
        data = self.data
        if np.all(np.isfinite(data)) and np.all(data == np.round(data)):
            if np.max(np.abs(data), initial=0) < 2**31:
                data = data.astype(np.int32)
        tr = Trace(data=np.ascontiguousarray(data))
        tr.stats.network = self.network
        tr.stats.station = self.station
        tr.stats.location = self.location
        tr.stats.channel = self.channel
        tr.stats.sampling_rate = self.sampling_rate
        tr.stats.starttime = self.starttime
        return tr

    @classmethod
    def from_trace(cls, trace: Trace, **attrs: Any) -> Signal:
        """Create a signal from an ObsPy trace; ``attrs`` override metadata (unit, name...)."""
        st = trace.stats
        kwargs = {
            "data": np.asarray(trace.data),
            "sampling_rate": float(st.sampling_rate),
            "starttime": st.starttime,
            "network": st.network,
            "station": st.station,
            "location": st.location,
            "channel": st.channel,
        }
        kwargs.update(attrs)
        return cls(**kwargs)

    def save(self, path: str | Path, **options: Any) -> Path:
        """Export to miniSEED (``.mseed``), text (``.txt``) or CSV (``.csv``)."""
        from ..io.export import save_signal

        return save_signal(self, path, **options)

    # ------------------------------------------------------------------ operators
    def _values_on_grid(
        self, start: UTCDateTime, npts: int, sampling_rate: float, method: str
    ) -> tuple[np.ndarray, str]:
        """Samples of this signal on another time grid; returns (values, note)."""
        same_rate = abs(self.sampling_rate - sampling_rate) <= 1e-9 * sampling_rate
        offset = (start - self.starttime) * self.sampling_rate
        if same_rate and abs(offset - round(offset)) < ALIGN_TOLERANCE:
            i0 = int(round(offset))
            return self.data[i0 : i0 + npts], ""
        src, note = self, ""
        if not same_rate:
            src = self.resample(sampling_rate)
            note = f"resampled to {src.sampling_rate:g} Hz, "
        t_target = (start - src.starttime) + np.arange(npts) / sampling_rate
        t_src = np.arange(src.npts) / src.sampling_rate
        if method == "linear":
            values = np.interp(t_target, t_src, src.data)
        elif method == "cubic":
            from scipy.interpolate import CubicSpline

            values = CubicSpline(t_src, src.data)(t_target)
        elif method == "lanczos":
            from obspy.signal.interpolation import lanczos_interpolation

            values = lanczos_interpolation(
                np.ascontiguousarray(src.data), 0.0, src.delta, float(t_target[0]),
                1.0 / sampling_rate, npts, a=20,
            )
        else:
            raise ParameterError("Interpolation method must be 'linear', 'cubic' or 'lanczos'")
        return np.asarray(values, dtype=np.float64), note + f"{method} interpolation"

    def _combine(self, other: Signal, op: Callable, symbol: str, method: str) -> Signal:
        if self.unit != other.unit:
            raise UnitError(
                f"Cannot combine signals in {pretty_unit(self.unit)} and {pretty_unit(other.unit)}"
            )
        t0 = max(self.starttime, other.starttime)
        t1 = min(self.endtime, other.endtime)
        if t1 < t0:
            raise TimeRangeError("The signals do not overlap in time")
        a = self.slice(t0, t1)
        b, note = other._values_on_grid(a.starttime, a.npts, a.sampling_rate, method)
        if b.size < a.npts:
            a = a.copy(data=a.data[: b.size], history=a.history)
        if other.sensitivity != self.sensitivity:
            b = b * (other.sensitivity / self.sensitivity)
        label_a = self.name or self.id
        label_b = other.name or other.id
        if note:
            warnings.warn(f"{label_b} {note} onto the time grid of {label_a}",
                          OnTheSignalWarning, stacklevel=3)
        history = [*self.history, f"{symbol} {label_b}" + (f" ({note})" if note else "")]
        return a.copy(data=op(a.data, b), history=history)

    def add(self, other: Signal, method: str = "linear") -> Signal:
        """Sample-wise sum on the common time window, interpolating ``other`` if needed."""
        return self._combine(other, np.add, "+", method)

    def subtract(self, other: Signal, method: str = "linear") -> Signal:
        """Sample-wise difference on the common time window."""
        return self._combine(other, np.subtract, "−", method)

    def __add__(self, other: Any) -> Signal:
        if isinstance(other, Signal):
            return self.add(other)
        return NotImplemented

    def __radd__(self, other: Any) -> Signal:
        if isinstance(other, (int, float)) and other == 0:  # supports sum([S1, S2])
            return self.copy()
        return NotImplemented

    def __sub__(self, other: Any) -> Signal:
        if isinstance(other, Signal):
            return self.subtract(other)
        return NotImplemented

    def __mul__(self, k: Any) -> Signal:
        if isinstance(k, (int, float, np.integer, np.floating)) and not isinstance(k, bool):
            return self._derive(self.data * float(k), f"amplitude × {fmt_num(float(k))}")
        return NotImplemented

    __rmul__ = __mul__

    def __truediv__(self, k: Any) -> Signal:
        if isinstance(k, (int, float, np.integer, np.floating)) and not isinstance(k, bool):
            if k == 0:
                raise ZeroDivisionError("Cannot divide a signal by zero")
            return self._derive(self.data / float(k), f"amplitude ÷ {fmt_num(float(k))}")
        return NotImplemented

    def __neg__(self) -> Signal:
        return self._derive(-self.data, "polarity inverted")


def _shortcut(name: str) -> Callable:
    def method(self: Signal, *others: Any, **params: Any) -> Any:
        from .. import api

        return getattr(api, name)(self, *others, **params)

    method.__name__ = name
    method.__doc__ = f"Shortcut: ``S.{name}(...)`` is ``onthesignal.{name}(S, ...)``."
    return method


for _name in (
    "noise",
    "noise_fft",
    "noise_dsp",
    "lnm",
    "sinefit",
    "sinad",
    "sfdr",
    "thd",
    "dynamic",
    "frequency",
    "period",
    "delay50",
    "coherence",
    "spectrogram",
):
    setattr(Signal, _name, _shortcut(_name))
