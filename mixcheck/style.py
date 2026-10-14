"""Style: loudness, punch, contrast and tone, judged against what the user is going for.

These aren't errors. A trap master at -6 LUFS is right for trap and wrong for jazz,
so they stay out of the technical score. With no target picked, the old neutral
notes are raised; with a target, findings say how the file differs from that style.

The built-in ranges below are starting points from common practice. Measuring real
releases with `mixcheck-calibrate` (calibrate.py) replaces them with ranges taken
from those songs, and adds tone targets per band, which the built-in ranges don't
guess at. Calibrated ranges live in ~/.mixcheck/style_targets.json.
"""
import json
import math

from .bands import BANDS
from .util import mixcheck_home

# Neutral notes when the user hasn't said what they're going for.
DEFAULT_LIMITS = {"very_loud_lufs": -9.0, "low_plr_db": 8.0, "low_lra_lu": 4.0, "lossy_air_pct": 0.005}

# Ranges for a finished master in each style. Starting points from common practice;
# `mixcheck-calibrate` replaces them with ranges measured from real releases.
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
    "tone": ("Tone", "dB", 4.0),
}

STYLE_IDS = {
    "very_loud", "low_plr", "low_lra", "no_air",
    "louder_than_target", "quieter_than_target", "more_limited_than_target",
    "more_dynamic_than_target", "less_contrast_than_target", "more_contrast_than_target",
    "tone_more_than_target", "tone_less_than_target",
}

CALIBRATION_FILE = "style_targets.json"
_cache = {"key": None, "styles": {}}


def calibration_path():
    return mixcheck_home() / CALIBRATION_FILE


def calibration():
    """Calibrated styles from style_targets.json ({} if none). Re-read when the file changes,
    so a running web server picks up a new calibration without a restart."""
    path = calibration_path()
    try:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _cache["key"] != key:
        try:
            with open(path, encoding="utf-8") as fh:
                styles = json.load(fh).get("styles", {})
        except (OSError, ValueError, AttributeError):
            styles = {}
        _cache.update(key=key, styles=styles if isinstance(styles, dict) else {})
    return _cache["styles"]


def _pair(v):
    """A (low, high) range from JSON, or None if it isn't one."""
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(_num(x) is not None for x in v) and v[0] <= v[1]:
        return (float(v[0]), float(v[1]))
    return None


def targets():
    """Every style's ranges: built-in, with calibrated values laid over the styles that have them."""
    out, cal = {}, calibration()
    for sid, base in TARGETS.items():
        t, c = dict(base), cal.get(sid)
        if isinstance(c, dict):
            for dim in ("lufs", "plr", "lra"):
                t[dim] = _pair(c.get(dim)) or t[dim]
            tone = c.get("tone") if isinstance(c.get("tone"), dict) else {}
            tone = {b: _pair(tone.get(b)) for b in BANDS if _pair(tone.get(b))}
            if tone:
                t["tone"] = tone
            if isinstance(c.get("songs"), int):
                t["songs"] = c["songs"]
        out[sid] = t
    return out


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def measures(report):
    """The numbers style is judged on; the page sends these back when the target changes."""
    tone = (report.get("profile") or {}).get("tone_db") or {}
    return {
        "lufs": _num(report["loudness"]["integrated_lufs"]),
        "plr": _num(report["dynamics"]["plr_db"]),
        "lra": _num(report["loudness"]["loudness_range_lu"]),
        "air_pct": _num((report.get("spectrum") or {}).get("energy_above_16k_pct")),
        # Band levels at matched volume, on the loudest sections (see reference.py).
        "tone": {b: _num(tone.get(b)) for b in BANDS} if tone else None,
    }


def ranges(target_id, stage):
    t = targets()[target_id]
    out = {"lra": t["lra"]}
    if stage == "master":
        out.update(lufs=t["lufs"], plr=t["plr"])
    else:
        lo, hi = t["plr"]
        out["plr"] = (lo + MIX_PLR_SHIFT[0], hi + MIX_PLR_SHIFT[1])
    if t.get("tone"):
        out["tone"] = t["tone"]  # tone at matched volume holds for a mix as much as a master
    return {k: out[k] for k in ("lufs", "plr", "lra", "tone") if k in out}


def _tone_values(m):
    tone = m.get("tone")
    return {b: _num(v) for b, v in tone.items() if b in BANDS and _num(v) is not None} if isinstance(tone, dict) else {}


def style_flags(m, target_id, stage):
    flags = []

    def flag(fid, severity, message, **data):
        flags.append({"id": fid, "severity": severity, "message": message, **data})

    lufs, plr, lra, air = (_num(m.get(k)) for k in ("lufs", "plr", "lra", "air_pct"))
    target = targets().get(target_id)

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

    # Tone, band by band, once the style has been calibrated from real releases.
    mine = _tone_values(m)
    for bid, (lo, hi) in rg.get("tone", {}).items():
        v = mine.get(bid)
        if v is None or lo <= v <= hi:
            continue
        # Lo-fi is dull on purpose: a dark top end is the point, not a problem.
        if bid == "highs" and v < lo and target.get("dull_ok"):
            continue
        high = v > hi
        miss = v - hi if high else lo - v
        _, _, _, _, band_name, phrase, words, shape = BANDS[bid]
        amount = min(6.0, max(1.0, round(miss * 2) / 2))
        flag("tone_more_than_target" if high else "tone_less_than_target", "warning" if miss > 2.0 else "info",
             f"{miss:.1f} dB {words[0 if high else 1]} {phrase} than typical for {name}, at matched volume.",
             value=round(v, 1), target=[lo, hi], off_by=round(miss, 1), band=bid, band_name=band_name,
             phrase=phrase, word=words[0 if high else 1], shape=shape, amount=f"{amount:g}", style=name)
    return flags


def apply_style(flags, m, target_id, stage):
    """Replace any style findings with ones for this target and stage."""
    return [f for f in flags if f["id"] not in STYLE_IDS] + style_flags(m, target_id, stage)


def _row(v, lo, hi, tol):
    miss = max(0.0, lo - v, v - hi)
    return {
        "value": round(v, 1), "low": lo, "high": hi,
        "status": "low" if v < lo else "high" if v > hi else "in",
        "off_by": round(miss, 1), "tolerance": tol,
        "match": round(max(0.0, 1.0 - miss / tol), 2),
    }


def style_match(m, target_id, stage):
    """How close the file is to the target, overall and per dimension; None with no target."""
    all_targets = targets()
    if target_id not in all_targets:
        return None
    t, dims, tone = all_targets[target_id], [], []
    for dim, rg in ranges(target_id, stage).items():
        name, unit, tol = DIMS[dim]
        if dim == "tone":
            mine = _tone_values(m)
            for bid, (lo, hi) in rg.items():
                if mine.get(bid) is None:
                    continue
                row = _row(mine[bid], lo, hi, tol)
                if bid == "highs" and row["status"] == "low" and t.get("dull_ok"):
                    row.update(status="in", off_by=0.0, match=1.0)
                band = BANDS[bid]
                tone.append({"id": bid, "name": band[3], "words": list(band[6]), **row})
            if tone:
                worst = max(b["off_by"] for b in tone)
                dims.append({"id": "tone", "name": name, "unit": unit, "tolerance": tol,
                             "status": "in" if worst == 0 else "off", "off_by": worst,
                             "match": round(sum(b["match"] for b in tone) / len(tone), 2)})
            continue
        v = _num(m.get(dim))
        if v is None:
            continue
        lo, hi = rg
        dims.append({"id": dim, "name": name, "unit": unit, **_row(v, lo, hi, tol)})
    percent = round(100 * sum(d["match"] for d in dims) / len(dims)) if dims else None
    return {"target": target_id, "name": t["name"], "stage": stage, "percent": percent,
            "dims": dims, "tone": tone, "songs": t.get("songs")}


def options():
    return [{"id": k, "name": v["name"], "songs": v.get("songs")} for k, v in targets().items()]
