#!/usr/bin/env python3
"""Build the AppImage of onthesignal: one file that runs on Linux without installation.

The AppImage contains a Python interpreter (base image of python-appimage), onthesignal with
its web, AI and desktop dependencies (PySide6 and Qt WebEngine), and starts
``onthesignal desktop``: the web interface in its own window. Quarto is not included:
install it on the computer to render the reports.

Usage::

    pip install python-appimage          # once, in any Python environment
    python packaging/appimage/build_appimage.py [--python 3.13] [--workdir /tmp/ots-appimage]

The AppImage is written to ``dist/onthesignal-<version>-x86_64.AppImage``. The build downloads
the Python base image (GitHub) and the wheels (PyPI): about 600 MB, and needs about 3 GB in
the working folder.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ICON = ROOT / "src" / "onthesignal" / "web" / "static" / "pwa" / "icon-512.png"
EXTRAS = "web,ai,desktop"


def version() -> str:
    namespace: dict = {}
    exec((ROOT / "src" / "onthesignal" / "_version.py").read_text(encoding="utf-8"), namespace)
    return str(namespace["__version__"])


def run(command: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def build_wheel(folder: Path) -> Path:
    """Wheel of the project (without its dependencies, which pip installs in the AppImage)."""
    folder.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-cache-dir", "-w",
         str(folder), str(ROOT)])
    wheels = sorted(folder.glob("onthesignal-*.whl"))
    if not wheels:
        raise SystemExit("The wheel of onthesignal was not built")
    return wheels[-1]


def recipe(folder: Path, wheel: Path) -> Path:
    """Folder read by ``python-appimage build app``."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("onthesignal.desktop", "entrypoint.sh", "onthesignal.appdata.xml"):
        shutil.copy(HERE / name, folder / name)
    shutil.copy(ICON, folder / "onthesignal.png")
    (folder / "requirements.txt").write_text(f"{wheel}[{EXTRAS}]\n", encoding="utf-8")
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--python", default="3.13", help="Python of the AppImage (3.11 to 3.14)")
    parser.add_argument("--workdir", help="working folder (default: a temporary folder)")
    parser.add_argument("--output", default=str(ROOT / "dist"), help="folder of the AppImage")
    args = parser.parse_args(argv)
    try:
        import python_appimage  # noqa: F401
    except ImportError:
        raise SystemExit("python-appimage is needed: pip install python-appimage") from None

    work = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="ots-appimage-"))
    work.mkdir(parents=True, exist_ok=True)
    wheel = build_wheel(work / "wheels")
    app = recipe(work / "onthesignal", wheel)
    run([sys.executable, "-m", "python_appimage", "build", "app", "-p", args.python,
         str(app)], cwd=work)
    built = work / "onthesignal-x86_64.AppImage"
    if not built.is_file():
        raise SystemExit(f"No AppImage in {work}")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"onthesignal-{version()}-x86_64.AppImage"
    shutil.move(str(built), target)
    target.chmod(0o755)
    print(f"AppImage written to {target} ({target.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
