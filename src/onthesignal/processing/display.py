"""Decimation for display (rule R16 of the web specification).

A browser draws at most a few thousand points per curve. These functions reduce a curve to
two points per bin, its minimum and its maximum, so that an isolated spike of one sample or a
narrow spectral line stays visible whatever the zoom level. They are presentation helpers:
the results themselves are never computed from decimated data.
"""

from __future__ import annotations

import numpy as np

#: Samples handled at once when looking for the extrema of the segments: a record of a day
#: (21.6 million samples at 250 Hz) is reduced by blocks, with a bounded temporary memory.
CHUNK = 1 << 21


def _segment_extrema(y: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Sorted indices of the minimum and the maximum of each segment ``y[starts[i]:...]``.

    Non-finite values are ignored; a segment without any finite value contributes nothing.
    Long series are handled by blocks of whole segments of about :data:`CHUNK` samples.
    """
    if y.size <= CHUNK or starts.size < 2:
        return _block_extrema(y, starts)
    parts = []
    i, total = 0, starts.size
    while i < total:
        j = max(int(np.searchsorted(starts, starts[i] + CHUNK, side="left")), i + 1)
        end = int(starts[j]) if j < total else y.size
        first = int(starts[i])
        parts.append(_block_extrema(y[first:end], starts[i:j] - first) + first)
        i = j
    return np.concatenate(parts)


def _block_extrema(y: np.ndarray, starts: np.ndarray) -> np.ndarray:
    n = y.size
    counts = np.diff(np.append(starts, n))
    seg = np.repeat(np.arange(starts.size), counts)
    finite = np.isfinite(y)
    low = np.where(finite, y, np.inf)
    high = np.where(finite, y, -np.inf)
    mins = np.minimum.reduceat(low, starts)
    maxs = np.maximum.reduceat(high, starts)
    positions = np.arange(n)
    picked = []
    for values, extrema in ((low, mins), (high, maxs)):
        hit = (values == extrema[seg]) & finite
        segments, first = np.unique(seg[hit], return_index=True)
        if segments.size:
            picked.append(positions[hit][first])
    if not picked:
        return np.empty(0, dtype=int)
    return np.unique(np.concatenate(picked))


def envelope_indices(n: int, y: np.ndarray, n_bins: int) -> np.ndarray:
    """Indices of a min/max envelope of ``y`` (``n`` samples) over ``n_bins`` equal bins.

    When the series has no more than ``2 * n_bins`` samples, every index is returned.
    Otherwise the first and last samples are kept as well (at most ``2 * n_bins + 2``
    indices), so that the curve spans the whole window: the full view of a plot is then the
    full record.
    """
    if n <= 2 * n_bins:
        return np.arange(n)
    starts = np.unique(np.linspace(0, n, n_bins + 1).astype(int)[:-1])
    return np.union1d(_segment_extrema(np.asarray(y, dtype=float), starts), [0, n - 1])


def decimate_xy(x: np.ndarray, y: np.ndarray, n_bins: int, scale: str = "linear"
                ) -> tuple[np.ndarray, np.ndarray]:
    """Reduce a curve to the minimum and maximum of each of ``n_bins`` bins along ``x``.

    Bins are equal in ``x`` (``scale="linear"``) or in ``log10(x)`` (``scale="log"``, where
    the points with ``x <= 0`` are dropped since a logarithmic axis cannot show them). A
    curve with no more than ``2 * n_bins`` points is returned unchanged (except for that
    filtering); otherwise its first and last points are kept as well, so that the curve spans
    its whole abscissa. ``x`` must be increasing, as for every curve of a result.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if scale == "log":
        keep = x > 0
        x, y = x[keep], y[keep]
    if x.size <= 2 * n_bins:
        return x, y
    u = np.log10(x) if scale == "log" else x
    lo, hi = float(u[0]), float(u[-1])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        idx = envelope_indices(x.size, y, n_bins)
        return x[idx], y[idx]
    bins = np.clip(((u - lo) / (hi - lo) * n_bins).astype(int), 0, n_bins - 1)
    starts = np.concatenate(([0], np.flatnonzero(np.diff(bins)) + 1))
    idx = np.union1d(_segment_extrema(y, starts), [0, x.size - 1])
    return x[idx], y[idx]


def window_stats(y: np.ndarray) -> dict[str, float]:
    """Statistics of a displayed window: mean, standard deviation, peak-to-peak, min, max."""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if y.size == 0:
        nan = float("nan")
        return {"mean": nan, "std": nan, "pp": nan, "min": nan, "max": nan, "n": 0}
    low, high = float(np.min(y)), float(np.max(y))
    return {"mean": float(np.mean(y)), "std": float(np.std(y)), "pp": high - low,
            "min": low, "max": high, "n": int(y.size)}


__all__ = ["decimate_xy", "envelope_indices", "window_stats"]
