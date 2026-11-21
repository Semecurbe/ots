# Changelog

All notable changes to this project are documented in this file.
The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Test signals from an ideal N-bit digitizer: `make_sine` (frequency, amplitude as a ratio of
  full scale or in dBFS, number of bits, added noise, harmonics, mains line) and
  `make_noise` (white, pink or brown noise of given RMS), with recorded seeds. Available in
  Python, as `/make_sine` and `/make_noise` console commands (forms) and as AI tools.
- `Signal.title`: human-readable title, set by default to the file name without its
  extension when a file is loaded (`title=` option of `load` / `/load` to choose it, one per
  channel for text files). It is shown in result and figure titles (`S1 · title (NSLC)`, also
  available as `Signal.label`), in `list_sig()`, `S.print()`, reports, the AI context and
  text/CSV export headers, and kept by derived signals.
- Sine figures (`sinad`, `sfdr`, `thd`, `dynamic`): the computation conditions (study band,
  filtering method, ENBW, mains lines removed or not) are written above the spectrum, and
  each removed mains line is marked by a red dashed line. New `xscale` parameter for these
  analyses.
- `[ai] context`: context length (tokens) sent to Ollama as `num_ctx` with every request.
  The default context of Ollama (often 4096 tokens) is shorter than the assistant's prompt
  (about 9 600 tokens) and Ollama truncates it silently. `/model` shows the Ollama server and
  context. `ollama.md` explains how to use Ollama, on a GB10 or locally, instead of Claude.
- Web interface `onthesignal web` (NiceGUI 4 + µPlot, specification `onthesignal_web.md`),
  installed with `pip install -e ".[web]"`; the console is unchanged and remains available:
  - objects panel listing the signals, results, figures and variables of the session, each
    displayed with one click;
  - interactive µPlot charts of every analysis (zoom, cursor, synchronized panels, study band,
    removed mains lines, fundamental, harmonics and spur markers, calculation conditions),
    with the results of the analysis under the chart: warnings, key figures, detail in counts
    and physical units, tables, parameters and traceability;
  - time plots of signals with zoom reloading the visible window, statistics of the visible
    window, editable properties, window selection for analyses and slicing;
  - analysis forms generated from the parameter declarations, showing the origin of each value;
  - Python terminal connected to the session (same engine as the console): signals and results
    are variables, Jedi completion, `name?` help, Ctrl+C interruption, figures shown in tabs;
  - Monaco editor with file explorer, upload and download, syntax check, script runs and
    execution of the selection in the terminal;
  - AI chat with tool-call cards, Allow/Deny confirmations, provider and model choice;
  - reports (basket, generation, Quarto rendering, preview), scripts and SeedLink acquisition
    views; command palette (`/`, Ctrl+K) and keyboard shortcuts;
  - interactive spectrogram: the color map is drawn in the chart, with the time, the frequency
    and the level read under the cursor, a color bar, and the time series above it on a
    shared time axis;
  - navigation toolbar on every chart, as in the matplotlib windows: full view, previous and
    next view (every zoom or move can be undone), *Zoom* mode (drag a rectangle to zoom on
    both axes; a flat drag zooms the abscissa only) and *Move* mode (drag the chart); the
    middle button and Shift + wheel move, Ctrl + wheel zooms around the cursor; a time plot
    receives one window width on each side of the visible window, so that it moves at once;
  - several signals in one plot: check boxes of the objects panel with *Overlay* and *Stack*,
    *Add signal* above a plot, a signal dragged onto a plot, chips to remove one; a warning
    when the overlaid signals have different units;
  - installable as an application (PWA): manifest, icons, service worker with an offline page
    when the server is not running;
  - dark theme (header menu, palette, `[web] theme`), with chart colors validated on the dark
    surface; Monaco and the Python terminal follow it;
  - editor: completion, signature help and documentation from Jedi with the objects of the
    session (`S1.` → `sensitivity`, `lnm`…), ruff findings underlined after a pause of typing
    and listed in *Problems* at saving, TOML checked at saving (`onthesignal.toml` read again);
  - chat: answers shown as they are generated, reasoning of the model in a folded block,
    tokens used against the context size, `@` mentions attaching summaries of signals and
    results or text files, conversations saved in `.onthesignal/chats/` (reopen, export in
    Markdown), *Allow for this chat*, profile selector with an availability check;
  - *Settings* view: every value with its origin, changes for the session, unknown keys;
  - `plot(x, y…)` in the Python terminal: arrays in an interactive chart (`plot(S1, S2)`
    overlays signals); 2-D arrays shown as a table, lists and dictionaries as a tree; levels
    ±full scale/2 on a time plot when the signal comes near them; *Ask AI* on the selection
    of the editor; *Regenerate* in the chat;
  - comparison of results of the same analysis (Ctrl+click in the objects panel, or
    *Compare with…*): one figure where each signal keeps its color, and a table with one
    column per result;
  - batches (*Scripts* view, or `/batch` in the palette): analysis or script, file patterns
    of the project, generated parameter form, reading options, progress file by file, table
    of the results with the failures, CSV or JSON export, global Quarto report;
  - real-time dashboard (*Real time* view) of SeedLink streams: statistics of each channel in
    counts and physical unit, latency and gaps, trace of the last seconds, FFT and Welch PSD
    over a sliding window, miniSEED recording that can be switched on and off while running;
  - security without login: loopback interface by default, Host and Origin checks of HTTP and
    WebSocket requests, files confined to the project, `[web] code_execution = false`;
  - µPlot 1.6.32 and Monaco 0.56.0 vendored (offline), see `web/static/vendor/VENDOR.md`;
  - built on NiceGUI 4 (`nicegui>=4.0,<5`, with Quasar 2.35 and xterm.js 6); needs a recent
    browser: Firefox, Chrome or Edge 121 or later, Safari 17.2 or later;
  - browser tests with Playwright and Google Chrome (`pip install -e ".[e2e]"`,
    `ONTHESIGNAL_E2E=1 pytest tests/test_web_e2e.py`).
- `onthesignal desktop`: the web interface in its own window, like an Electron application
  (Qt WebEngine, `pip install -e ".[desktop]"`): it starts the server on a free port and stops
  it when the window is closed; downloads ask where to save, links to other sites open in the
  browser. Without PySide6, a Chrome/Chromium window without browser bars.
- AppImage built by `packaging/appimage/build_appimage.py` (python-appimage): one file with
  Python 3.13, onthesignal and Qt WebEngine, which opens the desktop application (`--console`,
  `web`, `acq`, `rt` and `run` give the other commands).
- Signals: `S + k`, `k + S`, `S - k` and `k - S` shift the samples by `k` counts (new signal,
  `offset(k)` too); `S.data = …` replaces the samples (e.g. `S4.data = S4.data + 100`), which is
  noted in the history (`samples modified`); the console also notes changes made in place
  (`S4.data[:100] = 0`). `Signal.data_version` tells the views that the samples changed.
- AI profiles `[[ai.profiles]]` (`name`, `provider`, `model`, `base_url`, `context`) and
  `[ai] profile`; `/model <profile>` in the console. The providers stream their answers
  (`on_delta`), give the reasoning of the model and the tokens used.
- Configuration: origin of each value (default, global, project, session), keys not read by
  onthesignal, reloading of the files.
- `ruff` added to the `[web]` dependencies (diagnostics of the editor).
- `batch()` reports its progress (`on_progress`) and can be stopped between files
  (`should_stop`); `batch_summary()` turns the rows of a batch into a result for a report.
- `RealtimeMonitor`: `latest(seconds)` returns the last samples of each channel,
  `snapshot(spectrum=...)` computes the FFT or the PSD on demand, `set_record_dir()` starts or
  stops the recording while running.
- Results get stable session names (`R1`, `R2`…), available as variables in the console.
- `noise?` (or any `name?`) in the console shows the signature and the documentation.
- The session is observable (`Session.subscribe`, `Session.version`) and can be made the default
  of the process for worker threads (`set_session(session, default=True)`).
- `param_origins()`: where each parameter value comes from (call, signal, configuration,
  default); `processing.display`: decimation keeping minima and maxima; `plot.spec` and
  `plot.layouts`: renderer-independent figure descriptions of every analysis.

### Changed

- `lnm`: the NHNM is no longer shown by default (`show_nhnm=True` to show it).
- `lnm`: the abscissa is the frequency by default (`x="period"` for the period); the legend
  sits above the PSD plot and the results box gives the frequency of the maximum difference
  (new value `freq_max`).
- The frequency axis of the sine spectra is logarithmic by default (`xscale="linear"` for
  the former display); on a log axis the results box moves to the upper left corner.
- Removed mains lines are drawn as red dashed lines in every figure (noise spectra included),
  instead of grey dotted lines.
- The AI assistant talks to the user through a "user host" (console or web chat) instead of
  the console itself, reports its tool calls (`on_event`) and can be stopped (`cancel()`).
- The console synchronizes its variables with the session before each command too, so that
  signals loaded by another interface are available at once.

### Fixed

- `lnm`: the Peterson models were interpolated on periods sorted in decreasing order (as
  returned by ObsPy), which `numpy.interp` does not support. The NHNM curve was wrong (a
  straight line in displacement) and so were PSD − NLNM and every value derived from it
  (minimum, maximum, mean, period of the maximum, share below the NLNM). The NLNM curve
  itself was right. Results of `lnm` computed before this fix must be recomputed.
- `sfdr`: the mains lines excluded from the spur search now honour `mains_harmonics` and
  `fmin`, like the band limitation of the other analyses.
- Console: a signal created and assigned in the same command (`S5 = make_noise(...)`) is
  registered under the variable name, as the specification requires, instead of an automatic
  name with the variable as an alias.
- `/config` no longer fails when the global configuration file contains keys outside any
  section (written by another program).
- SeedLink: with ObsPy 1.5, every connection to a real server failed with "'<' not supported
  between instances of 'float' and 'NoneType'", so the acquisition, the real-time analysis
  and the stream listing could not work (`/acq`, `/rt`, `onthesignal acq|rt`). ObsPy creates
  the connection of its `EasySeedLinkClient` without a timeout, and `connect()` then compares
  the elapsed time with `None`. The connection now gets a 30 s timeout while connecting only,
  so that a quiet low-rate channel does not end the stream. Checked against the GEOFON
  server (SeedLink 4).

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
