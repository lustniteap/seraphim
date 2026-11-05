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
    "hiphop_rap": {"name": "Hip-hop / rap", "lufs": (-9.0, -6.0), "plr": (6.0, 9.5), "lra": (2.5, 7.0)},
    "edm": {"name": "EDM / dance", "lufs": (-8.0, -5.0), "plr": (5.0, 8.5), "lra": (2.0, 6.0)},
    "pop": {"name": "Pop", "lufs": (-10.0, -7.0), "plr": (7.0, 10.0), "lra": (3.0, 7.0)},
    "rock": {"name": "Rock / metal", "lufs": (-10.0, -6.5), "plr": (6.0, 9.5), "lra": (3.0, 7.0)},
    "rnb": {"name": "R&B / soul", "lufs": (-11.0, -8.0), "plr": (8.0, 11.0), "lra": (4.0, 8.0)},
    "acoustic": {"name": "Acoustic / jazz", "lufs": (-16.0, -11.0), "plr": (10.0, 15.0), "lra": (6.0, 12.0)},
    "lofi": {"name": "Lo-fi", "lufs": (-14.0, -9.0), "plr": (8.0, 12.0), "lra": (3.0, 8.0), "dull_ok": True},
    "film": {"name": "Film / classical", "lufs": (-23.0, -16.0), "plr": (14.0, 22.0), "lra": (8.0, 20.0)},
}

# Ids a style used to go by. Saved calibrations (style_targets.json), command-line --style values
# and the page's saved choice may still use them, so they keep working everywhere.
LEGACY_IDS = {"trap_hiphop": "hiphop_rap"}

# Sub-genres, each under one of the eight parent styles above. A sub-genre is only listed when its
# technical targets should differ from its parent's. Until it has ranges of its own it uses its
# parent's (see targets()). Key format is "parent.sub". Priority is the order to calibrate them in:
# 1 first, 2 next, 3 when there's demand. An optional "flags" overrides a flag the parent sets.
_SUBGENRES = [
    ("hiphop_rap", "trap", "Trap", 1),
    ("hiphop_rap", "drill", "Drill", 1),
    ("hiphop_rap", "boom_bap", "Boom bap", 1),
    ("hiphop_rap", "rage", "Rage", 1),
    ("hiphop_rap", "melodic", "Melodic / emo rap", 1),
    ("edm", "house", "House / tech house", 2),
    ("edm", "techno", "Techno", 3),
    ("edm", "dubstep", "Dubstep / bass music", 2),
    ("edm", "drum_and_bass", "Drum & bass", 3),
    ("edm", "future_bass", "Melodic / future bass", 3),
    ("pop", "mainstream", "Mainstream / radio pop", 2),
    ("pop", "dance_pop", "Dance pop", 2),
    ("pop", "indie_pop", "Indie / bedroom pop", 2),
    ("pop", "ballad", "Pop ballad", 3),
    ("rock", "alternative", "Alternative / indie rock", 2),
    ("rock", "classic_rock", "Classic rock", 3),
    ("rock", "punk", "Punk / pop-punk", 3),
    ("rock", "metal", "Metal / metalcore", 2),
    ("rnb", "contemporary", "Contemporary R&B", 2),
    ("rnb", "alternative", "Alternative R&B", 3),
    ("rnb", "neo_soul", "Neo-soul", 3),
    ("rnb", "classic_soul", "Classic soul", 3),
    ("acoustic", "singer_songwriter", "Singer-songwriter / folk", 3),
    ("acoustic", "americana", "Americana / acoustic band", 3),
    ("acoustic", "jazz", "Jazz (combo)", 3),
    ("lofi", "chillhop", "Lo-fi hip hop / chillhop", 2),
    ("lofi", "indie", "Chill / lo-fi indie", 3),
    ("film", "trailer", "Trailer / hybrid cinematic", 3),
    ("film", "orchestral", "Orchestral score", 3),
    ("film", "classical", "Classical", 3),
    ("film", "ambient", "Ambient / soundscape", 3),
]
SUBGENRES = {
    f"{parent}.{slug}": {"parent": parent, "slug": slug, "name": name, "priority": priority}
    for parent, slug, name, priority in _SUBGENRES
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


def canonical(target_id):
    """The current id for a style id (a parent, a "parent.sub" sub-genre, or a legacy id), else None."""
    if not isinstance(target_id, str):
        return None
    sid = LEGACY_IDS.get(target_id, target_id)
    return sid if sid in TARGETS or sid in SUBGENRES else None


def style_ids():
    """Every style id that can be picked: each parent, then its sub-genres."""
    return [sid for parent in TARGETS for sid in (parent, *(s for s, v in SUBGENRES.items() if v["parent"] == parent))]


def _calibrated(cal, sid):
    """The saved calibration for one style, also looking under the id it used to have."""
    for key in (sid, *(old for old, new in LEGACY_IDS.items() if new == sid)):
        if isinstance(cal.get(key), dict):
            return cal[key]
    return None


def _overlay(t, c):
    """Lay a saved calibration over a target. Returns the dimensions the calibration supplied."""
    own = set()
    for dim in ("lufs", "plr", "lra"):
        pair = _pair(c.get(dim))
        if pair:
            t[dim] = pair
            own.add(dim)
    tone = c.get("tone") if isinstance(c.get("tone"), dict) else {}
    tone = {b: _pair(tone.get(b)) for b in BANDS if _pair(tone.get(b))}
    if tone:
        t["tone"] = tone
        own.add("tone")
    songs = c.get("songs")
    if isinstance(songs, int) and not isinstance(songs, bool):
        t["songs"] = songs
    return own


# Under this many songs a calibration is "rough"; from here it's "calibrated".
ROUGH_BELOW = 8
DIM_WORDS = {"lufs": "loudness", "plr": "punch", "lra": "contrast", "tone": "tone"}


def _plural(n):
    return f"{n} song" + ("" if n == 1 else "s")


def _source(t, own, parent=None):
    """Where a target's numbers came from, so the page and the notes can say how far to trust them.

    kind: "estimated" (built in), "rough" or "calibrated" (measured from songs), or "inherited"
    (a sub-genre still using its parent's numbers). A sub-genre with some ranges of its own and
    some from its parent is judged by its own songs and lists what it takes from the parent."""
    songs = t.get("songs") if own else None
    inherits = [d for d in DIM_WORDS if parent is not None and d not in own and (d != "tone" or t.get("tone"))]
    if songs:
        kind = "rough" if songs < ROUGH_BELOW else "calibrated"
        label = f"{kind} ({_plural(songs)})"
        if inherits:
            label += "; " + ", ".join(DIM_WORDS[d] for d in inherits) + f" from {parent['name']}"
    elif parent is not None:
        kind, label = "inherited", f"inherited from {parent['name']}: {parent['source']['label']}"
    else:
        kind, label = "estimated", "built-in estimate"
    borrows = parent is not None and (kind == "inherited" or bool(inherits))
    return {"kind": kind, "songs": songs or None, "label": label,
            "from": parent["id"] if borrows else None, "from_name": parent["name"] if borrows else None,
            "parent_label": parent["source"]["label"] if borrows else None,
            "inherits": inherits if songs else []}


def targets():
    """Every style's ranges, parents and sub-genres: built-in, with calibrated values laid over the
    styles that have them. A sub-genre uses its parent's ranges (and flags such as dull_ok) for
    anything it hasn't been calibrated on itself."""
    out, cal = {}, calibration()
    for sid, base in TARGETS.items():
        t = dict(base)
        c = _calibrated(cal, sid)
        own = _overlay(t, c) if c else set()
        t.update(id=sid, parent=None, full_name=t["name"])
        t["source"] = _source(t, own)
        out[sid] = t
    for sid, sub in SUBGENRES.items():
        parent = out[sub["parent"]]
        t = {k: v for k, v in parent.items() if k not in ("songs", "source")}
        c = _calibrated(cal, sid)
        own = _overlay(t, c) if c else set()
        t.update(id=sid, parent=sub["parent"], name=sub["name"], full_name=f"{sub['name']} ({parent['name']})",
                 priority=sub["priority"], **sub.get("flags", {}))
        t["source"] = _source(t, own, parent)
        if not own:
            t.pop("songs", None)
        out[sid] = t
    return out


def get_target(target_id):
    """One style's resolved ranges by any id it has had, or None."""
    sid = canonical(target_id)
    return targets()[sid] if sid else None


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
    t = get_target(target_id)
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
    t = get_target(target_id)
    if t is None:
        return None
    dims, tone = [], []
    for dim, rg in ranges(t["id"], stage).items():
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
    return {"target": t["id"], "name": t["full_name"], "stage": stage, "percent": percent,
            "dims": dims, "tone": tone, "songs": t.get("songs"), "source": t["source"]}


def options():
    """Every style the page can offer: each parent, followed by its sub-genres. A sub-genre carries its
    parent's id so the picker can group them. `songs` is the songs this style's own ranges came from."""
    all_targets = targets()
    return [{"id": sid, "name": all_targets[sid]["name"], "parent": all_targets[sid]["parent"],
             "group": all_targets[all_targets[sid]["parent"] or sid]["name"],
             "songs": all_targets[sid].get("songs"), "source": all_targets[sid]["source"]}
            for sid in style_ids()]
