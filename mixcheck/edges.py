"""Start/end of the file, quiet passages."""
import numpy as np

from .util import db, rms

SILENCE_DB = -60      # below this counts as silence for head/tail
DIGITAL_SILENCE_DB = -90


def measure_edges(x, fs):
    env = np.max(np.abs(x), axis=1)
    audible = np.flatnonzero(env > 10 ** (SILENCE_DB / 20))
    if len(audible) == 0:
        return {"silent_file": True}

    first, last = audible[0], audible[-1]
    tail_len = int(0.05 * fs)
    end_rms = rms(x[max(first, last + 1 - tail_len):last + 1])

    # Quietest passage: 50 ms windows, ignoring pure digital silence.
    win = int(0.05 * fs)
    n_win = len(x) // win
    levels = db(np.sqrt(np.mean(np.square(x[:n_win * win]).reshape(n_win, win, -1), axis=(1, 2))))
    levels = levels[levels > DIGITAL_SILENCE_DB]
    quietest = float(np.percentile(levels, 5)) if len(levels) else None

    return {
        "silent_file": False,
        "head_silence_s": round(first / fs, 3),
        "tail_silence_s": round((len(x) - 1 - last) / fs, 3),
        "final_50ms_rms_dbfs": round(float(db(end_rms)), 1),
        "quietest_passage_rms_dbfs": round(quietest, 1) if quietest is not None else None,
    }
