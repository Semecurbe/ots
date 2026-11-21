"""The web interface as an installable application (progressive web app, PWA).

Chrome, Edge and Safari can install ``onthesignal web`` as an application: its own window
without the browser bars, an icon in the menu of applications or the dock, and a title bar in
the color of the interface. This module provides what they need:

* the manifest ``/manifest.webmanifest`` (name, icons, start page, standalone window);
* the service worker ``/sw.js``. The interface is driven by the server in real time, so
  nothing is served from a cache: when the server is not running, the window shows an
  offline page explaining how to start it;
* the icons and the offline page in ``web/static/pwa`` (``python -m onthesignal.web.pwa``
  draws the icons again).

A browser only installs an application from a secure context: ``http://127.0.0.1`` and
``http://localhost`` (also through an SSH tunnel), or HTTPS (``[web] tls_cert``).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PWA_DIR = Path(__file__).resolve().parent / "static" / "pwa"
PWA_URL = "/_ots/pwa"
#: Brand blue (first categorical slot of ``plot.style``) and surface of the interface.
BLUE = "#2a78d6"
SURFACE = "#fcfcfb"
ICONS = (("icon-192.png", 192, "any"), ("icon-512.png", 512, "any"),
         ("icon-maskable-512.png", 512, "maskable"))

SERVICE_WORKER = """// Service worker of onthesignal (web/pwa.py): makes the interface installable.
// The interface is driven by the server in real time: pages are never served from a cache.
// When the server cannot be reached, the window shows the offline page instead.
const CACHE = "onthesignal-pwa-v1";
const OFFLINE = "__PWA_URL__/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll([OFFLINE])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return; // scripts, data, websocket: the network
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
""".replace("__PWA_URL__", PWA_URL)


def manifest(name: str = "onthesignal") -> dict[str, Any]:
    """Web application manifest (``/manifest.webmanifest``)."""
    return {
        "id": "/",
        "name": name,
        "short_name": "onthesignal",
        "description": "Characterization of seismic acquisition chains: noise, NLNM, sine "
                       "tests, SeedLink acquisition and real time, reports, Python terminal and "
                       "AI assistant.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": SURFACE,
        "theme_color": SURFACE,
        "icons": [{"src": f"{PWA_URL}/{file}", "sizes": f"{size}x{size}", "type": "image/png",
                   "purpose": purpose} for file, size, purpose in ICONS],
    }


def head_html() -> str:
    """Links to the manifest and icons, and registration of the service worker."""
    return (f'<link rel="manifest" href="/manifest.webmanifest">'
            f'<meta name="theme-color" content="{SURFACE}">'
            f'<link rel="apple-touch-icon" href="{PWA_URL}/icon-192.png">'
            '<script>if ("serviceWorker" in navigator) window.addEventListener("load", () => '
            'navigator.serviceWorker.register("/sw.js").catch(() => {}));</script>')


def install(app: Any, name: str = "onthesignal") -> None:
    """Serve the manifest, the service worker, the icons and the offline page."""
    from fastapi.responses import Response

    text = json.dumps(manifest(name), ensure_ascii=False, indent=1)

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def _manifest() -> Response:
        return Response(text, media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js", include_in_schema=False)
    def _service_worker() -> Response:
        return Response(SERVICE_WORKER, media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})

    app.add_static_files(PWA_URL, str(PWA_DIR))


# ---------------------------------------------------------------------------------- icons
def _waveform(size: int, inset: float) -> list[tuple[float, float]]:
    """Points of a seismogram-like trace: a wave packet on a quiet line."""
    left, right = size * inset, size * (1 - inset)
    middle, height = size / 2, size * (1 - 2 * inset) * 0.42
    points = []
    for i in range(601):
        u = i / 600
        envelope = math.exp(-(((u - 0.5) / 0.13) ** 2))
        y = envelope * math.sin(2 * math.pi * 6 * (u - 0.5))
        points.append((left + u * (right - left), middle - y * height))
    return points


def draw_icon(size: int, maskable: bool = False) -> Any:
    """Icon of the application: a white wave packet on the brand blue.

    A maskable icon fills the square (the system cuts its own shape) and keeps the drawing in
    the central safe zone.
    """
    from PIL import Image, ImageDraw

    scale = 4  # drawn larger, then reduced: smooth edges
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if maskable:
        draw.rectangle([0, 0, big, big], fill=BLUE)
    else:
        draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.22), fill=BLUE)
    inset = 0.24 if maskable else 0.14
    draw.line(_waveform(big, inset), fill="white", width=max(2, int(big * 0.04)),
              joint="curve")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def make_icons(folder: Path = PWA_DIR) -> list[Path]:
    """Draw the icons of the manifest into ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for file, size, purpose in ICONS:
        path = folder / file
        draw_icon(size, purpose == "maskable").save(path, optimize=True)
        paths.append(path)
    return paths


if __name__ == "__main__":
    for path in make_icons():
        print(path)


__all__ = ["PWA_DIR", "PWA_URL", "SERVICE_WORKER", "draw_icon", "head_html", "install",
           "make_icons", "manifest"]
