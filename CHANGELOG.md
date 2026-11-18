# Changelog

All notable changes to this project are documented in this file.
The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `Signal.title`: human-readable title, set by default to the file name without its
  extension when a file is loaded (`title=` option of `load` / `/load` to choose it, one per
  channel for text files). It is shown in result and figure titles (`S1 · title (NSLC)`, also
  available as `Signal.label`), in `list_sig()`, `S.print()`, reports, the AI context and
  text/CSV export headers, and kept by derived signals.

## [0.1.0]

### Added

- Project skeleton: packaging (`pyproject.toml`), quality tools (ruff, mypy, pytest).
- Core data model: `Signal` (operators, slicing, resampling, ObsPy interop), `Result`,
  `Param`, `Session`, command registry, configuration files.
- File input/output: miniSEED with an explicit gap policy (never filled silently), multi-column
  text files (time column, decimal comma, irregular time detection), export to miniSEED, text
  and CSV.
- Common preprocessing: study band (ideal FFT mask or zero-phase Butterworth with reported
  ENBW), mains removal, Welch PSD, amplitude spectra, fractional-octave smoothing.
- Noise analysis: `noise`, `noise_fft`, `noise_dsp` (RMS from PSD integration, cumulative RMS),
  dynamic range and noise ENOB.
- Comparison with the Peterson NLNM/NHNM models in displacement, velocity or acceleration:
  `lnm`.
- Sine analyses: 4-parameter sine fit (IEEE 1057), `sinad` / ENOB (relative and full-scale),
  `sfdr` (residual spectrum, noise-floor detection), `thd` (multi-harmonic fit), SNR and the
  combined `dynamic` analysis.
- Measurements: `frequency`, `period`, `delay50`; spectral analyses: `coherence`,
  `spectrogram`.
- Quarto reports (`report`, `/report`): HTML and PDF (Typst or LaTeX).
- Terminal console: Python input, `/` commands with a fuzzy menu, parameter forms, completion,
  non-blocking matplotlib windows, script editing in vi/nano.
- Standardized scripts (template, `/run_script`, standalone entry point) and batch processing.
- SeedLink acquisition (rework of `acq_mseed.py`: arguments, incremental writing, gap reporting,
  live progress per channel, data-time stop, reconnection) and real-time statistics / FFT / PSD.
- AI assistant (Claude, ChatGPT, Ollama): tools generated from the registry, `agent.md`,
  `/init`, `context.md`, script generation, confirmation policy.
- Documentation site (Quarto): algorithms, user manual, developer guide, API reference
  (quartodoc), AI functions page.
