"""Configuration files.

The global file ``~/.config/onthesignal/config.toml`` is overridden by the project file
``./onthesignal.toml``. Values of the ``[analysis]`` section become the default values of the
analysis parameters with the same name (e.g. ``fmax``, ``mains_freq``, ``full_scale``).
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

from .errors import ParameterError

GLOBAL_CONFIG = Path("~/.config/onthesignal/config.toml").expanduser()
PROJECT_CONFIG = "onthesignal.toml"

DEFAULTS: dict[str, dict[str, Any]] = {
    "analysis": {},
    "console": {
        "editor": "",
        "mpl_backend": "",
        "history_file": "~/.local/state/onthesignal/history",
    },
    "seedlink": {
        "server": "",
        "port": 18000,
        "network": "",
        "station": "",
        "reconnect_attempts": 5,
        "reconnect_delay": 5.0,
    },
    "ai": {
        "provider": "ollama",
        "model": "",
        "base_url": "",
        "context": 0,
        "auto_execute": "read_only",
        "send_raw_data": False,
    },
    "report": {"pdf_engine": "typst", "author": ""},
    "web": {
        "host": "127.0.0.1",
        "port": 8080,
        "open_browser": True,
        "tls_cert": "",
        "tls_key": "",
        "allowed_hosts": [],
        "code_execution": True,
        "scrollback": 10000,
        "roots": ["."],
        "upload_dir": "data/uploads",
        "upload_max_mb": 1024,
        "editor_max_mb": 5,
        "theme": "auto",
        "points_per_pixel": 2,
        "autosave": False,
    },
    "paths": {"scripts": "scripts", "reports": "reports", "state": ".onthesignal"},
}


def _merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


class Config:
    """Merged configuration with dotted-key access (``config.get("ai.provider")``)."""

    def __init__(self, data: dict | None = None, sources: list[Path] | None = None) -> None:
        self.data = _merge(copy.deepcopy(DEFAULTS), data or {})
        self.sources = list(sources or [])

    @classmethod
    def load(cls, project_dir: str | Path | None = None) -> Config:
        """Load the default, global and project configuration files."""
        data: dict = {}
        sources: list[Path] = []
        project = Path(project_dir or Path.cwd()) / PROJECT_CONFIG
        for path in (GLOBAL_CONFIG, project):
            if path.is_file():
                try:
                    with path.open("rb") as fh:
                        _merge(data, tomllib.load(fh))
                except tomllib.TOMLDecodeError as exc:
                    raise ParameterError(f"Invalid configuration file {path}: {exc}") from exc
                sources.append(path)
        return cls(data, sources)

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def to_dict(self) -> dict:
        return copy.deepcopy(self.data)
