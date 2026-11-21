"""``python -m onthesignal``: the command line, as the ``onthesignal`` command."""

import sys

from .cli.main import main

if __name__ == "__main__":
    sys.exit(main())
