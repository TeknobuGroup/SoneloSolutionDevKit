#!/bin/sh
# Sonelo Solution DevKit - Mac/Linux installer. Windows: double-click install.cmd.
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python) || { echo "Python 3 is required (python.org or your package manager)."; exit 1; }
"$PY" repo_setup.py install "$@"
