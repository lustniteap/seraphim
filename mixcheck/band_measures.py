"""Layer A, band by band: what each frequency band is doing, over the song and over time.

See docs/09-analysis-model.md. Everything here is deterministic measurement (numpy/scipy only).

How it works. The whole file is transformed once. Each engineer band is then cut out of that
spectrum (a brick-wall cut, so the bands add up to the full signal exactly), shifted down to 0 Hz
and transformed back at a sample rate just high enough for its width. The result is the band's
"analytic" signal per channel: its magnitude is the band's envelope, and products of the left and
right signals give correlation, mid and side. That makes ten bands cost about as much as one.

Per band, as a whole-song summary and per WINDOW_S window (the timeline, stored as columns:
one list per measure, one entry per window):

  level_db_rel     band level relative to the song's loudness (the same convention as the tone
                   bands in reference.py: band power in dB minus the K-weighted power of the song)
  crest_db         peak of the band's envelope over its RMS (a sine reads 3.0 dB)
  correlation      L/R correlation inside the band (+1 mono, -1 out of phase)
  side_mid_db      side level relative to mid inside the band
  balance_db       left minus right level inside the band
  transient_ratio  share of the band's energy in short bursts: energy standing more than
                   TRANSIENT_OVER_DB above the band's own running median level (0 steady, 1 all hits)

and summary only:

  lra_lu           range of the band's 3 s level over the song (10th to 95th percentile, gated like
                   EBU loudness range; the band isn't K-weighted, so read LU as dB)
  level_std_db     how much the window levels move over the song (standard deviation, dB)
"""
import math

import numpy as np
from scipy import fft as sfft
from scipy.ndimage import median_filter

from .bands import ENGINEER_BANDS, FINE_BANDS

WINDOW_S = 0.4            # timeline step
TOP_HZ = 20000
SILENT_WINDOW_DB = -70.0  # windows quieter than this (mean square, all channels) are skipped
BAND_FLOOR = 1e-16        # band power below this is "nothing there" (-160 dB)
MIN_RATE_HZ = 800         # lowest sample rate a band is brought down to (keeps 5 ms frames meaningful)
FRAME_S = 0.005           # envelope frames for the transient measure
MEDIAN_S = 0.2            # running-median length for the "sustained" level
TRANSIENT_OVER_DB = 6.0
LRA_SMOOTH_S = 3.0
LRA_REL_GATE_DB = -20.0


def _db(power):
    return 10.0 * np.log10(np.maximum(power, 1e-30))


def _r(value, places):
    """Rounded float, or None for missing/non-finite."""
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), places)


def _edges(count, step, total):
    """Start index of each of `count` consecutive blocks `step` (fractional) samples long, capped at total."""
    return np.minimum(np.round(np.arange(count) * step).astype(np.int64), max(total - 1, 0))


def window_count(n, fs):
    return int(n // int(round(WINDOW_S * fs)))


def active_windows(x, fs):
    """Which timeline windows hold audio (not silence)."""
    hop, count = int(round(WINDOW_S * fs)), window_count(len(x), fs)
    power = (x[:count * hop] ** 2).reshape(count, hop, x.shape[1]).mean(axis=1).sum(axis=1)
    return _db(power) > SILENT_WINDOW_DB


def measure_bands(x, fs, integrated_lufs):
    """The report's "bands" block, or None when there's no audio to measure.

    Returns (block, levels): levels is (windows, 10) band power per window, for relations.py.
    """
    n, channels = x.shape
    count = window_count(n, fs)
    if count < 1 or integrated_lufs is None or not math.isfinite(integrated_lufs):
        return None, None
    ref_db = integrated_lufs + 0.691  # the song's K-weighted power, in dB
    active = active_windows(x, fs)
    nfast = sfft.next_fast_len(n, real=True)
    spectra = [sfft.rfft(x[:, ch], nfast) for ch in range(channels)]
    df = fs / nfast
    top = min(TOP_HZ, fs / 2)
    frames_per_window = int(round(WINDOW_S / FRAME_S))
    med_len = int(round(MEDIAN_S / FRAME_S)) | 1
    over = 10 ** (TRANSIENT_OVER_DB / 10)

    engineer, window_power = [], np.zeros((count, len(ENGINEER_BANDS)))
    for b, (bid, lo, hi, _name) in enumerate(ENGINEER_BANDS):
        entry = {"id": bid, "lo_hz": lo, "hi_hz": hi, "level_db_rel": None, "target_delta_db": None,
                 "crest_db": None, "lra_lu": None, "correlation": None, "side_mid_db": None,
                 "balance_db": None, "transient_ratio": None, "level_std_db": None, "timeline": None}
        engineer.append(entry)
        k0, k1 = int(math.ceil(lo / df)), min(int(math.ceil(min(hi, top) / df)), len(spectra[0]))
        if k1 - k0 < 2:  # the sample rate is too low to hold this band
            continue
        # Bring the band down to 0 Hz at m samples for the whole file: rate = m / (nfast / fs).
        m = sfft.next_fast_len(max(2 * (k1 - k0), int(math.ceil(MIN_RATE_HZ * nfast / fs))))
        analytic = []
        for spec in spectra:
            shifted = np.zeros(m, complex)
            shifted[:k1 - k0] = spec[k0:k1]
            analytic.append(sfft.ifft(shifted) * (2.0 * m / nfast))
        per_s = m * fs / nfast                       # samples per second in this band
        used = int(min(m, round(count * WINDOW_S * per_s)))
        w_edges = _edges(count, WINDOW_S * per_s, used)
        w_len = np.diff(np.append(w_edges, used))

        # Mean-square power of the real band signal is half the analytic signal's.
        sq = [np.abs(a[:used]) ** 2 for a in analytic]
        ch_power = [np.add.reduceat(s, w_edges) / w_len / 2 for s in sq]      # per window, per channel
        power = np.sum(ch_power, axis=0)                                      # summed across channels
        window_power[:, b] = power
        peak = np.max([np.maximum.reduceat(s, w_edges) for s in sq], axis=0)  # envelope peak^2
        heard = active & (power > BAND_FLOOR)
        with np.errstate(divide="ignore", invalid="ignore"):
            crest = _db(peak / (power / channels))

        # Transients: 5 ms envelope frames against their own running median.
        total = np.sum(sq, axis=0)
        f_edges = _edges(count * frames_per_window, FRAME_S * per_s, used)
        frames = np.add.reduceat(total, f_edges) / np.diff(np.append(f_edges, used))
        burst = np.maximum(frames - over * median_filter(frames, size=med_len, mode="nearest"), 0.0)
        burst_w = burst.reshape(count, frames_per_window).sum(axis=1)
        frames_w = frames.reshape(count, frames_per_window).sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            transient = np.where(frames_w > 0, burst_w / frames_w, 0.0)

        corr = side_mid = balance = None
        song_corr = song_side_mid = song_balance = None
        if channels == 2:
            left, right = analytic[0][:used], analytic[1][:used]
            cross = np.add.reduceat((left * np.conj(right)).real, w_edges) / w_len / 2
            pl, pr = ch_power
            with np.errstate(divide="ignore", invalid="ignore"):
                corr = cross / np.sqrt(pl * pr)
                mid, side = pl + pr + 2 * cross, pl + pr - 2 * cross
                side_mid = _db(np.maximum(side, 0)) - _db(mid)
                balance = _db(pl) - _db(pr)
            # Whole-song values, weighted by energy like the overall stereo numbers.
            sl, sr, sc = (pl * w_len)[heard].sum(), (pr * w_len)[heard].sum(), (cross * w_len)[heard].sum()
            if sl > 0 and sr > 0:
                song_corr = sc / math.sqrt(sl * sr)
                song_side_mid = float(_db(max(sl + sr - 2 * sc, 0.0)) - _db(sl + sr + 2 * sc))
                song_balance = float(_db(sl) - _db(sr))

        level = _db(power) - ref_db
        # The timeline is stored as columns (one list per measure, one entry per window): the same
        # numbers as a list of points at about a quarter of the size. Silent windows read null.
        def column(values, places, lo=None, hi=None):
            if lo is not None:
                values = np.clip(values, lo, hi)
            return [_r(float(v), places) if ok else None for v, ok in zip(values, heard)]

        entry["timeline"] = {"t_s": [round(i * WINDOW_S, 1) for i in range(count)],
                             "level_db_rel": column(level, 1), "crest_db": column(crest, 1),
                             "transient_ratio": column(transient, 2)}
        if channels == 2:
            entry["timeline"].update(correlation=column(corr, 2), side_mid_db=column(side_mid, 1, -99.0, 99.0),
                                     balance_db=column(balance, 1, -99.0, 99.0))

        # Whole-song level: exact, from the spectrum (every sample, not just whole windows).
        song_power = sum(2.0 * np.sum(np.abs(spec[k0:k1]) ** 2) for spec in spectra) / (nfast * n)
        if song_power > BAND_FLOOR and heard.any():
            entry.update(
                level_db_rel=_r(float(_db(song_power)) - ref_db, 2),
                crest_db=_r(float(np.median(crest[heard])), 1),
                lra_lu=_r(_level_range(power, active), 1),
                level_std_db=_r(float(np.std(_db(power[heard]))), 2),
                transient_ratio=_r(float(burst_w[heard].sum() / frames_w[heard].sum()), 3),
                correlation=_r(song_corr, 3),
                side_mid_db=_r(None if song_side_mid is None else max(song_side_mid, -99.0), 1),
                balance_db=_r(None if song_balance is None else float(np.clip(song_balance, -99.0, 99.0)), 2),
            )

    fine_power = [sum(2.0 * np.sum(np.abs(spec[int(math.ceil(lo / df)):int(math.ceil(min(hi, top) / df))]) ** 2)
                      for spec in spectra) / (nfast * n) if lo < top else 0.0
                  for _nominal, lo, hi in FINE_BANDS]
    block = {
        "window_s": WINDOW_S,
        "level_reference": "band power in dB relative to the song's K-weighted loudness (integrated LUFS + 0.691)",
        "engineer": engineer,
        "fine": {
            "center_hz": [nominal for nominal, _lo, _hi in FINE_BANDS],
            "level_db_rel": [_r(float(_db(p)) - ref_db, 2) if p > BAND_FLOOR else None for p in fine_power],
            "timeline": None,  # filled in by analyze.py from the spectral pass
        },
    }
    return block, window_power


def _level_range(power, active):
    """10th-95th percentile range of the band's ~3 s level, gated like EBU loudness range."""
    span = max(1, int(round(LRA_SMOOTH_S / WINDOW_S)))
    if len(power) < span:
        return None
    smooth = np.convolve(power, np.ones(span) / span, mode="valid")
    keep = np.convolve(active.astype(float), np.ones(span) / span, mode="valid") > 0.5
    smooth = smooth[keep & (smooth > BAND_FLOOR)]
    if len(smooth) < 2:
        return None
    smooth = smooth[_db(smooth) > _db(smooth.mean()) + LRA_REL_GATE_DB]
    if len(smooth) < 2:
        return None
    lo, hi = np.percentile(_db(smooth), [10, 95])
    return float(hi - lo)


# ---------------------------------------------------------------- one pass over short spectra

# Resonance grid: 48 points per octave.
GRID_PER_OCTAVE = 48
GRID_LO_HZ, GRID_HI_HZ = 30.0, 18000.0
CONTRAST_SHARE = 0.2  # spectral contrast compares the top and bottom fifth of each octave


def spectral_pass(x, fs):
    """Short-time spectra, one per timeline window (a Hann window twice the step, centered on it).

    Returns a dict:
      freqs        bin frequencies
      long_power   mean power per bin over the non-silent windows (channels summed)
      fine         (windows, 31) power per one-third-octave band
      grid_hz      center frequencies of the resonance grid
      grid         (windows, len(grid_hz)) power density on that grid
      contrast_db  (windows,) spectral contrast per window
      active       (windows,) False for silent windows
    or None when the file is shorter than one window.
    """
    n, channels = x.shape
    hop, count = int(round(WINDOW_S * fs)), window_count(n, fs)
    if count < 1:
        return None
    nfft = 2 * hop
    win = np.hanning(nfft)
    norm = nfft * np.sum(win ** 2)
    freqs = np.fft.rfftfreq(nfft, 1 / fs)
    df = fs / nfft
    top = min(TOP_HZ, fs / 2)
    active = active_windows(x, fs)
    padded = np.concatenate([np.zeros((hop // 2, channels)), x[:count * hop], np.zeros((nfft, channels))])

    fine_bins = [(int(math.ceil(lo / df)), int(math.ceil(min(hi, top) / df))) for _n, lo, hi in FINE_BANDS]
    grid_hz = GRID_LO_HZ * 2.0 ** (np.arange(int(math.log2(min(GRID_HI_HZ, 0.45 * fs) / GRID_LO_HZ)
                                                 * GRID_PER_OCTAVE) + 1) / GRID_PER_OCTAVE)
    half = np.maximum(grid_hz * (2.0 ** (0.5 / GRID_PER_OCTAVE) - 1), 1.5 * df)  # at least 3 bins wide
    # Cell power = cumulative power interpolated at the cell's edges (bin k covers (k-0.5, k+0.5) * df).
    pos = np.stack([(grid_hz - half) / df + 0.5, (grid_hz + half) / df + 0.5])
    pos = np.clip(pos, 0, len(freqs) - 1e-9)
    idx, frac = pos.astype(int), pos - pos.astype(int)
    octaves = [(int(math.ceil(lo / df)), int(math.ceil(min(2 * lo, top) / df)))
               for lo in 62.5 * 2.0 ** np.arange(9) if lo < top]  # 62.5 Hz ... 16 kHz
    octaves = [(a, b) for a, b in octaves if b - a >= 10]

    long_power = np.zeros(len(freqs))
    fine = np.zeros((count, len(FINE_BANDS)))
    grid = np.zeros((count, len(grid_hz)))
    contrast = np.full(count, np.nan)
    for start in range(0, count, 64):  # in chunks, so long files stay light on memory
        rows = np.arange(start, min(count, start + 64))
        at = rows[:, None] * hop + np.arange(nfft)
        power = np.zeros((len(rows), len(freqs)))
        for ch in range(channels):
            power += 2.0 * np.abs(sfft.rfft(padded[at, ch] * win, axis=1)) ** 2 / norm
        long_power += power[active[rows]].sum(axis=0)
        cum = np.concatenate([np.zeros((len(rows), 1)), np.cumsum(power, axis=1)], axis=1)
        for j, (a, b) in enumerate(fine_bins):
            if b > a:
                fine[rows, j] = cum[:, b] - cum[:, a]
        edge = cum[:, idx] * (1 - frac) + cum[:, np.minimum(idx + 1, cum.shape[1] - 1)] * frac
        grid[rows] = (edge[:, 1] - edge[:, 0]) / (2 * half)
        parts = []
        for a, b in octaves:
            k = max(1, int((b - a) * CONTRAST_SHARE))
            band = np.partition(power[:, a:b], (k, b - a - k), axis=1)
            parts.append(_db(band[:, b - a - k:].mean(axis=1)) - _db(band[:, :k].mean(axis=1)))
        if parts:
            contrast[rows] = np.mean(parts, axis=0)
    if active.any():
        long_power /= active.sum()
    return {"freqs": freqs, "long_power": long_power, "fine": fine, "grid_hz": grid_hz, "grid": grid,
            "contrast_db": contrast, "active": active}


def fine_timeline(spectral, integrated_lufs):
    """The fine bands over time as one table: times, then one row of 31 levels per window."""
    ref_db = integrated_lufs + 0.691
    levels = _db(spectral["fine"]) - ref_db
    heard = spectral["active"][:, None] & (spectral["fine"] > BAND_FLOOR)
    return {
        "t_s": [round(i * WINDOW_S, 1) for i in range(len(levels))],
        "level_db_rel": [[round(float(v), 1) if ok else None for v, ok in zip(row, keep)]
                         for row, keep in zip(levels, heard)],
    }
