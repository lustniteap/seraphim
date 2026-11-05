"""Decay measurement: how fast sound dies away after it stops (the reverb measurement tool).

Where a sound ends, such as a phrase, a held note or a drum hit, the level then falls. How quickly it falls, band by
band, says how much reverb or room there is. This module finds those endings in a finished audio file and measures
the fall.

The idea, in one fact: after a sound stops, the level cannot fall faster than the room allows. So the *fastest* clean
decays in a song are the best estimate of the room, and slower ones are the source itself or other sounds filling in.

What it returns is a measurement with a confidence, never a verdict:

  t60_s     how long the level would take to fall 60 dB, from the fall measured between 5 and 25 dB below the
            level where the sound stopped (a "T20" reading, scaled up to 60 dB)
  events    clean decays used, out of those found

**Read t60_s as an upper limit on the room.** The room can't be slower than the fall that was observed, but a source
that rings by itself (a plucked or held note) can make the fall look slower than the room. Nothing in the decay alone
tells the two apart: the measured confidence says how well the fall was measured, not whose it is. So the result is
tight when the sources stop abruptly (a voice, a drum hit) and loose when they ring. The audio model's description
of what is playing is what tells the reasoning layer which case this is.

It says "couldn't tell" when there are too few clean decays. In a dense mix nearly every ending is covered by
something else, so that answer is normal there. Pre-delay and the wet-to-dry balance can't be recovered from a
finished mix by this method, and it doesn't claim to.

Only numbers leave this module. The audio is read and not kept.
"""
import math

import numpy as np
from scipy.signal import butter, find_peaks, sosfilt

DECAY_VERSION = 1

# Reverb tails differ by frequency, so each band gets its own reading.
DECAY_BANDS = [("low", 125, 500), ("mid", 500, 2000), ("high", 2000, 8000)]

ENV_WINDOW_S = 0.020    # smoothing of the energy envelope
HOP_S = 0.010           # envelope resolution
PROMINENCE_DB = 20.0    # an ending must stand this far above what is around it to count as an event
PLATEAU_DB = 1.0        # a held sound counts as ended when it leaves this band below its top
FIT_FROM_DB = 5.0       # the fall is read from here ...
FIT_TO_DB = 25.0        # ... to here, below the level where the sound stopped
RISE_DB = 3.0           # new energy: the decay stops being clean
MAX_TAIL_S = 6.0
MIN_R2 = 0.90           # how straight the fall must be, in dB against time
MIN_EVENTS = 3          # fewer clean decays than this and it says it couldn't tell
FLOOR_T60_S = 0.15      # below this the smoothing can't resolve a tail: reported as "no measurable tail"
FAST_T60_S = 0.10       # stand-in value for an ending too quick to measure (it is under FLOOR_T60_S)
TOP_PERCENTILE = 20     # which of the decays to trust: the fast end, as the room can't be faster than the sound


def _band_filter(x, fs, lo, hi):
    hi = min(hi, 0.45 * fs)
    if lo >= hi:
        return None
    return sosfilt(butter(4, [lo, hi], "bandpass", fs=fs, output="sos"), x)


def _envelope_db(y, fs):
    """Smoothed energy in dB, one value per HOP_S."""
    w = max(1, int(round(ENV_WINDOW_S * fs)))
    c = np.cumsum(np.concatenate(([0.0], y * y)))
    mean = (c[w:] - c[:-w]) / w
    hop = max(1, int(round(HOP_S * fs)))
    return 10.0 * np.log10(mean[::hop] + 1e-12)


def _events(env_db):
    """Every ending found in the envelope: [{"start_s", "t60_s", "r2"}] for the clean ones, plus the number found."""
    peaks, _ = find_peaks(env_db, prominence=PROMINENCE_DB)
    n, clean = len(env_db), []
    max_len = int(MAX_TAIL_S / HOP_S)
    for p in peaks:
        j = p
        while j + 1 < n and env_db[j + 1] >= env_db[p] - PLATEAU_DB:  # to the end of a held sound
            j += 1
        top = env_db[j]
        k, low, reached = j, top, False
        while k < min(n - 1, j + max_len):
            k += 1
            if env_db[k] > low + RISE_DB:  # something new came in: the decay is no longer clean
                break
            low = min(low, env_db[k])
            if env_db[k] <= top - FIT_TO_DB:
                reached = True
                break
        if not reached:
            continue
        seg = env_db[j:k + 1]
        t = np.arange(len(seg)) * HOP_S
        keep = (seg <= top - FIT_FROM_DB) & (seg >= top - FIT_TO_DB - 2.0)
        if keep.sum() < 5:  # fell 25 dB within a few hops: too quick to measure, so there is no tail to speak of
            clean.append({"start_s": (j * HOP_S) + ENV_WINDOW_S / 2, "t60_s": FAST_T60_S, "r2": MIN_R2})
            continue
        slope, icpt = np.polyfit(t[keep], seg[keep], 1)
        if slope >= 0:
            continue
        pred = slope * t[keep] + icpt
        ss_res = float(np.sum((seg[keep] - pred) ** 2))
        ss_tot = float(np.sum((seg[keep] - seg[keep].mean()) ** 2)) or 1e-12
        r2 = 1.0 - ss_res / ss_tot
        if r2 < MIN_R2:
            continue
        clean.append({"start_s": (j * HOP_S) + ENV_WINDOW_S / 2, "t60_s": -60.0 / slope, "r2": r2})
    return clean, len(peaks)


def _in_ranges(t, ranges):
    return ranges is None or any(a <= t <= b for a, b in ranges)


def _band_result(clean, found):
    """One band's reading and how far to trust it. Endings too quick to measure count as very short decays."""
    if len(clean) < MIN_EVENTS:
        return {"status": "couldnt_tell", "events": len(clean), "events_found": found, "confidence": 0.0,
                "reason": "too few clean decays to read"}
    t60 = np.array([e["t60_s"] for e in clean])
    q25, q75 = np.percentile(t60, [25, 75])
    est = float(np.percentile(t60, TOP_PERCENTILE))
    spread = (q75 - q25) / max(est, 0.05)
    quality = float(np.mean([e["r2"] for e in clean]))
    confidence = (1 - math.exp(-len(clean) / 4)) * (1 - min(1.0, spread)) * quality
    no_tail = est < FLOOR_T60_S
    return {"status": "estimated", "t60_s": None if no_tail else round(est, 2),
            "range_s": None if no_tail else [round(float(t60.min()), 2), round(float(t60.max()), 2)],
            "no_measurable_tail": no_tail, "below_s": FLOOR_T60_S if no_tail else None,
            "events": len(clean), "events_found": found,
            "confidence": round(max(0.0, min(1.0, confidence)), 2)}


def measure_decay(x, fs, ranges=None):
    """Decay of the sound after it stops, per band and overall, from a (samples, channels) array.

    ranges: optional [(start_s, end_s)] to read only the endings that begin inside them (for example the sections
    the audio model labelled). None reads the whole file.
    """
    mono = x.mean(axis=1) if x.ndim == 2 else x
    bands, estimated = {}, []
    for name, lo, hi in DECAY_BANDS:
        y = _band_filter(mono, fs, lo, hi)
        if y is None:
            continue
        clean, found = _events(_envelope_db(y, fs))
        clean = [e for e in clean if _in_ranges(e["start_s"], ranges)]
        bands[name] = _band_result(clean, found)
        if bands[name]["status"] == "estimated":
            estimated.append(bands[name])
    if not estimated:
        overall = {"status": "couldnt_tell", "confidence": 0.0,
                   "reason": "too few clean decays in any band: the endings are covered by other sounds, or there are none"}
    else:
        t60 = [b["t60_s"] for b in estimated if b["t60_s"] is not None]
        overall = {"status": "estimated", "t60_s": round(float(np.median(t60)), 2) if t60 else None,
                   "range_s": [round(min(t60), 2), round(max(t60), 2)] if t60 else None,
                   "no_measurable_tail": not t60, "below_s": None if t60 else FLOOR_T60_S,
                   "confidence": round(float(np.mean([b["confidence"] for b in estimated])), 2)}
    return {"version": DECAY_VERSION, "bands": bands, "overall": overall,
            "resolution_s": FLOOR_T60_S,
            "meaning": "An upper limit on the room's decay. The room can't be slower than the fall observed, but a "
                       "source that rings by itself can make it look slower.",
            "note": "Measures the tail after sounds stop. Not pre-delay and not the wet-to-dry balance."}
