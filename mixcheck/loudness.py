"""Loudness per ITU-R BS.1770-4 and EBU R128 / Tech 3342.

The pipeline:
  1. K-weighting: a high shelf (+4 dB above ~1.7 kHz, roughly how the head
     affects what we hear) and a high-pass at ~38 Hz (we're insensitive to
     deep lows). Filter coefficients are computed for any sample rate using
     the same method as libebur128.
  2. Chop the signal into overlapping blocks and take mean-square power.
  3. Gate out silence (absolute gate, -70 LUFS) and quiet passages (relative
     gate) so a long fade doesn't drag the number down.
"""
import numpy as np
from scipy.signal import lfilter

ABS_GATE = -70.0


def k_weighting_coeffs(fs):
    """Return ((b1, a1), (b2, a2)) for the two K-weighting stages."""
    # Stage 1: high shelf
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / fs)
    vh = 10.0 ** (gain / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    b1 = np.array([(vh + vb * k / q + k * k), 2.0 * (k * k - vh), (vh - vb * k / q + k * k)]) / a0
    a1 = np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0])

    # Stage 2: high-pass
    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / fs)
    a0 = 1.0 + k / q + k * k
    b2 = np.array([1.0, -2.0, 1.0])
    a2 = np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0])
    return (b1, a1), (b2, a2)


def k_weight(x, fs):
    (b1, a1), (b2, a2) = k_weighting_coeffs(fs)
    return lfilter(b2, a2, lfilter(b1, a1, x, axis=0), axis=0)


def block_mean_squares(y, fs, window_s, hop_s):
    """Mean-square power per channel for each block. Returns (powers, start_times)."""
    win, hop = int(round(window_s * fs)), int(round(hop_s * fs))
    n = y.shape[0]
    if n < win:
        return np.empty((0, y.shape[1])), np.empty(0)
    csum = np.vstack([np.zeros((1, y.shape[1])), np.cumsum(y * y, axis=0)])
    starts = np.arange(0, n - win + 1, hop)
    return (csum[starts + win] - csum[starts]) / win, starts / fs


def to_lufs(power):
    return -0.691 + 10.0 * np.log10(np.maximum(power, 1e-20))


def _channel_weights(n_channels):
    # BS.1770 weights: 1.0 for L/R/C. (Surround would use 1.41 for Ls/Rs.)
    return np.ones(n_channels)


def gated_integrated(block_powers, weights):
    p = block_powers @ weights
    lufs = to_lufs(p)
    above_abs = lufs > ABS_GATE
    if not above_abs.any():
        return float("-inf")
    rel_gate = to_lufs(p[above_abs].mean()) - 10.0
    keep = above_abs & (lufs > rel_gate)
    return float(to_lufs(p[keep].mean()))


def integrated_lufs(x, fs):
    """Integrated loudness of a (samples, channels) array."""
    y = k_weight(x, fs)
    powers, _ = block_mean_squares(y, fs, 0.4, 0.1)
    if len(powers) == 0:
        return float("-inf")
    return gated_integrated(powers, _channel_weights(x.shape[1]))


def loudness_range(st_powers, weights):
    """LRA per EBU Tech 3342: spread between 10th and 95th percentile of
    gated short-term loudness."""
    p = st_powers @ weights
    lufs = to_lufs(p)
    above_abs = lufs > ABS_GATE
    if above_abs.sum() < 2:
        return None
    rel_gate = to_lufs(p[above_abs].mean()) - 20.0
    vals = lufs[above_abs & (lufs > rel_gate)]
    if len(vals) < 2:
        return None
    lo, hi = np.percentile(vals, [10, 95])
    return float(hi - lo)


def measure_loudness(x, fs):
    weights = _channel_weights(x.shape[1])
    y = k_weight(x, fs)

    mom, _ = block_mean_squares(y, fs, 0.4, 0.1)     # momentary: 400 ms
    st, _ = block_mean_squares(y, fs, 3.0, 0.1)      # short-term: 3 s
    timeline_p, timeline_t = block_mean_squares(y, fs, 3.0, 1.0)

    integrated = gated_integrated(mom, weights) if len(mom) else float("-inf")
    lra = loudness_range(st, weights) if len(st) else None
    return {
        "integrated_lufs": round(integrated, 2),
        "max_momentary_lufs": round(float(to_lufs(mom @ weights).max()), 2) if len(mom) else None,
        "max_short_term_lufs": round(float(to_lufs(st @ weights).max()), 2) if len(st) else None,
        "loudness_range_lu": round(lra, 2) if lra is not None else None,
        # Short-term loudness once per second, centered on each 3 s window.
        "timeline": [
            {"t": round(float(t) + 1.5, 1), "lufs": round(float(v), 1)}
            for t, v in zip(timeline_t, to_lufs(timeline_p @ weights))
        ],
    }
