"""Security of the web interface (web specification §12).

The interface has no authentication (decision of 2026-11-20): it listens on the loopback
interface by default, and every request and WebSocket connection is checked so that a web
page of another site, opened in the same browser, cannot drive the server:

* the ``Host`` header must name the server (protection against DNS rebinding);
* the ``Origin`` header, when present, must be the server itself (cross-site requests and
  cross-site WebSocket hijacking).

Files are only served or written inside the roots of the project.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger("onthesignal.web.security")

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
WILDCARDS = {"0.0.0.0", "::", ""}

#: Rendered reports are self-contained Quarto pages: their scripts and styles are data URIs.
REPORTS_PREFIX = "/_ots/reports/"
REPORT_CSP = (b"default-src 'self'; script-src 'self' 'unsafe-inline' data:; "
              b"style-src 'self' 'unsafe-inline' data:; img-src 'self' data: blob:; "
              b"font-src 'self' data:; frame-ancestors 'self'")

#: HTTP headers added to every response.
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"referrer-policy", b"same-origin"),
    (b"content-security-policy",
     b"default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
     b"style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
     b"worker-src 'self' blob:; connect-src 'self' ws: wss:; frame-ancestors 'self'"),
]


def _hostname(value: str) -> str:
    """Host name of a ``Host`` header (``[::1]:8080`` → ``::1``)."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class OriginGuard:
    """ASGI middleware checking ``Host`` and ``Origin`` of HTTP and WebSocket requests.

    Parameters
    ----------
    app : ASGI application
    bind_host : str
        Address the server listens on.
    allowed_hosts : iterable of str
        Additional host names allowed in the ``Host`` header (``[web] allowed_hosts``). When
        the server listens on every interface and no host is configured, any host name is
        accepted (the start-up warning says that the server is exposed).
    """

    def __init__(self, app: Any, bind_host: str = "127.0.0.1",
                 allowed_hosts: Iterable[str] = ()) -> None:
        self.app = app
        extra = {h.lower() for h in allowed_hosts}
        self.any_host = bind_host in WILDCARDS and not extra
        self.hosts = LOOPBACK | extra | ({bind_host.lower()} - WILDCARDS)

    def host_allowed(self, host_header: str) -> bool:
        return self.any_host or _hostname(host_header) in self.hosts

    @staticmethod
    def origin_allowed(origin: str, host_header: str) -> bool:
        if origin in ("", "null"):
            return origin == ""
        parts = urlsplit(origin)
        return parts.netloc.lower() == host_header.strip().lower()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        origin = headers.get("origin")
        reason = ""
        if not self.host_allowed(host):
            reason = f"host {host!r} not allowed"
        elif origin is not None and not self.origin_allowed(origin, host):
            reason = f"origin {origin!r} differs from host {host!r}"
        if reason:
            client = scope.get("client") or ("?", 0)
            log.warning("Refused %s %s from %s: %s", scope["type"], scope.get("path"),
                        client[0], reason)
            await self._refuse(scope, receive, send)
            return
        if scope["type"] == "http":
            report = str(scope.get("path", "")).startswith(REPORTS_PREFIX)
            await self.app(scope, receive, self._with_headers(send, report))
        else:
            await self.app(scope, receive, send)

    @staticmethod
    def _with_headers(send: Any, report: bool = False) -> Any:
        headers = [(k, REPORT_CSP if report and k == b"content-security-policy" else v)
                   for k, v in SECURITY_HEADERS]

        async def wrapped(message: dict) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in headers if k not in names]
            await send(message)

        return wrapped

    @staticmethod
    async def _refuse(scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            message = await receive()
            if message.get("type") == "websocket.connect":
                await send({"type": "websocket.close", "code": 1008})
            return
        body = b"Forbidden: request refused by onthesignal (Host or Origin check)\n"
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def confine(path: str | Path, roots: Iterable[Path]) -> Path:
    """Resolve ``path`` (relative to the first root) and check that it lies in a root.

    Symbolic links are followed before the check, so a link pointing outside the project is
    refused like ``../../etc/passwd``.
    """
    roots = [Path(r).resolve() for r in roots]
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    if not any(resolved == r or resolved.is_relative_to(r) for r in roots):
        raise PermissionError(f"{path} is outside the project")
    return resolved


def safe_name(name: str) -> str:
    """File name of an upload, without directories or control characters."""
    name = Path(name.replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*').strip(". ")
    return name or "upload"


__all__ = ["OriginGuard", "confine", "safe_name"]
