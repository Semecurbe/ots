"""``onthesignal`` command-line entry point.

* ``onthesignal [files...]`` — interactive console, optionally loading files;
* ``onthesignal run script.py [args...]`` — run a standardized script non-interactively;
* ``onthesignal acq ...`` — SeedLink acquisition (see ``onthesignal acq --help``).
"""

from __future__ import annotations

import argparse
import runpy
import sys
from collections.abc import Sequence

from .._version import __version__


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "acq":
        from ..seedlink.acquisition import main as acq_main

        return acq_main(argv[1:])
    if argv and argv[0] == "rt":
        from ..seedlink.realtime import main as rt_main

        return rt_main(argv[1:])
    if argv and argv[0] == "run":
        if len(argv) < 2:
            print("Usage: onthesignal run <script.py> [arguments...]", file=sys.stderr)
            return 2
        sys.argv = [argv[1], *argv[2:]]
        runpy.run_path(argv[1], run_name="__main__")
        return 0
    parser = argparse.ArgumentParser(
        prog="onthesignal",
        description="Signal processing console for seismic acquisition chain characterization.",
        epilog="Subcommands: 'onthesignal run script.py ...', 'onthesignal acq ...'.",
    )
    parser.add_argument("files", nargs="*", help="files loaded at start-up (miniSEED, text)")
    parser.add_argument("--version", action="version", version=f"onthesignal {__version__}")
    args = parser.parse_args(argv)

    from .console import OnTheSignalConsole

    return OnTheSignalConsole(files=args.files).run()


if __name__ == "__main__":
    sys.exit(main())
