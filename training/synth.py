"""Synthesized multitracks: clean "songs" with stems, made from nothing but math.

Owned material (docs/09 licensing: "synthetic test signals and synthesized stems"), so it can be
used anywhere. These are not music; they are stand-ins with the right kinds of parts (a kick, an
808, a snare, hats, a pad, a voice-like lead) to prove the degradation generator and to give the
rules baseline something to be scored on until licensed multitracks are in the shared bucket.

song(seed) -> ({"vocals", "drums", "bass", "other"}: (samples, 2) arrays, fs)
"""
import numpy as np
from scipy.signal import butter, sosfilt

FS = 48000
STEMS = ("vocals", "drums", "bass", "other")
LICENSE = "owned-synthetic"


def _band(x, fs, lo=None, hi=None, order=2):
    if lo and hi:
        sos = butter(order, [lo, hi], "band", fs=fs, output="sos")
    else:
        sos = butter(order, lo or hi, "high" if lo else "low", fs=fs, output="sos")
    return sosfilt(sos, x, axis=0)


def _place(out, sound, at):
    end = min(len(out), at + len(sound))
    if at < end:
        out[at:end] += sound[:end - at]


def song(seed, seconds=20.0, fs=FS):
    """One clean synthetic song as four stereo stems. The same seed always gives the same song."""
    rng = np.random.default_rng(seed)
    n = int(seconds * fs)
    beat = 60.0 / rng.uniform(80, 150)
    root = rng.uniform(36, 55)                      # 808 root, Hz
    beats = np.arange(0, seconds, beat)
    mono = lambda x: np.column_stack([x, x])

    # Drums: kick on every beat, snare on 2 and 4, hats on the eighths.
    t = np.arange(int(0.3 * fs)) / fs
    kick = np.sin(2 * np.pi * (45 * t + (120 - 45) * 0.03 * (1 - np.exp(-t / 0.03)))) * np.exp(-t / 0.09)
    t = np.arange(int(0.2 * fs)) / fs
    snare = _band(rng.standard_normal(len(t)), fs, 180, 7000) * np.exp(-t / 0.06)
    t = np.arange(int(0.06 * fs)) / fs
    hat = _band(rng.standard_normal(len(t)), fs, lo=7000) * np.exp(-t / 0.015)
    drums = np.zeros((n, 2))
    for i, b in enumerate(beats):
        _place(drums, mono(0.9 * kick), int(b * fs))
        if i % 2 == 1:
            _place(drums, mono(0.35 * snare), int(b * fs))
        for off in (0.0, 0.5):
            pan = rng.uniform(0.3, 0.7)
            _place(drums, 0.12 * hat[:, None] * np.array([1 - pan, pan]) * 2, int((b + off * beat) * fs))

    # 808: one long note per bar, a sine with a little saturation.
    bass = np.zeros(n)
    bar = 4 * beat
    for i, start in enumerate(np.arange(0, seconds, bar)):
        t = np.arange(int(bar * fs)) / fs
        f = root * (1, 1, 4 / 3, 3 / 2)[i % 4]
        _place(bass, np.tanh(2.0 * np.sin(2 * np.pi * f * t)) * np.exp(-t / (0.6 * bar)), int(start * fs))
    bass = mono(0.5 * _band(bass, fs, hi=400))

    # Pad: a detuned saw chord that changes every bar and drifts slightly in pitch (so no single
    # harmonic rings for the whole song), darker than the lead, different in each channel (so it has width).
    t = np.arange(n) / fs
    bar_no = np.minimum((t / bar).astype(int), 10 ** 6)
    chord = np.array([1, 4 / 3, 3 / 2, 9 / 8])[bar_no % 4]
    pad = np.zeros((n, 2))
    for ratio in (1, 5 / 4, 3 / 2):
        for ch, detune in enumerate((0.997, 1.003)):
            drift = 1 + 0.012 * np.sin(2 * np.pi * rng.uniform(0.1, 0.4) * t + rng.uniform(0, 6.28))
            f = root * 4 * ratio * detune * chord * drift
            pad[:, ch] += 2 * ((np.cumsum(f) / fs + rng.uniform()) % 1.0) - 1
    other = 0.07 * _band(pad, fs, 150, 2500)

    # Lead "voice": a buzzy tone with vibrato through three broad vowel-like resonances, in phrases
    # on a different note each, with a short burst of sibilance at the start of each phrase.
    starts = np.arange(rng.uniform(0, bar), seconds, bar)
    note = np.ones(n)
    for start in starts:
        note[int(start * fs):] = rng.choice([1, 9 / 8, 5 / 4, 4 / 3, 3 / 2])
    f0 = root * 4 * note * (1 + 0.015 * np.sin(2 * np.pi * 5.5 * t))
    phase = 2 * np.pi * np.cumsum(f0) / fs
    buzz = sum(np.sin(k * phase) / k for k in range(1, 40))
    voice = sum(g * _band(buzz, fs, f * 0.6, f * 1.6, order=1) for f, g in ((700, 1.0), (1200, 0.6), (2600, 0.35)))
    gate = np.zeros(n)
    for start in starts:
        a, b = int(start * fs), int(min(seconds, start + 0.6 * bar) * fs)
        gate[a:b] = 1.0
        s = _band(rng.standard_normal(int(0.08 * fs)), fs, 6000, 10000) * np.hanning(int(0.08 * fs))
        _place(voice, 0.4 * np.abs(voice).max() * s, a)
    gate = np.convolve(gate, np.hanning(int(0.03 * fs)) / np.hanning(int(0.03 * fs)).sum(), mode="same")
    vocals = mono(voice * gate)
    vocals *= 0.12 / max(np.sqrt(np.mean(vocals ** 2)), 1e-9)

    stems = {"vocals": vocals, "drums": drums, "bass": bass, "other": other}
    # Random but sensible balance, then leave headroom: the clean mix peaks at -6 dBFS.
    for name in stems:
        stems[name] = stems[name] * 10 ** (rng.uniform(-2, 2) / 20)
    peak = np.abs(sum(stems.values())).max()
    return {name: s * (0.5 / peak) for name, s in stems.items()}, fs
