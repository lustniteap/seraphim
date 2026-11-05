"""Observations: neutral comparisons of a measurement with a range, tagged to a stage of the chain.

An observation says what was measured, what it was compared with, how far outside that range it sits and how far to
trust the range. It carries **no severity and no verdict**. Whether it matters for this song, its sub-genre and its
stage is the reasoning step's judgement. The only findings that carry a severity are the floors (analyze.build_flags):
hard technical facts with a standard, such as peaks over the ceiling, clipping and polarity.

Three comparisons produce observations:

  style      the measurement against the chosen style's range (style.py), with that range's provenance
  reference  the measurement against the person's reference songs (reference.py)
  vocal      the vocal measurements (vocal.py), which are estimates unless a stem was supplied

and, with no style chosen, neutral defaults plus a note when the top end is missing.

Every observation is tagged to one of the ten stages of the chain (see docs/contracts.md), so an explanation connects
to the plugin the person is using. `playbook` names the recipe in remediation.FIXES that turns an out-of-range
observation into steps for the person's own tools.
"""
from .bands import BANDS
from .remediation import build_fix
from .style import DEFAULT_LIMITS, get_target
from . import vocal as vocal_mod

CHAIN = {1: "Gain staging", 2: "Cleanup", 3: "Tone EQ", 4: "Dynamics", 5: "De-essing", 6: "Colour", 7: "Space",
         8: "Level and balance", 9: "Stereo and phase", 10: "Master bus"}

# Which stage of the chain a dimension belongs to.
STAGE_OF = {"loudness": 10, "punch": 10, "contrast": 4, "tone": 3, "top_end": 3, "width": 9,
            "vocal_dynamics": 4, "vocal_mud": 3, "vocal_body": 3, "vocal_rumble": 2, "vocal_sibilance": 5,
            "vocal_level": 8}

# (source, dimension, direction the measurement sits) -> the recipe in remediation.FIXES.
PLAYBOOK = {
    ("style", "loudness", "high"): "louder_than_target", ("style", "loudness", "low"): "quieter_than_target",
    ("style", "punch", "low"): "more_limited_than_target", ("style", "punch", "high"): "more_dynamic_than_target",
    ("style", "contrast", "low"): "less_contrast_than_target", ("style", "contrast", "high"): "more_contrast_than_target",
    ("style", "tone", "high"): "tone_more_than_target", ("style", "tone", "low"): "tone_less_than_target",
    ("reference", "loudness", "high"): "ref_louder", ("reference", "loudness", "low"): "ref_quieter",
    ("reference", "punch", "low"): "ref_more_limited", ("reference", "punch", "high"): "ref_more_dynamic",
    ("reference", "contrast", "low"): "ref_less_contrast", ("reference", "contrast", "high"): "ref_more_contrast",
    ("reference", "width", "low"): "ref_narrower", ("reference", "width", "high"): "ref_wider",
    ("reference", "tone", "high"): "ref_tone_more", ("reference", "tone", "low"): "ref_tone_less",
    ("default", "loudness", "high"): "very_loud", ("default", "punch", "low"): "low_plr",
    ("default", "contrast", "low"): "low_lra", ("file", "top_end", "low"): "no_air",
    ("vocal", "vocal_dynamics", "high"): "vocal_uncompressed", ("vocal", "vocal_mud", "high"): "vocal_muddy",
    ("vocal", "vocal_body", "low"): "vocal_thin", ("vocal", "vocal_rumble", "high"): "vocal_rumble",
    ("vocal", "vocal_sibilance", "high"): "vocal_sibilant", ("vocal", "vocal_level", "low"): "vocal_buried",
    ("vocal", "vocal_level", "high"): "vocal_dominant",
}

DIM_NAMES = {"lufs": "loudness", "plr": "punch", "lra": "contrast"}
WORDS = {"loudness": ("louder", "quieter"), "contrast": ("wider", "narrower"), "width": ("wider", "narrower")}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _observation(source, dimension, scope, value, unit, low, high, status, off_by, trust, summary,
                 band=None, estimated=False, context=None, **extra):
    stage_no = STAGE_OF[dimension]
    oid = f"{source}.{dimension}" + (f".{band}" if band else "")
    playbook = PLAYBOOK.get((source, dimension, status)) if status != "in" else None
    return {
        "id": oid, "source": source, "stage_no": stage_no, "stage": CHAIN[stage_no], "scope": scope,
        "dimension": dimension, **({"band": band} if band else {}),
        "value": value, "unit": unit, "range": {"low": low, "high": high}, "status": status,
        "off_by": round(off_by, 1), "trust": trust, "estimated": estimated, "summary": summary,
        "playbook": playbook, "context": context or {}, **extra,
    }


def _amount(miss):
    return f"{min(6.0, max(1.0, round(miss * 2) / 2)):g}"


# ---------------------------------------------------------------- style

def style_observations(sm, stage):
    """From style.style_match(): one observation per dimension and per tone band."""
    if not sm:
        return []
    out, name, trust = [], sm["name"], {"kind": sm["source"]["kind"], "label": sm["source"]["label"]}
    for d in sm["dims"]:
        if d["id"] == "tone":
            continue
        dim, unit = DIM_NAMES[d["id"]], d["unit"].replace("dB PLR", "dB")
        lo, hi, v = d["low"], d["high"], d["value"]
        where = "in range" if d["status"] == "in" else f"{d['off_by']:.1f} {unit} {'below' if d['status'] == 'low' else 'above'}"
        out.append(_observation(
            "style", dim, stage, v, unit, lo, hi, d["status"], d["off_by"], trust,
            f"{dim.capitalize()} is {v:.1f} {unit}; the range for {name} is {lo:g} to {hi:g} {unit} ({where})."))
    for b in sm["tone"]:
        bid, high = b["id"], b["status"] == "high"
        _, _, _, _, band_name, phrase, words, shape = BANDS[bid]
        if b["status"] == "in":
            summary = f"{b['name']} is within the typical range for {name}, at matched volume."
        else:
            summary = f"{b['off_by']:.1f} dB {words[0 if high else 1]} {phrase} than typical for {name}, at matched volume."
        out.append(_observation(
            "style", "tone", stage, b["value"], "dB", b["low"], b["high"], b["status"], b["off_by"], trust,
            summary, band=bid, context={"band_name": band_name, "phrase": phrase, "word": words[0 if high else 1],
                                        "shape": shape, "amount": _amount(b["off_by"])}))
    return out


# ---------------------------------------------------------------- reference

def reference_observations(cmp, stage):
    """From reference.compare(): one observation per dimension and per tone band."""
    if not cmp:
        return []
    out = []
    count = cmp["count"]
    trust = {"kind": "reference", "label": f"{count} reference song{'' if count == 1 else 's'}"}
    than = "than your reference" if count == 1 else "than your references on average"
    for d in cmp["dims"]:
        if d["id"] == "tone":
            continue
        dim = d["id"]
        high, unit = d["status"] == "high", d["unit"]
        lo, hi = d["zone"]
        if d["status"] == "in":
            summary = f"{dim.capitalize()} is in line with your reference{'s' if count != 1 else ''} ({d['value']:.1f} {unit} against {d['ref']:.1f})."
        elif dim == "punch":
            summary = f"Peaks stand {d['value']:.1f} dB above the loud sections, against {d['ref']:.1f} dB in your reference{'s' if count != 1 else ''}."
        else:
            more, less = WORDS.get(dim, ("higher", "lower"))
            summary = (f"{dim.capitalize()} is {abs(d['diff']):.1f} {unit} {more if high else less} {than} "
                       f"({d['value']:.1f} vs {d['ref']:.1f} {unit}).")
        out.append(_observation("reference", dim, stage, d["value"], unit, lo, hi, d["status"], d["off_by"],
                                trust, summary, reference=d["ref"]))
    for b in cmp["tone"]:
        bid, high = b["id"], b["status"] == "high"
        lo, hi = b["zone"]
        if b["status"] == "in":
            summary = f"{b['name']} is in line with your reference{'s' if count != 1 else ''}, at matched volume."
        else:
            summary = f"{abs(b['diff']):.1f} dB {b['words'][0 if high else 1]} {b['phrase']} {than}, at matched volume."
        out.append(_observation(
            "reference", "tone", stage, b["value"], "dB", lo, hi, b["status"], b["off_by"], trust, summary,
            band=bid, reference=b["ref"],
            context={"band_name": b["band"], "phrase": b["phrase"], "word": b["words"][0 if high else 1],
                     "shape": b["shape"], "amount": _amount(abs(b["diff"]))}))
    return out


# ---------------------------------------------------------------- defaults and the file

def default_observations(m, stage, target_id):
    """With no style chosen: neutral notes on loudness, punch and contrast, and a note when the top end is missing."""
    d, out = DEFAULT_LIMITS, []
    trust = {"kind": "default", "label": "neutral defaults; no style chosen"}
    if not target_id:
        lufs, plr, lra = (_num(m.get(k)) for k in ("lufs", "plr", "lra"))
        if lufs is not None:
            hi = lufs > d["very_loud_lufs"]
            out.append(_observation(
                "default", "loudness", stage, lufs, "LUFS", None, d["very_loud_lufs"], "high" if hi else "in",
                max(0.0, lufs - d["very_loud_lufs"]), trust,
                f"Integrated loudness is {lufs:.1f} LUFS; Spotify would turn it down about {lufs + 14:.1f} dB."))
        if plr is not None:
            lo = plr < d["low_plr_db"]
            out.append(_observation(
                "default", "punch", stage, plr, "dB", d["low_plr_db"], None, "low" if lo else "in",
                max(0.0, d["low_plr_db"] - plr), trust, f"Peak-to-loudness ratio is {plr:.1f} dB."))
        if lra is not None:
            lo = lra < d["low_lra_lu"]
            out.append(_observation(
                "default", "contrast", stage, lra, "LU", d["low_lra_lu"], None, "low" if lo else "in",
                max(0.0, d["low_lra_lu"] - lra), trust, f"Loudness range is {lra:.1f} LU."))
    air = _num(m.get("air_pct"))
    target = get_target(target_id) if target_id else None
    if air is not None and not (target or {}).get("dull_ok"):
        low = air < d["lossy_air_pct"]
        out.append(_observation(
            "file", "top_end", stage, air, "%", d["lossy_air_pct"], None, "low" if low else "in",
            max(0.0, d["lossy_air_pct"] - air), {"kind": "default", "label": "rule of thumb"},
            "Almost no content above 16 kHz; it may be an MP3/AAC or low-passed source." if low
            else "There is content above 16 kHz."))
    return out


# ---------------------------------------------------------------- vocal

def vocal_observations(v):
    """From vocal.measure_vocal(): estimates of the vocal's own chain. Empty when no vocal was found."""
    if not v or not v.get("found"):
        return []
    L = vocal_mod.LIMITS
    trust = {"kind": "estimate", "label": "estimated from a split of the mix"}
    out = []

    def one(dim, key, value, summary, lower_worse=False, unit="dB", **extra):
        first, second = L[key]
        status = ("low" if value <= first else "in") if lower_worse else ("high" if value >= first else "in")
        far = value <= second if lower_worse else value >= second
        out.append(_observation(
            "vocal", dim, "vocal", value, unit, first if lower_worse else None, None if lower_worse else first,
            status, max(0.0, (first - value) if lower_worse else (value - first)), trust, summary,
            estimated=True, beyond_second_limit=bool(far and status != "in"), **extra))

    crest, spread = v["crest_db"], v["range_db"]
    dyn_high = crest >= L["crest_db"][0] or spread >= L["range_db"][0]
    out.append(_observation(
        "vocal", "vocal_dynamics", "vocal", spread, "dB", None, L["range_db"][0],
        "high" if dyn_high else "in", max(0.0, spread - L["range_db"][0]), trust,
        f"The vocal's loud words sit {spread:.1f} dB above the typical word and its peaks sit {crest:.1f} dB above its average.",
        estimated=True, crest_db=crest,
        beyond_second_limit=bool(dyn_high and (crest >= L["crest_db"][1] or spread >= L["range_db"][1]))))
    if "mud_db" in v:
        one("vocal_mud", "mud_db", v["mud_db"], f"The vocal is {v['mud_db']:+.1f} dB at 200–500 Hz against its mids.")
        one("vocal_body", "body_db", v["body_db"], f"The vocal is {v['body_db']:+.1f} dB at 100–250 Hz against its mids.", lower_worse=True)
        one("vocal_rumble", "rumble_db", v["rumble_db"], f"The vocal is {v['rumble_db']:+.1f} dB below 80 Hz against its mids.")
        one("vocal_sibilance", "sibilance_db", v["sibilance_db"], f"The vocal's 5–9 kHz peaks sit {v['sibilance_db']:+.1f} dB over its mids.")
    gap = v.get("vocal_to_beat_db")
    if gap is not None:
        buried, over = L["beat_gap_db"][0], L["beat_over_db"][0]
        status = "low" if gap <= buried else "high" if gap >= over else "in"
        miss = max(0.0, buried - gap) if status == "low" else max(0.0, gap - over) if status == "high" else 0.0
        far = gap <= L["beat_gap_db"][1] if status == "low" else gap >= L["beat_over_db"][1]
        out.append(_observation(
            "vocal", "vocal_level", "vocal", gap, "dB", buried, over, status, miss, trust,
            f"The vocal sits {gap:+.1f} dB against the beat while it is singing.", estimated=True,
            beyond_second_limit=bool(far and status != "in")))
    return out


# ---------------------------------------------------------------- putting it together

def build_observations(m, stage, target_id, style_match_result, reference_result, vocal):
    """Every observation for one bounce: style, reference, defaults, and the vocal if it was checked."""
    return (style_observations(style_match_result, stage) + reference_observations(reference_result, stage)
            + default_observations(m, stage, target_id) + vocal_observations(vocal))


def attach_observation_fixes(observations, setup, stage):
    """Add steps for the person's own tools to each observation that is outside its range. Returns the list."""
    for o in observations:
        o.pop("fix", None)
        if o["status"] == "in" or not o["playbook"]:
            continue
        o["fix"] = build_fix({"id": o["playbook"], "value": o["value"], **o["context"]}, setup, stage)
    return observations
