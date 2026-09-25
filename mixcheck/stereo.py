"""Stereo image and mono compatibility.

Correlation: +1 = identical channels (mono), 0 = unrelated, -1 = one channel
is the polarity-flipped copy of the other (disappears when summed to mono).
"""
import numpy as np
from scipy.signal import butter, sosfilt

from .loudness import integrated_lufs
from .util import db, rms

LOW_END_CUTOFF_HZ = 150


def correlation(left, right):
    denom = np.sqrt(np.sum(left * left) * np.sum(right * right))
    return float(np.sum(left * right) / denom) if denom > 0 else None


def windowed_correlation(left, right, fs, window_s=1.0, silence_db=-60):
    """Correlation per window; silent windows are skipped (None)."""
    win = int(fs * window_s)
    out = []
    for start in range(0, len(left) - win + 1, win):
        l, r = left[start:start + win], right[start:start + win]
        if db(max(rms(l), rms(r))) < silence_db:
            out.append((start / fs, None))
        else:
            out.append((start / fs, correlation(l, r)))
    return out


def negative_sections(windows, window_s=1.0, threshold=0.0):
    """Merge consecutive windows with correlation below threshold into ranges."""
    sections, current = [], None
    for t, c in windows:
        if c is not None and c < threshold:
            if current is None:
                current = [t, t + window_s, c]
            else:
                current[1], current[2] = t + window_s, min(current[2], c)
        elif current is not None:
            sections.append(current)
            current = None
    if current is not None:
        sections.append(current)
    return [{"start_s": s, "end_s": e, "min_correlation": round(c, 2)} for s, e, c in sections]


def measure_stereo(x, fs):
    if x.shape[1] != 2:
        return None
    left, right = x[:, 0], x[:, 1]
    mid, side = (left + right) / 2, (left - right) / 2

    sos = butter(4, LOW_END_CUTOFF_HZ, "low", fs=fs, output="sos")
    low_l, low_r = sosfilt(sos, left), sosfilt(sos, right)

    stereo_lufs = integrated_lufs(x, fs)
    mono_lufs = integrated_lufs(np.column_stack([mid, mid]), fs)
    mono_loss = (stereo_lufs - mono_lufs
                 if np.isfinite(stereo_lufs) and np.isfinite(mono_lufs) else None)

    overall = correlation(left, right)
    low_corr = correlation(low_l, low_r)
    return {
        "correlation": round(overall, 3) if overall is not None else None,
        "low_end_correlation": round(low_corr, 3) if low_corr is not None else None,
        "low_end_cutoff_hz": LOW_END_CUTOFF_HZ,
        "mono_loudness_loss_db": round(mono_loss, 2) if mono_loss is not None else None,
        "side_to_mid_db": round(float(db(rms(side)) - db(rms(mid))), 1),
        "left_right_balance_db": round(float(db(rms(left)) - db(rms(right))), 2),
        "negative_correlation_sections": negative_sections(windowed_correlation(left, right, fs)),
    }
