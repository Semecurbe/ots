"""Shared fixtures: synthetic signals with known characteristics and a fresh session."""

from __future__ import annotations

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from onthesignal import Session, Signal, set_session  # noqa: E402
from onthesignal.core.config import Config  # noqa: E402


@pytest.fixture(autouse=True)
def session():
    """Isolated session (no configuration file, non-interactive) for every test."""
    s = Session(config=Config(), interactive=False)
    set_session(s)
    return s


@pytest.fixture
def rng():
    return np.random.default_rng(12345)


def sine(n: int, fs: float, f0: float, amplitude: float, phase: float = 0.3,
         offset: float = 0.0) -> np.ndarray:
    t = np.arange(n) / fs
    return amplitude * np.sin(2 * np.pi * f0 * t + phase) + offset


@pytest.fixture
def white_noise(rng):
    """Gaussian white noise, sigma = 100 counts, fs = 200 Hz, 1e6 samples (V-01)."""
    return Signal(rng.normal(0.0, 100.0, 1_000_000), 200.0, station="TEST", channel="HHZ")
