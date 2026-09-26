#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
exec .venv/bin/python sms_worker.py
