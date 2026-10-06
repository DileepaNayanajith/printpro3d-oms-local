#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
export LOCALAPPDATA="$PWD/instance/mac-station"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/instance/browser-binaries"
exec .venv/bin/python -u home_worker.py --kind fde
