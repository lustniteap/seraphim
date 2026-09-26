"""Style: loudness, punch, contrast and top end, judged against what the user is going for.

These aren't errors. A trap master at -6 LUFS is right for trap and wrong for jazz,
so they stay out of the technical score. With no target picked, the old neutral
notes are raised; with a target, findings say how the file differs from that style.

Tone (bass/treble balance) isn't judged by genre here: that needs a reference track.
"""
import math

# Neutral notes when the user hasn't said what they're going for.
DEFAULT_LIMITS = {"very_loud_lufs": -9.0, "low_plr_db": 8.0, "low_lra_lu": 4.0, "lossy_air_pct": 0.005}

# Ranges for a finished master in each style. Starting points from common practice;
# tune them by measuring real releases.
TARGETS = {
    "trap_hiphop": {"name": "Trap / hip-hop", "lufs": (-9.0, -6.0), "plr": (6.0, 9.5), "lra": (2.5, 7.0)},
    "edm": {"name": "EDM / dance", "lufs": (-8.0, -5.0), "plr": (5.0, 8.5), "lra": (2.0, 6.0)},
    "pop": {"name": "Pop", "lufs": (-10.0, -7.0), "plr": (7.0, 10.0), "lra": (3.0, 7.0)},
    "rock": {"name": "Rock / metal", "lufs": (-10.0, -6.5), "plr": (6.0, 9.5), "lra": (3.0, 7.0)},
    "rnb": {"name": "R&B / soul", "lufs": (-11.0, -8.0), "plr": (8.0, 11.0), "lra": (4.0, 8.0)},
    "acoustic": {"name": "Acoustic / jazz", "lufs": (-16.0, -11.0), "plr": (10.0, 15.0), "lra": (6.0, 12.0)},
    "lofi": {"name": "Lo-fi", "lufs": (-14.0, -9.0), "plr": (8.0, 12.0), "lra": (3.0, 8.0), "dull_ok": True},
    "film": {"name": "Film / classical", "lufs": (-23.0, -16.0), "plr": (14.0, 22.0), "lra": (8.0, 20.0)},
}

# A mix isn't judged on loudness (mastering sets it) and should keep more punch than the master will.
MIX_PLR_SHIFT = (2.0, 6.0)

# id -> (name, unit, how far outside the range counts as a complete miss)
DIMS = {
    "lufs": ("Loudness", "LUFS", 4.0),
    "plr": ("Punch", "dB PLR", 4.0),
    "lra": ("Contrast", "LU", 4.0),
}

STYLE_IDS = {
    "very_loud", "low_plr", "low_lra", "no_air",
    "louder_than_target", "quieter_than_target", "more_limited_than_target",
    "more_dynamic_than_target", "less_contrast_than_target", "more_contrast_than_target",
}


def _num(v):
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def measures(report):
    """The numbers style is judged on; the page sends these back when the target changes."""
    return {
        "lufs": _num(report["loudness"]["integrated_lufs"]),
        "plr": _num(report["dynamics"]["plr_db"]),
        "lra": _num(report["loudness"]["loudness_range_lu"]),
        "air_pct": _num((report.get("spectrum") or {}).get("energy_above_16k_pct")),
    }


def ranges(target_id, stage):
    t = TARGETS[target_id]
    if stage == "master":
        return {"lufs": t["lufs"], "plr": t["plr"], "lra": t["lra"]}
    lo, hi = t["plr"]
    return {"plr": (lo + MIX_PLR_SHIFT[0], hi + MIX_PLR_SHIFT[1]), "lra": t["lra"]}


def style_flags(m, target_id, stage):
    flags = []

    def flag(fid, severity, message, **data):
        flags.append({"id": fid, "severity": severity, "message": message, **data})

    lufs, plr, lra, air = m.get("lufs"), m.get("plr"), m.get("lra"), m.get("air_pct")
    target = TARGETS.get(target_id)

    if air is not None and air < DEFAULT_LIMITS["lossy_air_pct"] and not (target or {}).get("dull_ok"):
        flag("no_air", "info",
             "Almost no content above 16 kHz; check whether an MP3/AAC or low-passed file was used as a source.", value=air)

    if target is None:
        d = DEFAULT_LIMITS
        if lufs is not None and lufs > d["very_loud_lufs"]:
            flag("very_loud", "info",
                 f"Integrated loudness is {lufs:.1f} LUFS; Spotify would turn it down about {lufs + 14:.1f} dB.", value=lufs)
        if plr is not None and plr < d["low_plr_db"]:
            flag("low_plr", "info", f"Peak-to-loudness ratio is {plr:.1f} dB; the master is heavily limited.", value=plr)
        if lra is not None and lra < d["low_lra_lu"]:
            flag("low_lra", "info", f"Loudness range is {lra:.1f} LU; there is little contrast between sections.", value=lra)
        return flags

    name, rg = target["name"], ranges(target_id, stage)
    checks = [
        ("lufs", lufs, "quieter_than_target", "louder_than_target", "LUFS"),
        ("plr", plr, "more_limited_than_target", "more_dynamic_than_target", "dB PLR"),
        ("lra", lra, "less_contrast_than_target", "more_contrast_than_target", "LU"),
    ]
    for dim, v, below_id, above_id, unit in checks:
        if dim not in rg or v is None:
            continue
        lo, hi = rg[dim]
        if lo <= v <= hi:
            continue
        miss = lo - v if v < lo else v - hi
        fid = below_id if v < lo else above_id
        flag(fid, "warning" if miss > 2.0 else "info",
             f"{DIMS[dim][0]} is {v:.1f} {unit}; typical for {name} is {lo:g} to {hi:g} {unit}.",
             value=v, target=[lo, hi], off_by=round(miss, 1))
    return flags


def apply_style(flags, m, target_id, stage):
    """Replace any style findings with ones for this target and stage."""
    return [f for f in flags if f["id"] not in STYLE_IDS] + style_flags(m, target_id, stage)


def style_match(m, target_id, stage):
    """How close the file is to the target, overall and per dimension; None with no target."""
    if target_id not in TARGETS:
        return None
    dims = []
    for dim, (lo, hi) in ranges(target_id, stage).items():
        v = m.get(dim)
        if v is None:
            continue
        name, unit, tol = DIMS[dim]
        miss = max(0.0, lo - v, v - hi)
        dims.append({
            "id": dim, "name": name, "unit": unit, "value": round(v, 1), "low": lo, "high": hi,
            "status": "low" if v < lo else "high" if v > hi else "in",
            "off_by": round(miss, 1), "tolerance": tol,
            "match": round(max(0.0, 1.0 - miss / tol), 2),
        })
    percent = round(100 * sum(d["match"] for d in dims) / len(dims)) if dims else None
    return {"target": target_id, "name": TARGETS[target_id]["name"], "stage": stage, "percent": percent, "dims": dims}


def options():
    return [{"id": k, "name": v["name"]} for k, v in TARGETS.items()]
