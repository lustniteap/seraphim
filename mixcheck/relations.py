"""Layer A, the bands together: how the bands relate, and narrow peaks that stick out.

See docs/09-analysis-model.md. Deterministic measurement only (numpy/scipy).

relations:
  tilt_db_per_oct   slope of the spectrum's density across the one-third-octave bands
                    (white noise reads 0, pink noise -3 dB per octave)
  ratios            level differences between engineer bands, in dB
  flatness          geometric over arithmetic mean of the long-term spectrum, 20 Hz-20 kHz
                    (1 = noise-like and even, 0 = a few tones)
  contrast_db       spectral contrast: in each octave, the strongest fifth of the spectrum against
                    the weakest fifth, per window; the median over the song. Low = a dense wall of
                    sound, high = clear peaks and gaps. (Plain noise reads about 14 dB.)
  band_correlation  how each pair of engineer bands' levels move together over time (-1 to +1)

resonances: narrow peaks standing above the smoothed long-term spectrum, with frequency,
prominence (dB above the surrounding spectrum), Q (frequency over the peak's -3 dB width;
RESONANCE_MAX_Q is the finest the grid can tell apart) and the time ranges where they show.
"""
import math

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import find_peaks

from .band_measures import BAND_FLOOR, GRID_PER_OCTAVE, WINDOW_S, _db, _r
from .bands import ENGINEER_IDS, FINE_BANDS

# (name, band, against band)
RATIOS = [
    ("sub_to_bass_db", "sub", "bass"),
    ("low_mids_to_mids_db", "low_mids", "mids"),
    ("presence_to_mids_db", "presence", "mids"),
    ("sibilance_to_presence_db", "sibilance", "presence"),
]

RESONANCE_MIN_DB = 6.0        # how far a peak must stand above the smoothed spectrum
RESONANCE_NEAR_OCT, RESONANCE_FAR_OCT = 0.5, 1.0  # the spectrum around a peak: this far out on each side
RESONANCE_MAX = 8             # most prominent ones kept
RESONANCE_MIN_WINDOWS = 2     # a time range must last at least this many windows
RESONANCE_MAX_Q = 60.0        # anything narrower than the grid resolves reads as this
RESONANCE_MIN_Q = 2.0         # broader than this is tonal balance, not a resonance


def measure_relations(bands, window_power, spectral):
    """The report's "relations" block from the "bands" block and the spectral pass."""
    if bands is None or spectral is None:
        return None
    level = {b["id"]: b["level_db_rel"] for b in bands["engineer"]}
    ratios = {name: _r(level[a] - level[b], 2) if level[a] is not None and level[b] is not None else None
              for name, a, b in RATIOS}

    # Tilt: straight-line fit of density (level minus 10 log bandwidth) against octaves.
    # Only bands that fit whole under 20 kHz and the sample rate, so a cut-off band doesn't bend the line.
    top = min(20000, spectral["freqs"][-1])
    pts = [(math.log2(nominal), lvl - 10 * math.log10(hi - lo))
           for (nominal, lo, hi), lvl in zip(FINE_BANDS, bands["fine"]["level_db_rel"])
           if lvl is not None and hi <= top]
    tilt = float(np.polyfit(*zip(*pts), 1)[0]) if len(pts) >= 6 else None

    freqs, long_power = spectral["freqs"], spectral["long_power"]
    inside = long_power[(freqs >= 20) & (freqs <= min(20000, freqs[-1]))]
    flatness = None
    if len(inside) and inside.mean() > BAND_FLOOR:
        flatness = float(np.exp(np.mean(np.log(np.maximum(inside, 1e-30)))) / inside.mean())

    active = spectral["active"]
    contrast = spectral["contrast_db"][active]
    contrast = contrast[np.isfinite(contrast)]

    # Band-to-band: correlation of the window levels (dB) over the non-silent windows.
    matrix = [[None] * len(ENGINEER_IDS) for _ in ENGINEER_IDS]
    heard = active & np.all((window_power > BAND_FLOOR) | (window_power.max(axis=0) <= BAND_FLOOR), axis=1)
    if heard.sum() >= 8:
        lv = _db(window_power[heard])
        ok = (window_power.max(axis=0) > BAND_FLOOR) & (lv.std(axis=0) > 1e-6)
        with np.errstate(divide="ignore", invalid="ignore"):
            cc = np.corrcoef(lv, rowvar=False)
        for i in range(len(ENGINEER_IDS)):
            for j in range(len(ENGINEER_IDS)):
                if ok[i] and ok[j]:
                    matrix[i][j] = _r(float(cc[i, j]), 2)

    return {
        "tilt_db_per_oct": _r(tilt, 2),
        "ratios": ratios,
        "flatness": _r(flatness, 3),
        "contrast_db": _r(float(np.median(contrast)), 1) if len(contrast) else None,
        "band_correlation": {"bands": list(ENGINEER_IDS), "matrix": matrix},
    }


def find_resonances(spectral):
    """Narrow peaks above the smoothed spectrum: [{hz, prominence_db, q, time_ranges_s, element}]."""
    if spectral is None or not spectral["active"].any():
        return []
    active, grid, grid_hz = spectral["active"], spectral["grid"], spectral["grid_hz"]
    near, far = int(RESONANCE_NEAR_OCT * GRID_PER_OCTAVE), int(RESONANCE_FAR_OCT * GRID_PER_OCTAVE)
    if len(grid_hz) < 2 * far:
        return []
    density = grid[active].mean(axis=0)
    if density.max() <= BAND_FLOOR:
        return []
    curve = _db(density)
    excess = curve - _around(curve, near, far)
    # A peak must also rise 3 dB clear of its own surroundings, so ripples on the side of a bigger
    # peak aren't counted as peaks of their own.
    peaks, _ = find_peaks(excess, height=RESONANCE_MIN_DB, distance=GRID_PER_OCTAVE // 8, prominence=3.0)

    freqs, long_power = spectral["freqs"], spectral["long_power"]
    found = []
    for g in sorted(peaks, key=lambda p: -excess[p])[:RESONANCE_MAX]:
        # When it shows: windows where the peak stands above that window's own smoothed spectrum.
        g = int(g)
        now = _db(grid[:, max(0, g - 1):g + 2].max(axis=1)) - _around_at(_db(grid), g, near, far)
        ranges = _ranges(active & (now >= RESONANCE_MIN_DB))
        q = _q(curve, grid_hz, g)
        if not ranges or q < RESONANCE_MIN_Q:
            continue
        # Exact frequency: the strongest bin under the peak.
        under = (freqs >= grid_hz[max(0, g - 1)]) & (freqs <= grid_hz[min(len(grid_hz) - 1, g + 1)])
        hz = float(freqs[under][np.argmax(long_power[under])]) if under.any() else float(grid_hz[g])
        found.append({
            "hz": round(hz, 1) if hz < 100 else int(round(hz)),
            "prominence_db": _r(float(excess[g]), 1),
            "q": _r(q, 1),
            "time_ranges_s": ranges,
            "element": None,  # which element it belongs to needs layer B (stems)
        })
    return sorted(found, key=lambda r: r["hz"])


def _around(curve, near, far):
    """The level around each point of a spectrum (dB): the median of the stretch from `near` to
    `far` grid points below it, averaged with the same stretch above it. Taking both sides keeps a
    tilted spectrum from reading as a peak; skipping the middle keeps a peak out of its own baseline."""
    side = median_filter(curve, size=far - near + 1, mode="nearest")
    idx, last, mid = np.arange(len(curve)), len(curve) - 1, (near + far) // 2
    return 0.5 * (side[np.clip(idx - mid, 0, last)] + side[np.clip(idx + mid, 0, last)])


def _around_at(levels, g, near, far):
    """The same, at grid point g only, for every window of `levels` (windows, grid points; dB)."""
    last = levels.shape[1] - 1
    below = levels[:, np.clip(np.arange(g - far, g - near + 1), 0, last)]
    above = levels[:, np.clip(np.arange(g + near, g + far + 1), 0, last)]
    return 0.5 * (np.median(below, axis=1) + np.median(above, axis=1))


def _q(curve, grid_hz, g):
    """Center frequency over the width 3 dB down from the top of the peak."""
    def cross(step):
        i = g
        while 0 <= i + step < len(curve) and curve[i + step] > curve[g] - 3.0:
            i += step
        j = i + step
        if not 0 <= j < len(curve):
            return math.log2(grid_hz[i])
        # Straight line between the last point above and the first point below, in octaves.
        t = (curve[i] - (curve[g] - 3.0)) / max(curve[i] - curve[j], 1e-9)
        return math.log2(grid_hz[i]) + t * (math.log2(grid_hz[j]) - math.log2(grid_hz[i]))
    width = grid_hz[g] * (2.0 ** (cross(+1) - math.log2(grid_hz[g])) - 2.0 ** (cross(-1) - math.log2(grid_hz[g])))
    return min(RESONANCE_MAX_Q, grid_hz[g] / width) if width > 0 else RESONANCE_MAX_Q


def _ranges(shows):
    """[[start_s, end_s]] of runs of windows, bridging one-window gaps and dropping very short runs."""
    shows = shows.copy()
    for i in range(1, len(shows) - 1):
        if not shows[i] and shows[i - 1] and shows[i + 1]:
            shows[i] = True
    d = np.diff(np.concatenate([[0], shows.astype(np.int8), [0]]))
    return [[round(float(a) * WINDOW_S, 1), round(float(b) * WINDOW_S, 1)]
            for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)) if b - a >= RESONANCE_MIN_WINDOWS]
