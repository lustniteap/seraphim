import numpy as np

TINY = 1e-20


def db(amplitude):
    """Linear amplitude -> dB (dBFS when 1.0 is full scale)."""
    return 20.0 * np.log10(np.maximum(amplitude, TINY))


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def fmt_time(seconds):
    """83.4 -> '1:23'"""
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"
