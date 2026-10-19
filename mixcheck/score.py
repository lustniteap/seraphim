"""A 1.0–10.0 technical score, built from the findings.

It counts only errors that are wrong in any genre: peaks and clipping, phase and
mono problems, and file/edge problems. Loudness, punch, contrast and top end are
style choices, rated separately against the user's target in style.py, and
comparisons with reference tracks (reference.py) are rated there too.

Start at 10 and subtract points per finding, scaled by how bad the measurement is.
Each area has a cap so one kind of problem can't sink the whole score. The stage
matters: a peak just under 0 dB costs points on a master but not on a mix.

The vocal checks (vocal.py) are counted only when they were run. Their numbers are estimates
when the vocal was split from the mix, so they cost less than a measured error. A mix that
hasn't had them can still be technically clean, but isn't called "Ready for mastering": nothing
has judged the vocal.
"""
from .reference import REFERENCE_IDS
from .style import STYLE_IDS
from .vocal import VOCAL_IDS

AREAS = {
    "peaks": {"name": "Peaks & clipping", "cap": 4.0},
    "stereo": {"name": "Stereo & phase", "cap": 3.5},
    "file": {"name": "File & edges", "cap": 1.5},
    "vocal": {"name": "Vocal (estimated)", "cap": 3.0},
}

LABELS = [(9.0, "Release-ready"), (7.0, "Solid"), (5.0, "Needs work"), (3.0, "Rough"), (0.0, "Major problems")]


def _points(flag, stage):
    """(area, points lost) for one finding."""
    fid, v = flag["id"], flag.get("value")
    v = v if isinstance(v, (int, float)) else 0.0
    master = stage == "master"
    if fid in VOCAL_IDS:
        return "vocal", 0.8 if flag["severity"] == "warning" else 0.3
    if fid == "true_peak_over":
        return "peaks", (1.5 if master else 1.0) + min(1.0, v * 0.25)
    if fid == "true_peak_hot":
        return "peaks", 0.5 if master else 0.0
    if fid == "clipping":
        return "peaks", min(1.5, 0.3 + 0.1 * v)
    if fid == "negative_correlation":
        return "stereo", 2.5
    if fid == "phase_section":
        return "stereo", 0.6
    if fid == "wide_low_end":
        return "stereo", 1.2 if v < 0 else 0.6
    if fid == "mono_loss":
        return "stereo", min(1.2, 0.4 + (v - 3.0) * 0.4)
    if fid == "imbalance":
        return "stereo", min(0.8, 0.3 + (abs(v) - 1.5) * 0.3)
    if fid == "dc_offset":
        return "file", 0.4
    if fid == "abrupt_end":
        return "file", 0.6
    if fid in ("long_head", "long_tail"):
        return "file", 0.2
    return "file", 0.0


def _total(lost):
    return sum(min(AREAS[a]["cap"], pts) for a, pts in lost.items())


def score_flags(flags, stage, vocal=False):
    """{"value", "label", "areas": [...], "if_fixed"}; flags must already be rated for the stage.
    vocal: the vocal checks were run, so they count and can earn "Ready for mastering"."""
    if any(f["id"] == "silent" for f in flags):
        return {"value": 1.0, "label": "Major problems", "areas": [], "if_fixed": 1.0}  # nothing was bounced

    lost = {a: 0.0 for a in AREAS}
    kept = {a: 0.0 for a in AREAS}  # what's left after fixing everything but notes
    for f in flags:
        if f["id"] in STYLE_IDS or f["id"] in REFERENCE_IDS:
            continue  # style is rated against the target or the references, not here
        area, pts = _points(f, stage)
        pts = max(0.0, pts)
        lost[area] += pts
        if f["severity"] == "info":
            kept[area] += pts

    value = _clamp(10.0 - _total(lost))
    label = next(name for floor, name in LABELS if value >= floor)
    if stage == "mix" and label == "Release-ready":
        label = "Ready for mastering" if vocal else "No technical errors found"
    return {
        "value": value,
        "label": label,
        "areas": [
            {"id": a, "name": AREAS[a]["name"], "lost": round(min(AREAS[a]["cap"], lost[a]), 1)}
            for a in AREAS if a != "vocal" or vocal or lost[a]
        ],
        "vocal_checked": bool(vocal),
        "if_fixed": _clamp(10.0 - _total(kept)),
    }


def _clamp(x):
    return round(min(10.0, max(1.0, x)), 1)
