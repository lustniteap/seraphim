"""Layer C baseline: plain rules on layer A's numbers (docs/09-analysis-model.md, groundwork step 7).

This is the bar a trained model must beat, not the perception layer itself. Each rule looks at
numbers already in the report and names an issue from the one category vocabulary of
docs/08-feedback-data.md, with the evidence it used. The thresholds are first guesses, checked
only against synthetic material (training/evaluate.py); they are not calibrated to real mixes or
to any sub-genre, so nothing here is shown to users or added to the report yet.

"probability" is how far past its threshold a rule is, squashed to 0-1. It is not calibrated:
0.8 does not yet mean "right 80% of the time".

detect_issues(report) -> [{category, probability, severity, bands, elements, time_ranges_s,
                           evidence, detector_version}]
"""
import math

DETECTOR_VERSION = "rules-0.1"

# What each rule needs to see before it speaks. "scale" is how many units past the threshold
# count as clearly wrong (probability 0.88, severity "must_fix" at twice that).
RULES = {
    "mud_bump_db": 4.0,          # 250-500 Hz above the average of the bands either side
    "sub_over_bass_db": 9.0,     # sub above bass
    "sub_under_bass_db": -9.0,   # sub below bass
    "resonance_db": 8.0,         # a resonance in 2-8 kHz standing this far out
    "top_under_presence_db": -14.0,  # 6-20 kHz below 2-4 kHz
    "low_band_correlation": 0.5,     # sub or bass correlation below this
    "side_over_mid_db": -6.0,        # whole-mix side level this close to (or above) mid
    "narrow_side_mid_db": -25.0,     # whole-mix side this far under mid
    "plr_db": 8.0,                   # peak-to-loudness ratio under this
    "scale_db": 3.0, "scale_corr": 0.3,
}


def _issue(category, margin, scale, evidence, bands=(), time_ranges=None, duration=None):
    probability = 1.0 / (1.0 + math.exp(-2.0 * margin / scale))
    severity = "must_fix" if margin >= 2 * scale else "worth_fixing" if margin >= scale else "minor"
    return {"category": category, "probability": round(probability, 2), "severity": severity,
            "bands": list(bands), "elements": [], "evidence": list(evidence),
            "time_ranges_s": time_ranges if time_ranges is not None else [[0.0, duration]],
            "detector_version": DETECTOR_VERSION}


def detect_issues(report):
    """Issues the rules can name from a report (schema 2.0 or later). Empty when nothing stands out."""
    if not report.get("bands"):
        return []
    r, issues = RULES, []
    duration = report["file"]["duration_s"]
    band = {b["id"]: b for b in report["bands"]["engineer"]}
    level = {bid: b["level_db_rel"] for bid, b in band.items()}
    have = lambda *ids: all(level.get(i) is not None for i in ids)
    add = lambda *a, **k: issues.append(_issue(*a, duration=duration, **k))

    if have("low_mids", "mud", "box"):
        bump = level["mud"] - (level["low_mids"] + level["box"]) / 2
        if bump > r["mud_bump_db"]:
            add("mud_low_mids", bump - r["mud_bump_db"], r["scale_db"], bands=["mud"],
                evidence=["bands.engineer.mud.level_db_rel", "bands.engineer.low_mids.level_db_rel",
                          "bands.engineer.box.level_db_rel"])

    sub_bass = (report.get("relations") or {}).get("ratios", {}).get("sub_to_bass_db")
    if sub_bass is not None:
        if sub_bass > r["sub_over_bass_db"]:
            add("sub_too_loud", sub_bass - r["sub_over_bass_db"], r["scale_db"], bands=["sub"],
                evidence=["relations.ratios.sub_to_bass_db"])
        elif sub_bass < r["sub_under_bass_db"]:
            add("sub_too_quiet", r["sub_under_bass_db"] - sub_bass, r["scale_db"], bands=["sub"],
                evidence=["relations.ratios.sub_to_bass_db"])

    harsh = [(i, x) for i, x in enumerate(report.get("resonances") or [])
             if 2000 <= x["hz"] <= 8000 and x["prominence_db"] >= r["resonance_db"]]
    if harsh:
        i, worst = max(harsh, key=lambda p: p[1]["prominence_db"])
        add("harsh_top", worst["prominence_db"] - r["resonance_db"], r["scale_db"],
            bands=["presence" if worst["hz"] < 4000 else "bite" if worst["hz"] < 6000 else "sibilance"],
            evidence=[f"resonances[{i}]"], time_ranges=worst["time_ranges_s"])

    if have("presence", "sibilance", "air"):
        top = 10 * math.log10(10 ** (level["sibilance"] / 10) + 10 ** (level["air"] / 10)) - level["presence"]
        if top < r["top_under_presence_db"]:
            add("dull_top", r["top_under_presence_db"] - top, r["scale_db"], bands=["sibilance", "air"],
                evidence=["bands.engineer.sibilance.level_db_rel", "bands.engineer.air.level_db_rel",
                          "bands.engineer.presence.level_db_rel"])

    st = report.get("stereo") or {}
    lows = [(bid, band[bid]["correlation"]) for bid in ("sub", "bass") if band[bid]["correlation"] is not None]
    wide_lows = [(bid, c) for bid, c in lows if c < r["low_band_correlation"]]
    side = st.get("side_to_mid_db")
    if wide_lows:
        add("too_wide", r["low_band_correlation"] - min(c for _, c in wide_lows), r["scale_corr"],
            bands=[bid for bid, _ in wide_lows],
            evidence=[f"bands.engineer.{bid}.correlation" for bid, _ in wide_lows])
    elif side is not None and side > r["side_over_mid_db"]:
        add("too_wide", side - r["side_over_mid_db"], r["scale_db"], evidence=["stereo.side_to_mid_db"])
    elif side is not None and side < r["narrow_side_mid_db"]:
        add("too_narrow", r["narrow_side_mid_db"] - side, 2 * r["scale_db"], evidence=["stereo.side_to_mid_db"])

    clips = report["peaks"].get("clip_events_total") or 0
    if clips:
        times = sorted({t for ch in report["peaks"]["channels"] for t in ch.get("clip_times_s", [])})
        add("distortion", r["scale_db"] * min(2.0, 0.5 + math.log10(clips)), r["scale_db"],
            evidence=["peaks.clip_events_total"],
            time_ranges=[[round(times[0], 1), round(times[-1], 1)]] if times else None)
    plr = (report.get("dynamics") or {}).get("plr_db")
    if plr is not None and plr < r["plr_db"] and not clips:
        add("dynamics_overcompressed", r["plr_db"] - plr, r["scale_db"], evidence=["dynamics.plr_db"])

    return sorted(issues, key=lambda i: -i["probability"])
