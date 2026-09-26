#!/bin/bash
# Double-click this file in Finder to start Seraphim.
# The first run sets things up (about a minute); after that it opens straight away.

cd "$(dirname "$0")" || exit 1
clear
echo "Seraphim"
echo

if [ ! -x .venv/bin/mixcheck-web ]; then
  PY=$(command -v python3)
  if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    echo "Seraphim needs Python 3.9 or newer."
    echo "Install it from https://www.python.org/downloads/ and double-click Seraphim again."
    read -r -p "Press Return to close."
    exit 1
  fi
  echo "First run: setting up Seraphim. This takes about a minute..."
  if ! { "$PY" -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -e ".[web]"; }; then
    rm -rf .venv
    echo
    echo "Setup didn't finish. Check your internet connection and double-click Seraphim again."
    read -r -p "Press Return to close."
    exit 1
  fi
  echo "Done."
  echo
fi

exec .venv/bin/mixcheck-web
