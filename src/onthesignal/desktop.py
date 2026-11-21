"""``onthesignal desktop``: the web interface in its own window, as a desktop application.

Like an Electron application, the window embeds a web engine: Chromium, through Qt WebEngine
(PySide6). The server of ``onthesignal web`` runs in a child process on a free port of the
loopback interface; the window shows its page. Closing the window stops the server cleanly
(an acquisition in progress is saved). Downloads ask where to save the file, and links to
other sites open in the usual browser.

Install the dependencies with ``pip install -e ".[web,desktop]"``; the AppImage built by
``packaging/appimage/build_appimage.py`` contains them. Without PySide6, the interface opens in
a window of Chrome or Chromium without browser bars (``--app``), or else in the browser.

The project folder is ``--project``, else the current folder, unless that is the home folder
(launched from the menu of applications): the last project is then proposed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ._version import __version__

PWA_ICON = Path(__file__).resolve().parent / "web" / "static" / "pwa" / "icon-512.png"
#: Subcommands passed to the usual command line (AppImage: ``onthesignal.AppImage web ...``).
CLI_COMMANDS = {"web", "acq", "rt", "run"}
STATE = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser() / "onthesignal"

LOADING_HTML = """<!DOCTYPE html><html><body style="font-family: system-ui, sans-serif;
background: #fcfcfb; color: #52514e; display: flex; align-items: center;
justify-content: center; height: 95vh"><div style="text-align: center">
<div style="font-size: 20px; color: #0b0b0b; margin-bottom: 8px">onthesignal</div>
<div>Starting the server of the project…</div><div style="font-size: 12px; margin-top: 6px">
{project}</div></div></body></html>"""

FAILED_HTML = """<!DOCTYPE html><html><body style="font-family: system-ui, sans-serif;
background: #fcfcfb; color: #0b0b0b; padding: 24px"><h3>The onthesignal server stopped</h3>
<p style="color: #52514e">Its messages (also in {log}):</p>
<pre style="background: #f0efec; padding: 12px; white-space: pre-wrap">{tail}</pre>
</body></html>"""


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="onthesignal desktop",
        description="onthesignal in its own window (web interface with an embedded web engine).",
        epilog="The AppImage also runs the other commands: 'onthesignal.AppImage --console', "
               "'... web', '... acq', '... rt', '... run'.")
    parser.add_argument("files", nargs="*", help="files loaded at start-up (miniSEED, text)")
    parser.add_argument("--project", help="project folder (default: the current folder)")
    parser.add_argument("--port", type=int, default=0, help="port of the server (default: free)")
    parser.add_argument("--browser", action="store_true",
                        help="use a window of Chrome/Chromium or the browser instead of Qt")
    parser.add_argument("--version", action="version", version=f"onthesignal {__version__}")
    return parser.parse_args(list(argv))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def server_command(project: Path, port: int, files: Sequence[str]) -> list[str]:
    """Command of the server child process (the same Python, so the AppImage works too)."""
    return [sys.executable, "-m", "onthesignal.cli.main", "web", "--no-browser",
            "--host", "127.0.0.1", "--port", str(port), "--project", str(project), *files]


def wait_for(url: str, timeout: float = 90.0, alive: Any = None) -> bool:
    """True once ``url`` answers; False after ``timeout`` or when ``alive()`` turns false."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if alive is not None and not alive():
            return False
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def log_path(project: Path) -> Path:
    """Messages of the server: in the project (``.onthesignal/logs``), else the user state."""
    for folder in (project / ".onthesignal" / "logs", STATE):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "desktop-server.log"
            path.touch()
            return path
        except OSError:
            continue
    return Path(os.devnull)


class Server:
    """The ``onthesignal web`` child process.

    It runs in its own process group, stopped as a whole: in the AppImage, the Python
    command is a shell script that starts the interpreter as its own child, so a signal to the
    direct child alone would leave the server running.
    """

    def __init__(self, project: Path, files: Sequence[str], port: int = 0) -> None:
        self.project = project
        self.port = port or free_port()
        self.url = f"http://127.0.0.1:{self.port}/"
        self.log = log_path(project)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
        self._log_file = self.log.open("w", encoding="utf-8")
        self.process = subprocess.Popen(server_command(project, self.port, files),
                                        cwd=project, stdout=self._log_file,
                                        stderr=subprocess.STDOUT, env=env,
                                        start_new_session=True)

    def alive(self) -> bool:
        return self.process.poll() is None

    def _group_alive(self) -> bool:
        try:
            os.killpg(self.process.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self.process.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def tail(self, n: int = 40) -> str:
        try:
            return "\n".join(self.log.read_text(encoding="utf-8", errors="replace")
                             .splitlines()[-n:])
        except OSError:
            return ""

    def stop(self, timeout: float = 15.0) -> None:
        """Ctrl+C equivalent: the server stops its jobs (acquisition saved), then exits;
        after ``timeout`` seconds, every process of its group is killed."""
        if self._group_alive():
            self._signal_group(signal.SIGTERM)
            end = time.monotonic() + timeout
            while self._group_alive() and time.monotonic() < end:
                time.sleep(0.1)
            if self._group_alive():
                self._signal_group(signal.SIGKILL)
        try:
            self.process.wait(2)
        except subprocess.TimeoutExpired:
            pass
        if not self._log_file.closed:
            self._log_file.close()


# ---------------------------------------------------------------------------------- project
def remembered_project() -> Path | None:
    try:
        text = (STATE / "last_project").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    path = Path(text)
    return path if path.is_dir() else None


def remember_project(project: Path) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "last_project").write_text(str(project), encoding="utf-8")
    except OSError:
        pass


def default_project(given: str | None) -> Path | None:
    """``--project``, else the current folder unless it is the home folder (menu launch)."""
    if given:
        return Path(given).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if cwd != Path.home().resolve():
        return cwd
    return None


# ---------------------------------------------------------------------------------- Qt window
def run_qt(args: argparse.Namespace) -> int:
    """The interface in a Qt window with the Chromium engine of Qt WebEngine."""
    from PySide6.QtCore import QObject, QSettings, Qt, QUrl, Signal
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("onthesignal")
    app.setOrganizationName("onthesignal")
    app.setDesktopFileName("onthesignal")
    if PWA_ICON.is_file():
        app.setWindowIcon(QIcon(str(PWA_ICON)))
    settings = QSettings()

    project = default_project(args.project)
    if project is None:
        start = remembered_project() or Path.home()
        chosen = QFileDialog.getExistingDirectory(None, "Project folder of onthesignal",
                                                  str(start))
        if not chosen:
            return 0
        project = Path(chosen)
    if not project.is_dir():
        QMessageBox.critical(None, "onthesignal", f"Project folder not found: {project}")
        return 2
    remember_project(project)
    folder: Path = project  # narrowed for the classes below
    server = Server(folder, args.files, args.port)

    class Ready(QObject):
        done = Signal(bool)

    class Page(QWebEnginePage):
        """Links to other sites, or opened in a new window, go to the usual browser."""

        def acceptNavigationRequest(self, url: Any, kind: Any, main_frame: bool) -> bool:
            local = url.scheme() in ("data", "about") or url.host() in ("127.0.0.1",
                                                                          "localhost")
            if main_frame and not local:
                QDesktopServices.openUrl(url)
                return False
            return True

        def createWindow(self, kind: Any) -> Any:
            page = QWebEnginePage(self.profile(), self)

            def open_outside(url: Any) -> None:
                QDesktopServices.openUrl(url)
                page.deleteLater()

            page.urlChanged.connect(open_outside)
            return page

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(f"onthesignal — {folder.name}")
            storage = STATE / "webengine"
            # No parent: the profile must outlive the page (deleted after the window).
            self.profile = QWebEngineProfile("onthesignal")
            self.profile.setPersistentStoragePath(str(storage))
            self.profile.setCachePath(str(storage / "cache"))
            self.profile.downloadRequested.connect(self.download)
            self.view = QWebEngineView(self)
            self.view.setPage(Page(self.profile, self.view))
            web = self.view.settings()
            web.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
            web.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
            self.view.titleChanged.connect(
                lambda title: self.setWindowTitle(f"{title} — {folder.name}"
                                                  if title else "onthesignal"))
            self.setCentralWidget(self.view)
            self.view.setHtml(LOADING_HTML.format(project=folder))
            geometry = settings.value("window/geometry")
            if geometry is not None:
                self.restoreGeometry(geometry)
            else:
                self.resize(1600, 1000)

        def download(self, request: Any) -> None:
            folder = request.downloadDirectory() or str(Path.home() / "Downloads")
            target, _ = QFileDialog.getSaveFileName(
                self, "Save", str(Path(folder) / request.downloadFileName()))
            if not target:
                request.cancel()
                return
            request.setDownloadDirectory(str(Path(target).parent))
            request.setDownloadFileName(Path(target).name)
            request.accept()

        def failed(self) -> None:
            self.view.setHtml(FAILED_HTML.format(log=server.log, tail=server.tail()
                                                 .replace("&", "&amp;").replace("<", "&lt;")))

        def closeEvent(self, event: Any) -> None:
            settings.setValue("window/geometry", self.saveGeometry())
            self.setWindowTitle("onthesignal — stopping the server…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            server.stop()
            QApplication.restoreOverrideCursor()
            event.accept()

    window = Window()
    ready = Ready()
    ready.done.connect(lambda ok: window.view.load(QUrl(server.url)) if ok else window.failed())
    threading.Thread(target=lambda: ready.done.emit(wait_for(server.url, alive=server.alive)),
                     daemon=True).start()
    window.show()
    try:
        return int(app.exec())
    finally:
        server.stop()
        import shiboken6

        profile = window.profile
        shiboken6.delete(window)  # the view and its page first, then their profile
        shiboken6.delete(profile)


# ---------------------------------------------------------------------------------- fallback
def chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "microsoft-edge"):
        path = shutil.which(name)
        if path:
            return path
    return None


def run_browser(args: argparse.Namespace) -> int:
    """Without Qt: a Chrome/Chromium window without browser bars, else the browser."""
    project = default_project(args.project) or remembered_project() or Path.cwd()
    server = Server(project, args.files, args.port)
    try:
        if not wait_for(server.url, alive=server.alive):
            print(server.tail(), file=sys.stderr)
            return 1
        print(f"onthesignal on {server.url} (project {project}); Ctrl+C to stop.")
        browser = chrome()
        if browser:
            data = STATE / "chrome-app"
            window = subprocess.Popen([browser, f"--app={server.url}",
                                       f"--user-data-dir={data}", "--no-first-run"])
            window.wait()
        else:
            webbrowser.open(server.url)
            server.process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and (argv[0] in CLI_COMMANDS or argv[0] == "--console"):
        from .cli.main import main as cli_main

        return cli_main(argv[1:] if argv[0] == "--console" else argv)
    args = parse_args(argv)
    if not args.browser:
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401
        except ImportError:
            print("Qt WebEngine is not installed (pip install -e '.[desktop]'): the interface "
                  "opens in a browser window instead.", file=sys.stderr)
        else:
            return run_qt(args)
    return run_browser(args)


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["Server", "default_project", "free_port", "main", "server_command", "wait_for"]
