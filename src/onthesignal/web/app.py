"""``onthesignal web``: start the web interface (web specification §3.4).

One server = one user = one project = one session, shared by every browser tab. The server
listens on the loopback interface by default and has no authentication (decision of
2026-11-20); every request is checked by :class:`~onthesignal.web.security.OriginGuard`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .._version import __version__

log = logging.getLogger("onthesignal.web")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="onthesignal web",
        description="Web interface of onthesignal (NiceGUI + µPlot): signals, analyses, "
                    "Python terminal, editor and AI chat in the browser.",
        epilog="Remote access: prefer an SSH tunnel (ssh -L 8080:127.0.0.1:8080 user@host).",
    )
    parser.add_argument("files", nargs="*", help="files loaded at start-up (miniSEED, text)")
    parser.add_argument("--host", default=None,
                        help="address to listen on (default [web] host, 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="port (default [web] port, 8080)")
    parser.add_argument("--project", default=".", help="project folder (default: current folder)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--version", action="version", version=f"onthesignal {__version__}")
    return parser.parse_args(list(argv or []))


def _socketio_origins(host: str, port: int, allowed: Sequence[str]) -> list[str] | str:
    """Origins accepted by socket.io (the OriginGuard middleware checks them as well)."""
    from .security import LOOPBACK, WILDCARDS

    if host in WILDCARDS and not allowed:
        return "*"
    names = set(LOOPBACK) | set(allowed) | ({host} - WILDCARDS)
    origins = []
    for name in sorted(names):
        shown = f"[{name}]" if ":" in name else name
        for scheme in ("http", "https"):
            origins.append(f"{scheme}://{shown}:{port}")
    return origins


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from nicegui import app, core, ui
    except ImportError:
        print("The web interface needs the [web] dependencies: pip install -e '.[web]'",
              file=sys.stderr)
        return 2

    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        print(f"Project folder not found: {project}", file=sys.stderr)
        return 2
    os.chdir(project)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from .. import api
    from ..core.config import Config
    from ..core.session import Session, set_session
    from .components import VENDOR, VENDOR_URL
    from .security import LOOPBACK, OriginGuard
    from .state import WebState
    from .terminal import install_stream_routing
    from .ui.workbench import Workbench

    config = Config.load()
    logs = project / str(config.get("paths.state", ".onthesignal")) / "logs"
    try:
        logs.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(logs / "web.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: "
                                               "%(message)s"))
        journal = logging.getLogger("onthesignal.web")
        journal.addHandler(handler)
        journal.setLevel(logging.INFO)
    except OSError as exc:  # a read-only project must not prevent the start
        print(f"Cannot write the journal in {logs}: {exc}", file=sys.stderr)
    host = args.host or str(config.get("web.host", "127.0.0.1"))
    port = int(args.port or config.get("web.port", 8080))
    allowed = [str(h) for h in config.get("web.allowed_hosts", []) or []]

    session = Session(config=config, interactive=True)
    set_session(session, default=True)
    install_stream_routing()
    state = WebState(session, str(project))
    plt.show = lambda *a, **k: state.capture_figures()  # type: ignore[assignment]

    def show_warning(message: Any, category: type, filename: str, lineno: int,
                     file: Any = None, line: str | None = None) -> None:
        if state.terminal.in_terminal_thread():
            state.terminal.display.warning(str(message))
        elif issubclass(category, UserWarning):
            state.warn(str(message))

    warnings.showwarning = show_warning

    for path in args.files:
        try:
            api.load(path)
        except Exception as exc:  # a bad file must not prevent the start
            print(f"Cannot load {path}: {exc}", file=sys.stderr)

    reports = project / str(config.get("paths.reports", "reports"))
    reports.mkdir(parents=True, exist_ok=True)
    app.add_static_files(VENDOR_URL, str(VENDOR))
    app.add_static_files("/_ots/reports", str(reports))
    docs = Path(__file__).resolve().parents[3] / "docs" / "_site"
    docs_url = ""
    if docs.is_dir():
        app.add_static_files("/docs", str(docs))
        docs_url = "/docs/index.html"
    app.add_middleware(OriginGuard, bind_host=host, allowed_hosts=allowed)
    core.sio.eio.cors_allowed_origins = _socketio_origins(host, port, allowed)

    @ui.page("/")
    def index(client: Any) -> None:
        state.log("client", f"browser tab connected from {getattr(client, 'ip', '?')}")
        Workbench(state, client, project, docs_url).build()

    def startup() -> None:
        if state.code_execution:
            state.terminal.start()

    def shutdown() -> None:
        for job in state.jobs.running():
            if job.cancel is not None:
                try:
                    job.cancel()
                except Exception:
                    log.exception("Cannot stop %s", job.name)
        state.terminal.stop()

    app.on_startup(startup)
    app.on_shutdown(shutdown)

    shown_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    print(f"onthesignal {__version__} — web interface on http://{shown_host}:{port} "
          f"(project {project}). Ctrl+C to stop.")
    if host not in LOOPBACK:
        print("WARNING: the server listens on the network and has no authentication: anyone "
              "who can reach this port can run Python code with your account. Prefer an SSH "
              "tunnel; set [web] code_execution = false for a shared network.",
              file=sys.stderr)
    tls = {k: str(config.get(f"web.{k}")) for k in ("tls_cert", "tls_key")
           if config.get(f"web.{k}")}
    ui.run(host=host, port=port, title="onthesignal", reload=False,
           show=not args.no_browser and bool(config.get("web.open_browser", True)),
           show_welcome_message=False, favicon="📈", uvicorn_logging_level="warning",
           ssl_certfile=tls.get("tls_cert"), ssl_keyfile=tls.get("tls_key"))
    return 0


__all__ = ["main", "parse_args"]
