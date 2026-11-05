"""A 1.0–10.0 technical score, built from the findings.

It counts only the floors, the hard technical facts that are wrong in any genre: peaks and
clipping, phase and mono problems, and file/edge problems. Loudness, punch, contrast, tone and
the vocal are not errors: they are observations (observations.py), judged by the reasoning step.

Start at 10 and subtract points per finding, scaled by how bad the measurement is.
Each area has a cap so one kind of problem can't sink the whole score. The stage
matters: a peak just under 0 dB costs points on a master but not on a mix.

The labels say only what was found: a clean score reads "No technical errors found", never "ready".
Whether a mix is *ready* is a judgement about style, tone and dynamics as well, and that belongs to the
reasoning step. Its verdict is applied by apply_verdict(), the only way to earn "Ready for Wings",
and code checks the conditions before letting it through.
"""
AREAS = {
    "peaks": {"name": "Peaks & clipping", "cap": 4.0},
    "stereo": {"name": "Stereo & phase", "cap": 3.5},
    "file": {"name": "File & edges", "cap": 1.5},
}

# What the score found, in technical words. None of these says a mix is ready.
LABELS = [(9.0, "No technical errors found"), (7.0, "Minor technical issues"), (5.0, "Technical issues to fix"),
          (3.0, "Several technical problems"), (0.0, "Major technical problems")]
# What only the reasoning step's verdict can earn (see apply_verdict).
READY_LABELS = {"mix": "Ready for Wings", "master": "Ready for Wings"}
MIN_READY_VALUE = 9.0


def _points(flag, stage):
    """(area, points lost) for one finding."""
    fid, v = flag["id"], flag.get("value")
    v = v if isinstance(v, (int, float)) else 0.0
    master = stage == "master"
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
    vocal: the vocal checks were run (recorded only; the score counts floors, never the vocal estimates).
    "verdict" is None until apply_verdict() has applied the reasoning step's judgement."""
    if any(f["id"] == "silent" for f in flags):
        return {"value": 1.0, "label": "Major technical problems", "areas": [], "if_fixed": 1.0,
                "vocal_checked": bool(vocal), "verdict": None}  # nothing was bounced

    lost = {a: 0.0 for a in AREAS}
    kept = {a: 0.0 for a in AREAS}  # what's left after fixing everything but notes
    for f in flags:
        area, pts = _points(f, stage)
        pts = max(0.0, pts)
        lost[area] += pts
        if f["severity"] == "info":
            kept[area] += pts

    value = _clamp(10.0 - _total(lost))
    label = next(name for floor, name in LABELS if value >= floor)
    return {
        "value": value,
        "label": label,
        "areas": [
            {"id": a, "name": AREAS[a]["name"], "lost": round(min(AREAS[a]["cap"], lost[a]), 1)}
            for a in AREAS
        ],
        "vocal_checked": bool(vocal),
        "verdict": None,
        "if_fixed": _clamp(10.0 - _total(kept)),
    }


def apply_verdict(score, flags, stage, verdict):
    """The score with the reasoning step's verdict applied, as a new dict.

    verdict: None (not judged yet), or {"ready": bool, "open_diagnoses": int}. The "ready" label is granted only when
    the reasoning step says ready AND code agrees: the technical score is at least MIN_READY_VALUE, no diagnosis is
    still open, and no floor finding (peaks, clipping, phase and the like) is at warning level or worse. A verdict
    that doesn't meet the conditions is recorded with its blockers and leaves the label as it was."""
    out = {**score, "verdict": None}
    if verdict is None:
        return out
    if (not isinstance(verdict, dict) or not isinstance(verdict.get("ready"), bool)
            or not isinstance(verdict.get("open_diagnoses", 0), int) or isinstance(verdict.get("open_diagnoses"), bool)):
        raise ValueError('A verdict is {"ready": true or false, "open_diagnoses": a whole number}.')
    ready, open_n = verdict["ready"], verdict.get("open_diagnoses", 0)
    blockers = []
    if score["value"] < MIN_READY_VALUE:
        blockers.append(f"the technical score is below {MIN_READY_VALUE:g}")
    if open_n:
        blockers.append(f"{open_n} {'diagnosis' if open_n == 1 else 'diagnoses'} still open")
    floors = [f["id"] for f in flags if f.get("severity") in ("critical", "warning")]
    if floors:
        blockers.append("floor findings at warning level or worse: " + ", ".join(floors))
    granted = ready and not blockers
    out["verdict"] = {"ready": ready, "granted": granted, "blockers": blockers if ready else []}
    if granted:
        out["label"] = READY_LABELS[stage]
    return out


def _clamp(x):
    return round(min(10.0, max(1.0, x)), 1)
