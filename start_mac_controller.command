#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
export LOCALAPPDATA="$PWD/instance/mac-station"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/instance/browser-binaries"
.venv/bin/python -u home_worker.py --kind print >> "$LOCALAPPDATA/PRINTPRO3D-station/print-worker.log" 2>&1 &
exec .venv/bin/python -u station_controller.py >> "$LOCALAPPDATA/PRINTPRO3D-station/controller.log" 2>&1
