"""Reference tracks: compare a bounce with 1–3 songs the user wants to sound like.

Each file is boiled down to a small profile, measured on its loudest sections
(the chorus or drop, where people actually compare songs) and at matched volume:

  loudness   how loud the loud sections are (LUFS)
  punch      how far the true peaks stand above them (dB, like PLR)
  contrast   loudness range over the whole song (LU)
  tone       level in five bands relative to the file's own loudness (dB), so a
             quieter file doesn't read as "lighter" just for being quieter
  width      side relative to mid in the loud sections (dB)

Only loudness depends on level; everything else is the same at any volume.
Profiles hold numbers, never audio, so a reference set can be saved and reused
without keeping the songs. Fixes then read relative to the references:
"3.0 dB lighter below 100 Hz than your reference".
"""
import math

import numpy as np

from .audio_io import load_audio
from .loudness import ABS_GATE, block_mean_squares, k_weight, loudness_range, to_lufs
from .peaks import true_peak
from .style import MIX_PLR_SHIFT

PROFILE_VERSION = 1
MAX_REFERENCES = 3

# Loud sections: where short-term (3 s) loudness is within 3 LU of the song's
# near-loudest level (its 95th percentile, so one spike doesn't set the bar).
LOUD_PERCENTILE = 95
LOUD_WITHIN_LU = 3.0
ST_WINDOW_S, ST_HOP_S = 3.0, 0.1  # the hop EBU Tech 3342 uses for loudness range, so one pass serves both

# id, low Hz, high Hz, short name, how fixes name it, how findings phrase it,
# words for (more, less), EQ shape to fix it with.
TONE_BANDS = [
    ("lows", 20, 100, "Lows", "the lows (below 100 Hz)", "below 100 Hz", ("heavier", "lighter"), "low shelf"),
    ("low_mids", 100, 300, "Low mids", "the low mids (100–300 Hz)", "at 100–300 Hz", ("heavier", "lighter"), "wide bell"),
    ("mids", 300, 2000, "Mids", "the mids (300 Hz–2 kHz)", "at 300 Hz–2 kHz", ("fuller", "thinner"), "wide bell"),
    ("presence", 2000, 6000, "Presence", "the presence range (2–6 kHz)", "at 2–6 kHz", ("more forward", "further back"), "wide bell"),
    ("highs", 6000, 20000, "Highs", "the highs (above 6 kHz)", "above 6 kHz", ("brighter", "duller"), "high shelf"),
]
BAND_IDS = [b[0] for b in TONE_BANDS]

# id -> (name, unit, profile key, how far from the references still counts as a match)
DIMS = {
    "loudness": ("Loudness", "LUFS", "loudness_lufs", 1.0),
    "punch": ("Punch", "dB", "punch_db", 1.5),
    "contrast": ("Contrast", "LU", "contrast_lu", 2.0),
    "tone": ("Tone", "dB", "tone_db", 1.5),
    "width": ("Width", "dB", "width_db", 2.0),
}
# A dimension scores 0% once it's this many tolerances outside the references.
MISS_SCALE = 3.0

REFERENCE_IDS = {
    "ref_louder", "ref_quieter", "ref_more_limited", "ref_more_dynamic",
    "ref_less_contrast", "ref_more_contrast", "ref_narrower", "ref_wider",
    "ref_tone_more", "ref_tone_less",
}


# ---------------------------------------------------------------- measuring

def loud_mask(y, fs, powers=None, starts=None):
    """Samples inside the loud sections of K-weighted audio y; None if the file is silent.
    powers/starts: short-term blocks already measured from y, if any."""
    n = len(y)
    if powers is None:
        powers, starts = block_mean_squares(y, fs, ST_WINDOW_S, ST_HOP_S)
    if not len(powers):  # shorter than one window: use all of it
        return np.ones(n, bool) if to_lufs((y * y).mean(axis=0).sum()) > ABS_GATE else None
    st = to_lufs(powers.sum(axis=1))
    gated = st[st > ABS_GATE]
    if not len(gated):
        return None
    threshold = np.percentile(gated, LOUD_PERCENTILE) - LOUD_WITHIN_LU
    # Each loud window marks only its middle hop, so the edges of a chorus don't pull in the verse.
    win, hop = int(round(ST_WINDOW_S * fs)), int(round(ST_HOP_S * fs))
    begin = np.round(starts[st >= threshold] * fs).astype(int) + (win - hop) // 2
    edges = np.zeros(n + 1, int)
    np.add.at(edges, begin, 1)
    np.add.at(edges, np.minimum(n, begin + hop), -1)
    return np.cumsum(edges)[:n] > 0


def _runs(mask):
    """[(start, end)] of consecutive True samples."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def _tone(x, fs, mask):
    """Mean-square power per band over the loud sections, summed across channels."""
    nfft = 2 ** int(round(math.log2(fs * 0.085)))  # ~85 ms: 4096 at 44.1/48 kHz
    win = np.hanning(nfft)
    norm = nfft * np.sum(win ** 2)
    freqs = np.fft.rfftfreq(nfft, 1 / fs)
    top = min(20000, fs / 2)
    bins = [(freqs >= lo) & (freqs < min(hi, top)) for _, lo, hi, *_ in TONE_BANDS]

    starts = np.arange(0, len(x) - nfft + 1, nfft // 2)
    starts = starts[mask[starts + nfft // 2]]  # frames centered in a loud section
    totals, count = np.zeros(len(TONE_BANDS)), 0
    for i in range(0, len(starts), 128):  # in chunks, so long files stay light on memory
        idx = starts[i:i + 128, None] + np.arange(nfft)
        for ch in range(x.shape[1]):
            spec = np.abs(np.fft.rfft(x[idx, ch] * win, axis=1)) ** 2
            totals += [2 * spec[:, b].sum() for b in bins]
        count += len(idx)
    return totals / (norm * count) if count else None


def measure_profile(x, fs, name=""):
    """The numbers a reference comparison needs, from a (samples, channels) array."""
    if x.shape[1] > 2:
        raise ValueError(f"{x.shape[1]}-channel files aren't supported yet (mono or stereo only).")
    y = k_weight(x, fs)
    st, starts = block_mean_squares(y, fs, ST_WINDOW_S, ST_HOP_S)
    mask = loud_mask(y, fs, st, starts)
    if mask is None:
        raise ValueError(f"{name or 'The file'} is silent.")
    # Work on slices of each loud run: boolean indexing would copy the whole song.
    runs = _runs(mask)

    loud = float(to_lufs(sum(np.sum(y[a:b] ** 2) for a, b in runs) / mask.sum()))
    peak = max(true_peak(x[a:b, ch]) for a, b in runs for ch in range(x.shape[1]))
    lra = loudness_range(st, np.ones(x.shape[1])) if len(st) else None

    width = None
    if x.shape[1] == 2:
        mid = sum(np.sum((x[a:b, 0] + x[a:b, 1]) ** 2) for a, b in runs)
        side = sum(np.sum((x[a:b, 0] - x[a:b, 1]) ** 2) for a, b in runs)
        width = 10 * math.log10(max(side, 1e-20) / mid) if mid > 0 else None

    bands = _tone(x, fs, mask)
    tone = None
    if bands is not None:
        # Relative to the loud sections' own loudness: this is what "matched volume" means.
        tone = {bid: round(10 * math.log10(max(p, 1e-20)) - (loud + 0.691), 2)
                for bid, p in zip(BAND_IDS, bands)}
        for bid, lo, *_ in TONE_BANDS:
            if fs / 2 <= lo:  # the sample rate is too low to hold this band at all
                tone[bid] = None

    return {
        "version": PROFILE_VERSION,
        "name": name,
        "duration_s": round(len(x) / fs, 2),
        "loud_seconds": round(float(mask.sum()) / fs, 1),
        "loudness_lufs": round(loud, 2),
        "punch_db": round(20 * math.log10(max(peak, 1e-10)) - loud, 2),
        "contrast_lu": round(lra, 2) if lra is not None else None,
        "width_db": round(width, 2) if width is not None else None,
        "tone_db": tone,
    }


def profile_file(path, name=None):
    from pathlib import Path
    x, fs = load_audio(path)
    return measure_profile(x, fs, name or Path(path).name)


def sanitize_profile(p):
    """Check a profile that came from outside (the page, a saved set). Raises ValueError."""
    if not isinstance(p, dict):
        raise ValueError("A reference must be an object.")

    def number(v):
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("Reference values must be numbers.")
        return float(v)

    tone = p.get("tone_db")
    if tone is not None and not isinstance(tone, dict):
        raise ValueError("Reference tone must be an object.")
    out = {
        "version": PROFILE_VERSION,
        "name": str(p.get("name") or "Reference")[:200],
        "duration_s": number(p.get("duration_s")),
        "loud_seconds": number(p.get("loud_seconds")),
        **{DIMS[d][2]: number(p.get(DIMS[d][2])) for d in DIMS if d != "tone"},
        "tone_db": {b: number(tone.get(b)) for b in BAND_IDS} if tone else None,
    }
    if out["loudness_lufs"] is None:
        raise ValueError("A reference needs a loudness value.")
    return out


# ---------------------------------------------------------------- comparing

def _spread(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values), min(values), max(values)


def _row(value, spread, tol, shift=(0.0, 0.0)):
    """Where one value sits against the references. The zone is their spread plus tolerance."""
    mean, lo, hi = spread
    zone = (lo + shift[0] - tol, hi + shift[1] + tol)
    miss = max(0.0, zone[0] - value, value - zone[1])
    return {
        "value": round(value, 1), "ref": round(mean, 1), "ref_low": round(lo, 1), "ref_high": round(hi, 1),
        "zone": [round(zone[0], 2), round(zone[1], 2)], "diff": round(value - mean, 1),
        "status": "low" if value < zone[0] else "high" if value > zone[1] else "in",
        "off_by": round(miss, 1), "tolerance": tol,
        "match": round(max(0.0, 1.0 - miss / (tol * MISS_SCALE)), 2),
    }


def compare(profile, references, stage):
    """How a profile sits against 1–3 reference profiles; None without both."""
    refs = [r for r in (references or []) if r][:MAX_REFERENCES]
    if not profile or not refs:
        return None
    dims, skipped = [], []
    for dim, (name, unit, key, tol) in DIMS.items():
        if dim == "tone":
            continue
        if dim == "loudness" and stage != "master":
            skipped.append(dim)  # mastering sets the loudness of a mix
            continue
        spread, v = _spread([r.get(key) for r in refs]), profile.get(key)
        if spread is None or v is None:
            continue
        # A mix should keep more punch than the finished masters it's compared with.
        shift = MIX_PLR_SHIFT if dim == "punch" and stage == "mix" else (0.0, 0.0)
        dims.append({"id": dim, "name": name, "unit": unit, **_row(v, spread, tol, shift)})

    tone, tol = [], DIMS["tone"][3]
    mine = profile.get("tone_db") or {}
    for bid, _, _, short, fix_name, phrase, words, shape in TONE_BANDS:
        spread = _spread([(r.get("tone_db") or {}).get(bid) for r in refs])
        if spread is None or mine.get(bid) is None:
            continue
        tone.append({"id": bid, "name": short, "band": fix_name, "phrase": phrase, "words": list(words),
                     "shape": shape, **_row(mine[bid], spread, tol)})
    if tone:
        match = round(sum(b["match"] for b in tone) / len(tone), 2)
        worst = max(tone, key=lambda b: b["off_by"])
        dims.insert(len([d for d in dims if d["id"] in ("loudness", "punch", "contrast")]), {
            "id": "tone", "name": "Tone", "unit": "dB", "match": match,
            "status": "in" if worst["off_by"] == 0 else "off", "off_by": worst["off_by"], "tolerance": tol,
        })

    percent = round(100 * sum(d["match"] for d in dims) / len(dims)) if dims else None
    return {
        "references": [{"name": r.get("name") or "Reference"} for r in refs],
        "count": len(refs), "stage": stage, "percent": percent,
        "dims": dims, "tone": tone, "skipped": skipped,
    }


def reference_flags(cmp):
    """Findings that say how the file differs from the references, in their terms."""
    if not cmp:
        return []
    flags = []
    than = "than your reference" if cmp["count"] == 1 else "than your references on average"
    vs = "your reference" if cmp["count"] == 1 else "your references"

    def flag(fid, row, message, **data):
        # Past the zone by half a tolerance or more is worth a look; closer is a note.
        severity = "warning" if row["off_by"] >= row["tolerance"] / 2 else "info"
        flags.append({"id": fid, "severity": severity,
                      "message": message, "value": row["value"], "reference": row["ref"],
                      "diff": row["diff"], "off_by": row["off_by"], "references": cmp["count"], **data})

    for d in cmp["dims"]:
        if d["id"] == "tone" or d["status"] == "in":
            continue
        diff, v, ref, high = abs(d["diff"]), d["value"], d["ref"], d["status"] == "high"
        if d["id"] == "loudness":
            flag("ref_louder" if high else "ref_quieter", d,
                 f"The loud sections are {diff:.1f} LU {'louder' if high else 'quieter'} {than} "
                 f"({v:.1f} vs {ref:.1f} LUFS).")
        elif d["id"] == "punch":
            mix = " A mix should keep 2–6 dB more than the finished master." if cmp["stage"] == "mix" else ""
            flag("ref_more_dynamic" if high else "ref_more_limited", d,
                 f"Peaks stand {v:.1f} dB above the loud sections, against {ref:.1f} dB in {vs}.{mix}")
        elif d["id"] == "contrast":
            flag("ref_more_contrast" if high else "ref_less_contrast", d,
                 f"Loudness range is {diff:.1f} LU {'wider' if high else 'narrower'} {than} "
                 f"({v:.1f} vs {ref:.1f} LU).")
        elif d["id"] == "width":
            flag("ref_wider" if high else "ref_narrower", d,
                 f"The loud sections are {diff:.1f} dB {'wider' if high else 'narrower'} {than} "
                 f"(side vs mid {v:.1f} dB, against {ref:.1f} dB).")

    for b in cmp["tone"]:
        if b["status"] == "in":
            continue
        high = b["status"] == "high"
        amount = min(6.0, max(1.0, round(abs(b["diff"]) * 2) / 2))
        flag("ref_tone_more" if high else "ref_tone_less", b,
             f"{abs(b['diff']):.1f} dB {b['words'][0 if high else 1]} {b['phrase']} {than}, at matched volume.",
             band=b["id"], band_name=b["band"], phrase=b["phrase"], word=b["words"][0 if high else 1],
             shape=b["shape"], amount=f"{amount:g}")

    order = {"warning": 0, "info": 1}
    return sorted(flags, key=lambda f: (order[f["severity"]], -f["off_by"]))


def apply_reference(flags, profile, references, stage):
    """Replace any reference findings for these references and this stage. Returns (flags, comparison)."""
    cmp = compare(profile, references, stage)
    return [f for f in flags if f["id"] not in REFERENCE_IDS] + reference_flags(cmp), cmp
