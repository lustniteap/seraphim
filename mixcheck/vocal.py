"""Vocal checks: is the vocal compressed, EQ'd and sitting well against the beat?

Works on a vocal and an instrumental, either split from the mix (separate.py) or, later,
uploaded as stems. It measures the vocal on its own, which the full mix can't show: the beat
covers the vocal's mud, its dynamics and its harsh 's' sounds.

Tone levels are spectral density (dB per Hz), relative to the vocal's own 500 Hz–4 kHz range,
so they don't depend on how loud the vocal is. Dynamics use only the frames where the vocal is
actually singing.

LIMITS are starting points, not measured from real releases yet. The tone limits sit a few dB
beyond where an unprocessed voice naturally falls (from long-term average speech spectra:
about +14.5 dB at 200–500 Hz and +15.5 dB at 100–250 Hz against the mids), so a plain, healthy
voice isn't flagged. Anything split from a mix also carries the splitter's own coloration. The
numbers are always in the report so they can be tuned against real bounces.
"""
import numpy as np
from scipy.signal import spectrogram

WINDOW_S, HOP_S = 0.4, 0.2   # word-sized windows for level
ABS_GATE_DB = -60.0          # quieter than this is silence
REL_GATE_DB = 20.0           # and so is anything this far under the vocal's own average (as in EBU R128)
MIN_ACTIVE_S = 5.0           # less vocal than this isn't enough to judge

# id of a measurement -> (where it becomes "info", where it becomes "warning"). Higher is worse
# except where noted.
LIMITS = {
    "crest_db": (14.5, 17.0),       # peaks above the average level: raw vocals run high
    "range_db": (6.0, 9.0),         # how far the loud words stand above the typical word
    "mud_db": (17.0, 20.0),         # 200–500 Hz against the mids
    "body_db": (11.0, 7.0),         # 100–250 Hz against the mids; LOWER is worse
    "rumble_db": (-25.0, -18.0),    # below 80 Hz against the mids: no high-pass
    "sibilance_db": (2.0, 6.0),     # 5–9 kHz peaks against the mids
    "beat_gap_db": (-2.0, -5.0),    # vocal level minus beat level; LOWER is worse (vocal buried)
    "beat_over_db": (10.0, 13.0),   # the same number; HIGHER is worse (vocal on top of the beat)
}
LOWER_IS_WORSE = {"body_db", "beat_gap_db"}

VOCAL_IDS = {
    "vocal_uncompressed", "vocal_muddy", "vocal_thin", "vocal_rumble",
    "vocal_sibilant", "vocal_buried", "vocal_dominant",
}

ESTIMATE_NOTE = (
    "The vocal was split from the mix by a model, so these numbers are estimates: the split leaves some of "
    "the beat in the vocal and takes some of its low end and reverb. Results are more accurate when you "
    "upload the acapella and the beat separately."
)


def _db(power):
    return 10.0 * np.log10(np.maximum(power, 1e-12))


def _window_power(mono, fs):
    """Mean-square power of each window, and where each starts."""
    win, hop = int(WINDOW_S * fs), int(HOP_S * fs)
    if len(mono) < win:
        return np.array([]), np.array([], dtype=int)
    cs = np.concatenate([[0.0], np.cumsum(mono * mono)])
    starts = np.arange(0, len(mono) - win + 1, hop)
    return (cs[starts + win] - cs[starts]) / win, starts


def _gate(p_db):
    """(threshold in dB, mask of windows above it); (None, all False) if everything is silent."""
    above = p_db > ABS_GATE_DB
    if not above.any():
        return None, above
    average = _db(np.mean(10 ** (p_db[above] / 10)))
    threshold = max(ABS_GATE_DB, average - REL_GATE_DB)
    return threshold, p_db > threshold


def _mono(x):
    x = np.asarray(x, dtype=np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def measure_vocal(vocal, instrumental, fs):
    """Measurements of the vocal, or {"found": False, "reason": ...} when there isn't enough of it."""
    v, i = _mono(vocal), _mono(instrumental)
    p, _ = _window_power(v, fs)
    if p.size == 0:
        return {"found": False, "reason": "The file is too short to find a vocal in."}
    p_db = _db(p)
    threshold, active = _gate(p_db)
    active_s = float(active.sum()) * HOP_S
    if threshold is None or active_s < MIN_ACTIVE_S:
        return {"found": False, "reason": "Not enough vocal was found to judge it. Is this an instrumental?"}

    level = float(_db(np.mean(p[active])))
    peak = float(20 * np.log10(max(np.max(np.abs(v)), 1e-9)))
    out = {
        "found": True,
        "active_s": round(active_s, 1),
        "level_dbfs": round(level, 1),
        "peak_dbfs": round(peak, 1),
        "crest_db": round(peak - level, 1),
        # Loud words against the typical word. Not the quiet end: windows that straddle a pause read low.
        "range_db": round(float(np.percentile(p_db[active], 95) - np.percentile(p_db[active], 50)), 1),
    }

    nper = 4096
    f, _, s = spectrogram(v, fs, window="hann", nperseg=nper, noverlap=nper // 2, scaling="density", mode="psd")
    frames = _db(s.sum(axis=0) * (f[1] - f[0])) > threshold
    if frames.sum() >= 5:
        top = fs / 2 - 1

        def band(lo, hi):  # mean density per active frame
            return s[(f >= lo) & (f < min(hi, top))][:, frames].mean(axis=0)

        core = band(500, 4000)
        core_db = float(_db(core.mean()))
        out.update(
            rumble_db=round(float(_db(band(20, 80).mean())) - core_db, 1),
            body_db=round(float(_db(band(100, 250).mean())) - core_db, 1),
            mud_db=round(float(_db(band(200, 500).mean())) - core_db, 1),
            sibilance_db=round(float(np.percentile(_db(band(5000, 9000)) - _db(core), 95)), 1),
        )

    beat = float(_db(np.mean(_window_power(i, fs)[0][active])))
    out["vocal_to_beat_db"] = round(level - beat, 1) if beat > -90 else None
    return out


def _rate(name, value):
    """"warning", "info" or None for one measurement."""
    if value is None:
        return None
    info, warn = LIMITS[name]
    if name in LOWER_IS_WORSE:
        return "warning" if value <= warn else "info" if value <= info else None
    return "warning" if value >= warn else "info" if value >= info else None


def vocal_flags(v):
    """Findings from measure_vocal(); none if no vocal was found."""
    if not v or not v.get("found"):
        return []
    flags = []

    def flag(fid, severity, message, **data):
        if severity:
            flags.append({"id": fid, "severity": severity, "message": message, "estimated": True, **data})

    crest, spread = v["crest_db"], v["range_db"]
    ranks = {"warning": 2, "info": 1, None: 0}
    worst = max((_rate("crest_db", crest), _rate("range_db", spread)), key=ranks.get)
    flag("vocal_uncompressed", worst,
         f"The vocal looks uncompressed: its loud words sit {spread:.1f} dB above the typical word and its peaks sit "
         f"{crest:.1f} dB above its average.", value=spread, crest_db=crest)
    if "mud_db" in v:
        flag("vocal_muddy", _rate("mud_db", v["mud_db"]),
             f"The vocal is heavy at 200–500 Hz ({v['mud_db']:+.1f} dB against its mids), which reads as muddy.",
             value=v["mud_db"])
        flag("vocal_thin", _rate("body_db", v["body_db"]),
             f"The vocal has little body at 100–250 Hz ({v['body_db']:+.1f} dB against its mids); it may sound thin.",
             value=v["body_db"])
        flag("vocal_rumble", _rate("rumble_db", v["rumble_db"]),
             f"There is low rumble in the vocal below 80 Hz ({v['rumble_db']:+.1f} dB against its mids); "
             "it looks like there is no high-pass.", value=v["rumble_db"])
        flag("vocal_sibilant", _rate("sibilance_db", v["sibilance_db"]),
             f"The vocal's 's' sounds are strong: 5–9 kHz peaks sit {v['sibilance_db']:+.1f} dB over its mids.",
             value=v["sibilance_db"])
    gap = v.get("vocal_to_beat_db")
    if gap is not None:
        flag("vocal_buried", _rate("beat_gap_db", gap),
             f"The vocal sits {abs(gap):.1f} dB below the beat while it is singing, so it may be buried.", value=gap)
        flag("vocal_dominant", _rate("beat_over_db", gap),
             f"The vocal sits {gap:.1f} dB above the beat while it is singing, so the beat may feel pushed back.", value=gap)
    return flags
