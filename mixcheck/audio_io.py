"""Loading audio files into a consistent format.

Everything downstream expects a float64 array shaped (samples, channels)
with values in the range -1.0 to 1.0, where 1.0 is digital full scale.
"""
from pathlib import Path

import numpy as np


def load_audio(path):
    """Return (samples, sample_rate). samples is float64, shape (n, channels)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")

    try:
        import soundfile as sf  # handles WAV, AIFF, FLAC and more
        data, sr = sf.read(str(path), always_2d=True, dtype="float64")
        return data, sr
    except ImportError:
        pass

    # Fallback: scipy can read WAV only.
    if path.suffix.lower() not in (".wav", ".wave"):
        raise RuntimeError(
            "Reading non-WAV files needs the 'soundfile' package: pip install soundfile"
        )
    from scipy.io import wavfile

    sr, raw = wavfile.read(str(path))
    data = _to_float(raw)
    if data.ndim == 1:
        data = data[:, None]
    return data, sr


def _to_float(raw):
    """Convert integer PCM to float in [-1, 1]."""
    if raw.dtype == np.int16:
        return raw.astype(np.float64) / 32768.0
    if raw.dtype == np.int32:  # scipy also returns 24-bit files as int32
        return raw.astype(np.float64) / 2147483648.0
    if raw.dtype == np.uint8:
        return (raw.astype(np.float64) - 128.0) / 128.0
    return raw.astype(np.float64)
