# Vendored JavaScript libraries

The web interface works offline: these libraries are shipped with the package and served by
the application (no CDN). Versions are pinned; update them deliberately and run the browser
tests (`ONTHESIGNAL_E2E=1 pytest tests/test_web_e2e.py`).

| Library | Version | Source | License | Files kept |
| --- | --- | --- | --- | --- |
| µPlot | 1.6.32 | npm `uplot@1.6.32` | MIT (`uplot/LICENSE`) | `dist/uPlot.esm.js` as `uplot/index.js`, `dist/uPlot.min.css` |
| Monaco Editor | 0.56.0 | npm `monaco-editor@0.56.0` | MIT (`monaco/LICENSE`, `monaco/ThirdPartyNotices.txt`) | AMD build `min/vs` |

xterm.js 6, Quasar 2.35 and Vue 3.5 come with NiceGUI 4 (`ui.xterm`) and are not vendored here:
their versions follow the NiceGUI version (`nicegui>=4.0,<5` in `pyproject.toml`).

## Monaco: removed parts

The AMD build of Monaco (deprecated upstream but still shipped, and the only one usable without a
bundler) is 24 MB. The following parts, not needed by onthesignal, were removed (6.2 MB left):

- `vs/assets/ts.worker-*.js`, `vs/language/typescript/ts.worker.js` (TypeScript and JavaScript
  language service);
- `vs/assets/css.worker-*.js`, `vs/assets/html.worker-*.js`, `vs/language/css/css.worker.js`,
  `vs/language/html/html.worker.js` (CSS and HTML language services);
- `vs/nls/lang/` (translations of the editor's own messages; the interface is in English).

Syntax highlighting of every language is kept; the files of the project use Python, Markdown,
TOML (shown with the INI highlighting), YAML, JSON and shell.

To update: `npm pack uplot@<version> monaco-editor@<version>`, copy the files listed above,
remove the same Monaco parts, update this table.
