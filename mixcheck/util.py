import os
import sys
from pathlib import Path

import numpy as np

TINY = 1e-20

# Which system this is, for the start-up messages and for which DAWs make sense (Logic Pro is Mac only).
PLATFORM = "mac" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "other"
PLATFORM_NAMES = {"mac": "Mac", "windows": "PC", "other": "computer"}
LAUNCHERS = {"mac": "Seraphim.command", "windows": "Seraphim.bat"}


def utf8_console():
    """Print UTF-8 whatever the console or redirect defaults to.

    Fix steps and messages use characters like the minus sign and angle quotes. Windows consoles and
    redirected output can default to a legacy code page that can't print them and raises an error;
    anything it still can't show becomes a replacement mark rather than a crash.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # not a real text stream, e.g. captured by a test runner
            pass


def db(amplitude):
    """Linear amplitude -> dB (dBFS when 1.0 is full scale)."""
    return 20.0 * np.log10(np.maximum(amplitude, TINY))


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def fmt_time(seconds):
    """83.4 -> '1:23'"""
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def mixcheck_home():
    """Where MixCheck keeps its own files (reference sets, calibration): ~/.mixcheck or $MIXCHECK_HOME."""
    return Path(os.environ.get("MIXCHECK_HOME") or Path.home() / ".mixcheck")
