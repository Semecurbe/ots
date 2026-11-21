#! /bin/bash
# Entry point of the AppImage (template of python-appimage): the desktop application;
# "--console", "web", "acq", "rt" and "run" give the usual commands.
{{ python-executable }} -s -m onthesignal.desktop "$@"
