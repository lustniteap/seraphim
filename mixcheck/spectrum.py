"""Rough tonal balance: share of energy in broad frequency bands."""
import numpy as np
from scipy.signal import welch

from .bands import ENERGY_BANDS


def measure_spectrum(x, fs):
    mono = x.mean(axis=1)
    nperseg = min(8192, len(mono))
    freqs, psd = welch(mono, fs, nperseg=nperseg)
    top = min(20000, fs / 2)
    total = psd[(freqs >= 20) & (freqs <= top)].sum()
    if total <= 0:
        return None

    bands = {}
    for name, lo, hi in ENERGY_BANDS:
        mask = (freqs >= lo) & (freqs < min(hi, top))
        bands[name] = round(float(psd[mask].sum() / total * 100), 2)

    # Almost nothing above 16 kHz can mean an MP3/AAC source or a heavy low-pass.
    air = psd[(freqs >= 16000) & (freqs <= top)].sum() / total * 100 if top > 16000 else None
    return {
        "band_energy_pct": bands,
        "energy_above_16k_pct": round(float(air), 4) if air is not None else None,
    }
