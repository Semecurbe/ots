"""Web interface of onthesignal (NiceGUI + µPlot), see ``onthesignal_web.md``.

Started with ``onthesignal web``; needs the ``[web]`` dependencies
(``pip install -e ".[web]"``). The computation core is shared with the console: this package
only contains the user interface (rule R10 of the web specification).
"""


def main(argv=None) -> int:  # noqa: ANN001 - thin wrapper, see onthesignal.web.app.main
    from .app import main as _main

    return _main(argv)


__all__ = ["main"]
