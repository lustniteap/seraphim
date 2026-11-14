"""The synthetic-label factory: put a known problem into a clean mix and write down what was done.

Each degradation takes clean stems, damages them by a known amount and returns the damaged mix
with a label. The label's category comes from the one vocabulary in docs/08-feedback-data.md
(missed_issues.category), so synthetic labels, human labels and detector output can be compared.

    mix, label = degrade(stems, fs, "mud_boost", strength=6.0)
    mix, label = degrade(stems, fs, None)          # the clean mix, labeled as clean

A strength is always in the unit the label names (dB, mostly), and bigger is always worse.
"""
import numpy as np
from scipy.signal import butter, lfilter, sosfilt

GENERATOR_VERSION = "degrade-0.1"

# The label vocabulary of docs/08-feedback-data.md. Add a category there first.
CATEGORIES = {
    "vocal_level", "vocal_harshness", "sibilance", "masking", "mud_low_mids", "sub_too_loud", "sub_too_quiet",
    "kick_808_clash", "harsh_top", "dull_top", "too_wide", "too_narrow", "dynamics_overcompressed",
    "dynamics_too_loose", "reverb_delay", "tuning_pitch", "timing", "noise_artifacts", "distortion",
    "arrangement", "other",
}


def _mix(stems):
    return sum(stems.values())


def _fft_gain(x, fs, gain_of):
    """Apply a gain per frequency (gain_of(freqs) -> linear gain) to every channel."""
    spec = np.fft.rfft(x, axis=0) * gain_of(np.fft.rfftfreq(len(x), 1 / fs))[:, None]
    return np.fft.irfft(spec, n=len(x), axis=0)


def _band_gain(lo, hi, db):
    return lambda f: np.where((f >= lo) & (f < hi), 10 ** (db / 20), 1.0)


def _mid_side(x, side_gain):
    mid, side = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2 * side_gain
    return np.column_stack([mid + side, mid - side])


def mud_boost(stems, fs, db, rng):
    return _fft_gain(_mix(stems), fs, _band_gain(250, 500, db)), {"bands": ["mud"], "boost_db": db}


def sub_boost(stems, fs, db, rng):
    return _fft_gain(_mix(stems), fs, _band_gain(20, 60, db)), {"bands": ["sub"], "boost_db": db}


def sub_cut(stems, fs, db, rng):
    return _fft_gain(_mix(stems), fs, _band_gain(0, 60, -db)), {"bands": ["sub"], "cut_db": db}


def harsh_resonance(stems, fs, db, rng):
    """A narrow bell (Q 8) somewhere in 2.5-4.5 kHz."""
    f0, q = float(rng.uniform(2500, 4500)), 8.0
    a_, w = 10 ** (db / 40), 2 * np.pi * f0 / fs
    alpha = np.sin(w) / (2 * q)
    b = [1 + alpha * a_, -2 * np.cos(w), 1 - alpha * a_]
    a = [1 + alpha / a_, -2 * np.cos(w), 1 - alpha / a_]
    return lfilter(b, a, _mix(stems), axis=0), {"bands": ["presence", "bite"], "hz": round(f0), "q": q, "boost_db": db}


def dull_top(stems, fs, db, rng):
    return _fft_gain(_mix(stems), fs, _band_gain(6000, 1e9, -db)), {"bands": ["sibilance", "air"], "cut_db": db}


def lows_out_of_phase(stems, fs, amount, rng):
    """Flip the right channel's polarity below 120 Hz. (amount is ignored: it is flipped or it isn't.)"""
    x = _mix(stems)
    x[:, 1] = _fft_gain(x[:, 1:], fs, lambda f: np.where(f < 120, -1.0, 1.0))[:, 0]
    return x, {"bands": ["sub", "bass"], "flipped_below_hz": 120}


def widen(stems, fs, db, rng):
    return _mid_side(_mix(stems), 10 ** (db / 20)), {"side_gain_db": db}


def narrow(stems, fs, db, rng):
    return _mid_side(_mix(stems), 10 ** (-db / 20)), {"side_gain_db": -db}


def crush(stems, fs, db, rng):
    """Drive the mix into a soft limiter by this many dB (what a slammed mix bus does)."""
    x = _mix(stems)
    ceiling = np.abs(x).max()
    return np.tanh(x * 10 ** (db / 20) / ceiling) * ceiling, {"drive_db": db}


def clip(stems, fs, db, rng):
    """Push the mix this many dB past full scale and cut it off flat."""
    x = _mix(stems)
    return np.clip(x * 10 ** (db / 20) / np.abs(x).max(), -1.0, 1.0), {"over_db": db}


def vocal_down(stems, fs, db, rng):
    quiet = {**stems, "vocals": stems["vocals"] * 10 ** (-db / 20)}
    return _mix(quiet), {"elements": ["vocals"], "cut_db": db}


def hiss(stems, fs, db, rng):
    """Add steady hiss this many dB above a floor 60 dB under the mix."""
    x = _mix(stems)
    noise = sosfilt(butter(2, 2000, "high", fs=fs, output="sos"), rng.standard_normal(x.shape), axis=0)
    level = np.sqrt(np.mean(x ** 2)) * 10 ** ((db - 60) / 20)
    return x + noise * level / np.sqrt(np.mean(noise ** 2)), {"noise_db_rel_mix": db - 60}


# kind -> (function, category, lowest and highest strength, unit)
KINDS = {
    "mud_boost": (mud_boost, "mud_low_mids", 4.0, 10.0, "dB"),
    "sub_boost": (sub_boost, "sub_too_loud", 5.0, 10.0, "dB"),
    "sub_cut": (sub_cut, "sub_too_quiet", 8.0, 18.0, "dB"),
    "harsh_resonance": (harsh_resonance, "harsh_top", 8.0, 15.0, "dB"),
    "dull_top": (dull_top, "dull_top", 6.0, 14.0, "dB"),
    "lows_out_of_phase": (lows_out_of_phase, "too_wide", 1.0, 1.0, "on"),
    "widen": (widen, "too_wide", 8.0, 14.0, "dB"),
    "narrow": (narrow, "too_narrow", 20.0, 40.0, "dB"),
    "crush": (crush, "dynamics_overcompressed", 10.0, 18.0, "dB"),
    "clip": (clip, "distortion", 3.0, 9.0, "dB"),
    "vocal_down": (vocal_down, "vocal_level", 4.0, 8.0, "dB"),
    "hiss": (hiss, "noise_artifacts", 20.0, 35.0, "dB"),
}
assert all(k[1] in CATEGORIES for k in KINDS.values())


def degrade(stems, fs, kind, strength=None, seed=0):
    """(mix, label). kind None gives the clean mix. strength None picks one at random in the kind's range."""
    rng = np.random.default_rng(seed)
    label = {"generator_version": GENERATOR_VERSION, "seed": seed, "kind": kind, "category": None,
             "strength": None, "unit": None, "time_range_s": [0.0, round(len(_mix(stems)) / fs, 2)], "detail": {}}
    if kind is None:
        return _mix(stems), label
    fn, category, lo, hi, unit = KINDS[kind]
    strength = float(rng.uniform(lo, hi)) if strength is None else float(strength)
    mix, detail = fn({name: s.copy() for name, s in stems.items()}, fs, strength, rng)
    detail = {k: round(v, 2) if isinstance(v, float) else v for k, v in detail.items()}
    label.update(category=category, strength=round(strength, 2), unit=unit, detail=detail)
    return mix, label
