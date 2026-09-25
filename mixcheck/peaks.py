"""Peak level, true peak, clipping and DC offset."""
import numpy as np
from scipy.signal import resample_poly

from .util import db

CLIP_THRESHOLD = 0.9999   # ~ -0.001 dBFS
CLIP_MIN_RUN = 3          # consecutive samples at full scale = likely clipped


def true_peak(signal, factor=4, chunk=2 ** 18, margin=256):
    """Estimate the inter-sample peak by 4x oversampling (as in BS.1770).

    Works in chunks so a long file doesn't need gigabytes of memory; each
    chunk is padded with neighbouring audio so the edges are accurate.
    """
    n = len(signal)
    peak = 0.0
    for start in range(0, n, chunk):
        a, b = max(0, start - margin), min(n, start + chunk + margin)
        up = resample_poly(signal[a:b], factor, 1)
        lo = (start - a) * factor
        hi = lo + (min(start + chunk, n) - start) * factor
        peak = max(peak, float(np.max(np.abs(up[lo:hi]))))
    return peak


def find_clipping(signal, fs, max_events=20):
    """Find runs of consecutive samples at (or over) full scale."""
    hot = np.abs(signal) >= CLIP_THRESHOLD
    if not hot.any():
        return 0, []
    edges = np.diff(np.concatenate([[0], hot.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    runs = [(s, e - s) for s, e in zip(starts, ends) if e - s >= CLIP_MIN_RUN]
    times = [round(s / fs, 3) for s, _ in runs[:max_events]]
    return len(runs), times


def measure_peaks(x, fs):
    channels = []
    for ch in range(x.shape[1]):
        sig = x[:, ch]
        sample_pk = float(np.max(np.abs(sig)))
        tp = true_peak(sig)
        clip_count, clip_times = find_clipping(sig, fs)
        channels.append({
            "sample_peak_dbfs": round(float(db(sample_pk)), 2),
            "true_peak_dbtp": round(float(db(tp)), 2),
            "clip_events": clip_count,
            "clip_times_s": clip_times,
            "dc_offset_dbfs": round(float(db(abs(np.mean(sig)))), 1),
        })
    return {
        "true_peak_max_dbtp": max(c["true_peak_dbtp"] for c in channels),
        "sample_peak_max_dbfs": max(c["sample_peak_dbfs"] for c in channels),
        "clip_events_total": sum(c["clip_events"] for c in channels),
        "channels": channels,
    }
