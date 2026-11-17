# onthesignal

Signal processing toolkit for the characterization of seismic acquisition chains:
digitizer self-noise, dynamic range, sine-wave performance (SINAD, ENOB, SFDR, THD, SNR),
comparison with the Peterson noise models, time and spectral measurements, SeedLink
acquisition, Quarto reports and an optional AI assistant.

The software runs as an interactive console in a Linux terminal. Its computation core is
independent from the user interface so that it can later be reused by a web interface.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"        # add ,ai for the assistant and ,docs for the docs
```

Reports and documentation are rendered with [Quarto](https://quarto.org).

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
onthesignal acq --server HOST --network RD --station SN270 --duration 600   # acquisition
onthesignal rt --server HOST --network RD --station SN270 --channels FHZ    # real time
onthesignal run scripts/my_analysis.py --files "data/*.mseed" --out out.csv
```

## Quality checks

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

## Documentation

The documentation (algorithms, user manual, developer guide, API reference) lives in `docs/`:

```bash
cd docs
QUARTO_PYTHON=../.venv/bin/python ../.venv/bin/quartodoc build
QUARTO_PYTHON=../.venv/bin/python quarto render      # site in docs/_site/
```

The specification (in French) is `onthesignal_v2.md`. The former `acq_mseed.py` script is
superseded by `onthesignal acq`.
