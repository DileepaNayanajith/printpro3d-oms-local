#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
export LOCALAPPDATA="$PWD/instance/mac-station"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/instance/browser-binaries"
exec .venv/bin/python -u station_controller.py >> "$LOCALAPPDATA/PRINTPRO3D-station/controller.log" 2>&1
