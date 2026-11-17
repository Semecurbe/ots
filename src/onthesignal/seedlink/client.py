"""SeedLink client helpers shared by the acquisition and the real-time analysis."""

from __future__ import annotations

import fnmatch
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from typing import Any

from ..core.errors import ParameterError

Stream = tuple[str, str, str, str]  # (network, station, location, channel)

DEFAULT_PORT = 18000


def server_url(server: str, port: int | None = None) -> str:
    """``host:port`` (the port of ``server`` wins when it already contains one)."""
    if ":" in server:
        return server
    return f"{server}:{port or DEFAULT_PORT}"


def parse_streams(xml_info: str, network: str | None = None, station: str | None = None
                  ) -> list[Stream]:
    """Parse an ``INFO STREAMS`` answer into sorted ``(net, sta, loc, cha)`` tuples."""
    try:
        root = ET.fromstring(xml_info)
    except ET.ParseError as exc:
        raise ParameterError(f"Invalid INFO STREAMS answer from the server: {exc}") from exc
    streams = set()
    for st_elem in root.findall("station"):
        net, sta = st_elem.get("network", ""), st_elem.get("name", "")
        if network and net != network:
            continue
        if station and sta != station:
            continue
        for s in st_elem.findall("stream"):
            streams.add((net, sta, s.get("location", "") or "", s.get("seedname", "")))
    return sorted(streams)


def stream_id(stream: Stream) -> str:
    return ".".join(stream)


def selector(stream: Stream) -> str:
    """SeedLink selector ``LLCCC`` (location then channel, without a dot)."""
    return f"{stream[2]}{stream[3]}"


def filter_streams(streams: Sequence[Stream], patterns: Sequence[str]) -> list[Stream]:
    """Streams whose channel (``FH?``), ``LOC.CHA`` or full id matches one of the patterns."""
    chosen = []
    for s in streams:
        keys = (s[3], f"{s[2]}.{s[3]}", stream_id(s))
        if any(fnmatch.fnmatchcase(k, p) for p in patterns for k in keys):
            chosen.append(s)
    return chosen


def create(server: str, port: int | None, on_data: Callable[[Any], None],
           factory: Callable | None = None) -> Any:
    """Create an EasySeedLink client (``factory`` replaces it in tests)."""
    if factory is None:
        from obspy.clients.seedlink.easyseedlink import create_client

        factory = create_client
    return factory(server_url(server, port), on_data=on_data)


def list_streams(server: str, port: int | None, network: str | None, station: str | None,
                 factory: Callable | None = None) -> list[Stream]:
    """Streams served for ``network`` / ``station`` (``INFO STREAMS`` request)."""
    client = create(server, port, lambda trace: None, factory)
    try:
        return parse_streams(client.get_info("STREAMS"), network, station)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - closing a dead connection must not mask results
            pass
