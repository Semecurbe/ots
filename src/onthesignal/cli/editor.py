"""Script editing in an external terminal editor (vi, nano...)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..core.config import Config
from ..core.errors import ParameterError


def editor_command(config: Config) -> str:
    """Configured editor, else ``$EDITOR``, else ``nano`` (``vi`` as a last resort)."""
    for candidate in (config.get("console.editor"), os.environ.get("EDITOR"), "nano", "vi"):
        if candidate and shutil.which(str(candidate).split()[0]):
            return str(candidate)
    raise ParameterError("No text editor found: set [console] editor in the configuration")


def open_in_editor(path: Path, config: Config) -> int:
    """Open ``path`` in the editor and wait until it is closed."""
    command = editor_command(config).split()
    return subprocess.call([*command, str(path)])
