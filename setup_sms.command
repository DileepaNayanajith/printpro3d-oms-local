#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
.venv/bin/python configure_textlk.py
