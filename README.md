# onthesignal

Signal processing toolkit for the characterization of seismic acquisition chains:
digitizer self-noise, dynamic range, sine-wave performance (SINAD, ENOB, SFDR, THD, SNR),
comparison with the Peterson noise models, time and spectral measurements, SeedLink
acquisition, Quarto reports and an optional AI assistant.

The software runs as an interactive console in a Linux terminal and as a web interface in the
browser (`onthesignal web`: interactive charts, comparison of results, batches, SeedLink
acquisition and real-time dashboard, Python terminal, code editor, AI chat). Both use the same
computation core, commands and configuration.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"        # add ,ai for the assistant, ,web for the web
                                         # interface (NiceGUI 4) and ,docs for the docs
```

Reports and documentation are rendered with [Quarto](https://quarto.org). The web interface
needs a recent browser: Firefox, Chrome or Edge 121 or later, Safari 17.2 or later.

## Quick start

```bash
.venv/bin/onthesignal data/acquisition_FHZ.mseed
```

```text
ots> list_sig()
ots> S1.sensitivity = 2.384e-6; S1.unit = "V"
ots> noise(S1, remove_mains=True)
ots> /lnm S3
ots> /dynamic S2
ots> /report
```

Type `/` in the console to list every command. Other entry points:

```bash
onthesignal web data/*.mseed            # web interface in the browser (pip install -e ".[web]")
onthesignal acq --server HOST --network RD --station SN270 --duration 600   # acquisition
onthesignal rt --server HOST --network RD --station SN270 --channels FHZ    # real time
onthesignal run scripts/my_analysis.py --files "data/*.mseed" --out out.csv
```

## Quality checks

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
.venv/bin/mypy src
ONTHESIGNAL_E2E=1 .venv/bin/python -m pytest tests/test_web_e2e.py   # browser tests, needs
                                         # pip install -e ".[e2e]" and Google Chrome
```

## Documentation

The documentation (algorithms, user manual, developer guide, API reference) lives in `docs/`:

```bash
cd docs
QUARTO_PYTHON=../.venv/bin/python ../.venv/bin/quartodoc build
QUARTO_PYTHON=../.venv/bin/python quarto render      # site in docs/_site/
```

The specifications (in French) are `onthesignal_v2.md` (console and computation core) and
`onthesignal_web.md` (web interface); `ollama.md` explains how to use Ollama instead of Claude.
The former `acq_mseed.py` script is superseded by `onthesignal acq`.
