"""Synthetic signals with a known amount of reverb, to test the decay measurement against exact answers.

The reverb is an impulse response of noise whose level falls 60 dB over `rt60` seconds, so the true decay time is
known exactly. Sources are short sounds with abrupt endings (a voice-like harmonic tone, a drum-like noise burst).
"""
import numpy as np
from scipy.signal import fftconvolve

FS = 44100


def make_ir(rt60, fs=FS, seed=0, tail_to_direct_db=0.0):
    """A direct path plus a noise tail whose level falls 60 dB over rt60 seconds."""
    n = int((rt60 * 1.3 + 0.1) * fs)
    t = np.arange(n) / fs
    tail = np.random.default_rng(seed).standard_normal(n) * 10 ** (-3.0 * t / rt60)
    tail *= 10 ** (tail_to_direct_db / 20) / np.sqrt(np.sum(tail ** 2))
    ir = tail.copy()
    ir[0] += 1.0
    return ir


def sounds(kind, seconds=40.0, spacing=3.5, fs=FS, seed=0):
    """Sounds that stop abruptly, one every `spacing` seconds."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * fs))
    t0 = 0.5
    while t0 + 0.6 < seconds:
        if kind == "word":  # a voice-like harmonic tone, 0.4 s, with a short release
            n = int(0.4 * fs)
            t = np.arange(n) / fs
            f0 = rng.uniform(150, 300)
            s = sum(np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28)) / k for k in range(1, 25) if f0 * k < 8000)
            env = np.minimum(1.0, t / 0.01) * np.minimum(1.0, (t[-1] - t) / 0.005)
            s = s * env
        elif kind == "note":  # a plucked note that dies away slowly by itself (T60 about 1.2 s), with no room at all
            n = int(1.6 * fs)
            t = np.arange(n) / fs
            f0 = rng.uniform(110, 330)
            s = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 12)) * 10 ** (-3.0 * t / 1.2)
        else:  # "hit": a drum-like noise burst that dies away within about 50 ms
            n = int(0.08 * fs)
            t = np.arange(n) / fs
            s = rng.standard_normal(n) * np.exp(-t / 0.012)
        s = s / np.max(np.abs(s))
        i = int(t0 * fs)
        out[i:i + n] += s
        t0 += spacing * rng.uniform(0.9, 1.1)
    return out


def with_reverb(dry, rt60, fs=FS, seed=0):
    if rt60 is None:
        return dry.copy()
    return fftconvolve(dry, make_ir(rt60, fs, seed))[:len(dry)]


def with_bed(x, level_db, fs=FS, seed=1):
    """Add a steady broadband bed (other instruments) `level_db` below the peak level of x."""
    bed = np.random.default_rng(seed).standard_normal(len(x))
    bed *= np.max(np.abs(x)) * 10 ** (level_db / 20) / np.std(bed)
    return x + bed
