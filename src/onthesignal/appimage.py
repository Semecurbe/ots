"""Child processes when running inside the AppImage.

python-appimage makes ``sys.executable`` the AppImage itself (its Python reads
``APPIMAGE_COMMAND``), so that an AppImage holding only Python can start itself as an
interpreter. The entry point of the onthesignal AppImage is the desktop application: a child
process started with ``sys.executable`` (the server of the desktop window, the resource
tracker and the workers of ``multiprocessing`` that NiceGUI starts) would start the application
again, which refuses the arguments of Python (``unrecognized arguments: -s -c``).
:func:`python_executable` gives the interpreter inside the image instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def python_executable() -> str:
    """The Python interpreter to start child processes with.

    ``sys.executable`` everywhere except in the AppImage, where it is the AppImage: the
    interpreter of the image (``<APPDIR>/opt/python3.x/bin/python3.x``) is returned then.
    """
    executable = Path(sys.executable)
    if os.environ.get("APPIMAGE") and not executable.name.startswith("python"):
        version = f"{sys.version_info[0]}.{sys.version_info[1]}"
        image_python = Path(sys.prefix) / "bin" / f"python{version}"
        if image_python.is_file():
            return str(image_python)
    return sys.executable


def use_image_python() -> None:
    """Make ``multiprocessing`` start the Python of the image (no effect outside an AppImage).

    Called by the entry points before NiceGUI creates its process pool.
    """
    executable = python_executable()
    if executable != sys.executable:
        import multiprocessing

        multiprocessing.set_executable(executable)


def python_command(*args: str) -> list[str]:
    """Command running Python with ``args``, with the same isolation of the user's site
    packages as this process (``-s`` in the AppImage)."""
    return [python_executable(), *(["-s"] if sys.flags.no_user_site else []), *args]


__all__ = ["python_command", "python_executable", "use_image_python"]
