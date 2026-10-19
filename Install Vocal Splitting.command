#!/bin/bash
# Double-click this file in Finder to add vocal splitting to Seraphim.
# It downloads PyTorch and the Demucs separation model (a large download, a few GB),
# so it can take several minutes. You only need to do it once.

cd "$(dirname "$0")" || exit 1
clear
echo "Seraphim: vocal splitting"
echo

if [ ! -x .venv/bin/pip ]; then
  echo "Open Seraphim once first (double-click Seraphim.command), then run this again."
  read -r -p "Press Return to close."
  exit 1
fi

echo "Installing the vocal-splitting packages. This can take several minutes..."
if ! .venv/bin/pip install -q -e ".[web,separate]"; then
  echo
  echo "Setup didn't finish. Check your internet connection and double-click this file again."
  read -r -p "Press Return to close."
  exit 1
fi

echo
echo "Done. Close Seraphim if it is open and start it again."
echo "The first time you split a vocal it also downloads the model (about 80 MB)."
read -r -p "Press Return to close."
