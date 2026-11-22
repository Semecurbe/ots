"""Day files of SDS archives: inventory, selection by window, several days in one signal."""

from __future__ import annotations

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime

from onthesignal import api
from onthesignal.cli.console import OnTheSignalConsole
from onthesignal.core.config import Config
from onthesignal.core.errors import ParameterError
from onthesignal.core.session import Session, set_session
from onthesignal.io.archive import scan, select_channels

FS = 1.0  # one sample per second: a day is 86 400 samples


def day_file(folder, doy: int, channel: str = "BHE", year: int = 2026, offset: int = 0) -> None:
    """A day file of an SDS archive: the samples count the seconds from the start of the day."""
    start = UTCDateTime(year=year, julday=doy)
    tr = Trace((np.arange(86400) + offset).astype(np.int32),
               header={"network": "XX", "station": "LORA", "location": "HA", "channel": channel,
                       "sampling_rate": FS, "starttime": start})
    folder.mkdir(parents=True, exist_ok=True)
    Stream([tr]).write(str(folder / f"XX.LORA.HA.{channel}.D.{year}.{doy:03d}"), format="MSEED",
                       encoding="INT32", reclen=512)


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Session(config=Config(), interactive=True)
    set_session(s, default=True)
    return s


@pytest.fixture
def flat(tmp_path):
    """Day files gathered in one folder: BHE on days 252, 253 and 255, BHN on day 252."""
    folder = tmp_path / "uploads"
    for doy in (252, 253, 255):
        day_file(folder, doy)
    day_file(folder, 252, "BHN")
    (folder / "notes.txt").write_text("bench 3\n")
    return folder


def test_inventory_of_a_folder_and_of_an_sds_tree(flat, tmp_path):
    channels = scan(flat)
    assert list(channels) == ["XX.LORA.HA.BHE", "XX.LORA.HA.BHN"]
    bhe = channels["XX.LORA.HA.BHE"]
    assert [f.doy for f in bhe.files] == [252, 253, 255]
    assert [d.julday for d in bhe.missing_days()] == [254]
    assert bhe.row() | {"size_MB": 0} == {"channel": "XX.LORA.HA.BHE", "from": "2026-09-09",
                                         "to": "2026-09-12", "days": 3, "missing_days": 1,
                                         "size_MB": 0}
    # the file of the day before is read when the window starts near midnight (a day file
    # may end a few seconds after it)
    assert [p.name[-3:] for p in bhe.files_for("2026-09-10T12:00", "2026-09-10T18:00")] == \
        ["253"]
    assert [p.name[-3:] for p in bhe.files_for("2026-09-10T00:00", "2026-09-10T18:00")] == \
        ["252", "253"]
    tree = tmp_path / "archive"  # <root>/YEAR/NET/STA/CHA.D/
    day_file(tree / "2026" / "XX" / "LORA" / "BHZ.D", 10, "BHZ")
    assert list(scan(tree)) == ["XX.LORA.HA.BHZ"]
    assert [c.channel for c in select_channels(channels, "*.BH?")] == list(channels)
    with pytest.raises(ParameterError, match="No channel matches"):
        select_channels(channels, "*.HHZ")


def test_several_days_in_one_signal(flat, session):
    two = api.load_sds(flat, "XX.LORA.HA.BHE", "2026-09-09", "2026-09-11")
    assert two.npts == 2 * 86400 and not two.gaps
    assert two.title == "XX.LORA.HA.BHE.D.2026.252-253"
    assert two.data[86400] == 0 and two.data[86399] == 86399  # the second day follows
    assert "2 files" in two.history[0] and len(two.sha256) == 64
    split = api.load_sds(flat, "XX.LORA.HA.BHE", gaps="split")  # day 254 is missing
    assert [s.title for s in split] == ["XX.LORA.HA.BHE.D.2026.252-253",
                                        "XX.LORA.HA.BHE.D.2026.255"]
    assert split[0].gaps[0]["type"] == "gap" and split[0].gaps[0]["duration"] == 86400
    longest = api.load_sds(flat, "XX.LORA.HA.BHE")
    assert longest.npts == 2 * 86400  # the longest continuous segment
    part = api.load_sds(flat, "XX.LORA.HA.BHE", "2026-09-10T06:00:00", "2026-09-10T07:00:00")
    assert part.npts == 3601 and part.title == "XX.LORA.HA.BHE.D.2026.253"
    assert part.data[0] == 6 * 3600
    pattern = api.load(str(flat / "XX.LORA.HA.BHE.D.2026.25[23]"))  # a list of files too
    assert pattern.npts == 2 * 86400 and pattern.title == "XX.LORA.HA.BHE.D.2026.252-253"
    both = api.load_sds(flat, "*.BH?", "2026-09-09", "2026-09-10", name=["E", "N"])
    assert [s.name for s in both] == ["E", "N"] and "E" in session.signals
    assert api.sds_channels(flat)[1]["channel"] == "XX.LORA.HA.BHN"


def test_sds_console_command(flat, session, capsys):
    console = OnTheSignalConsole(session=session, forms=False, ask=lambda label, d: d,
                                 install_display=False)
    console.execute(f"/sds {flat}")
    out = capsys.readouterr().out
    assert "XX.LORA.HA.BHE" in out and "missing_days" in out
    console.execute(f"/sds {flat} XX.LORA.HA.BHE 2026-09-09 2026-09-11 name=Days")
    assert session.signals["Days"].npts == 2 * 86400
    assert "Loaded 1 signal" in capsys.readouterr().out
