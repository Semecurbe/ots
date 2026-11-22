"""Configuration files.

The global file ``~/.config/onthesignal/config.toml`` is overridden by the project file
``./onthesignal.toml``, itself overridden by the changes made for the session (``/config``,
the web interface). Values of the ``[analysis]`` section become the default values of the
analysis parameters with the same name (e.g. ``fmax``, ``mains_freq``, ``full_scale``).
``Config.origin(key)`` tells where a value comes from.
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
        "profile": "",
        "profiles": [],
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
        "notify_after": 15.0,
        "points_per_pixel": 2,
        "autosave": False,
    },
    "paths": {"scripts": "scripts", "reports": "reports", "state": ".onthesignal"},
}


#: Sections whose keys are free (parameter names of the analyses).
FREE_SECTIONS = {"analysis"}


def _merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _lookup(data: Any, key: str) -> tuple[bool, Any]:
    node = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _keys(data: dict, prefix: str = "") -> list[str]:
    """Dotted keys of the leaves of a nested dictionary (tables of tables are leaves)."""
    out = []
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out += _keys(value, dotted + ".")
        else:
            out.append(dotted)
    return out


def _read(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ParameterError(f"Invalid configuration file {path}: {exc}") from exc


class Config:
    """Merged configuration with dotted-key access (``config.get("ai.provider")``).

    ``layers`` are the files read, in increasing precedence, as ``(origin, path, data)`` with
    origin ``"global"`` or ``"project"`` (``"given"`` for data passed directly); the values
    changed with :meth:`set` are the ``"session"`` layer.
    """

    def __init__(self, data: dict | None = None, sources: list[Path] | None = None,
                 layers: list[tuple[str, Path | None, dict]] | None = None) -> None:
        self.data = _merge(copy.deepcopy(DEFAULTS), data or {})
        self.sources = list(sources or [])
        if layers is None:
            layers = [("given", None, copy.deepcopy(data))] if data else []
        self.layers = layers
        #: Values changed for this session only (dotted key → value).
        self.session: dict[str, Any] = {}
        self.project_dir: Path | None = None

    @classmethod
    def load(cls, project_dir: str | Path | None = None) -> Config:
        """Load the default, global and project configuration files."""
        data: dict = {}
        sources: list[Path] = []
        layers: list[tuple[str, Path | None, dict]] = []
        folder = Path(project_dir or Path.cwd())
        for origin, path in (("global", GLOBAL_CONFIG), ("project", folder / PROJECT_CONFIG)):
            if path.is_file():
                content = _read(path)
                _merge(data, copy.deepcopy(content))
                sources.append(path)
                layers.append((origin, path, content))
        config = cls(data, sources, layers)
        config.project_dir = folder
        return config

    def reload(self) -> None:
        """Read the files again (after they were edited); the session values are kept."""
        fresh = Config.load(self.project_dir)
        self.data, self.sources, self.layers = fresh.data, fresh.sources, fresh.layers
        for key, value in self.session.items():
            self._put(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        found, value = _lookup(self.data, key)
        return value if found else default

    def _put(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def set(self, key: str, value: Any) -> None:
        """Change a value for this session (the files are not modified)."""
        self._put(key, value)
        self.session[key] = value

    def origin(self, key: str) -> str:
        """``session``, ``project``, ``global``, ``given``, ``default`` or ``unknown``."""
        if key in self.session:
            return "session"
        for origin, _, content in reversed(self.layers):
            if _lookup(content, key)[0]:
                return origin
        return "default" if _lookup(DEFAULTS, key)[0] else "unknown"

    def known(self, key: str) -> bool:
        """True for the keys onthesignal reads (free keys of ``[analysis]`` included)."""
        section = key.split(".", 1)[0]
        return section in FREE_SECTIONS or _lookup(DEFAULTS, key)[0]

    def unknown_keys(self) -> list[str]:
        """Keys of the files that onthesignal does not read (another program's, typos)."""
        out: list[str] = []
        for _, _, content in self.layers:
            for key in _keys(content):
                if not self.known(key) and key not in out:
                    out.append(key)
        return out

    def items(self) -> list[tuple[str, Any, str]]:
        """Every value as ``(dotted key, value, origin)``, sections in a stable order."""
        keys = _keys(DEFAULTS) + [k for k in _keys(self.data) if k not in _keys(DEFAULTS)]
        out = []
        for key in keys:
            found, value = _lookup(self.data, key)
            if found and not isinstance(value, dict):  # an empty table is no value
                out.append((key, value, self.origin(key)))
        return out

    def to_dict(self) -> dict:
        return copy.deepcopy(self.data)
