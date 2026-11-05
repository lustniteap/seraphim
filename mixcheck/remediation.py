"""Turn findings into short fixes for one user's setup and stage.

Each finding id maps to a list of steps, either the same for mixes and masters
or split by stage. A step is one of:

    do("action")    an action from catalog.ACTIONS; rendered with the best tool
                    the user owns, or the generic wording if they own none
    say("text")     advice that doesn't depend on tools

Steps marked more=True go under "More options"; the rest are the short list
the user sees first. The user's other tools for a primary action also go
under "More options".

Stage matters: clipping in a mix headed for mastering is fixed with gain
staging, not a limiter. STAGE_SEVERITY re-rates findings that mean something
different for a mix.
"""
from .catalog import ACTIONS, DAWS, PACKAGES, expand_packages, owned_tools
from .util import fmt_time

STAGES = ("mix", "master")
DEFAULT_SETUP = {"daw": "other", "packages": []}

# A mix above this integrated loudness is almost certainly already mastered.
MASTER_LUFS = -13.0


def do(action, more=False):
    return {"do": action, "more": more}


def say(text, more=False):
    return {"say": text, "more": more}


FIXES = {
    "true_peak_over": {
        "master": [do("limit_true_peak"), do("loudness_meter", more=True)],
        "mix": [do("master_headroom"), do("remove_mix_limiting", more=True)],
    },
    "true_peak_hot": {
        "master": [do("limit_true_peak"), do("loudness_meter", more=True)],
        "mix": [do("master_headroom")],
    },
    "clipping": {
        "master": [
            say("Go to {times}. Clipping in a master usually means something after the limiter adds gain, "
                "or the limiter's ceiling is at 0 dB."),
            do("limit_true_peak"),
            say("Remove or turn down anything after the limiter, such as tape or saturation plugins.", more=True),
        ],
        "mix": [
            say("Go to {times} and watch the clip indicators to find which track or bus clips."),
            do("clip_gain"),
            do("master_headroom", more=True),
        ],
    },
    "very_loud": {
        "master": [
            do("ease_limiting"),
            say("Streaming services turn this down to about −14 LUFS anyway, so the extra limiting only costs punch.", more=True),
        ],
        "mix": [do("remove_mix_limiting"), do("master_headroom")],
    },
    "low_plr": {
        "master": [do("ease_limiting"), do("restore_transients", more=True), do("ease_bus_comp", more=True)],
        "mix": [do("remove_mix_limiting"), do("ease_bus_comp"), do("restore_transients", more=True)],
    },
    "low_lra": [do("volume_automation"), do("ease_bus_comp", more=True)],
    # Relative to the style the user is going for (style.py).
    "louder_than_target": [do("ease_limiting")],
    "quieter_than_target": [do("push_limiting"), do("loudness_meter", more=True)],
    "more_limited_than_target": {
        "master": [do("ease_limiting"), do("restore_transients", more=True)],
        "mix": [do("remove_mix_limiting"), do("ease_bus_comp")],
    },
    "more_dynamic_than_target": {
        "master": [do("glue_compression"), do("push_limiting")],
        "mix": [do("glue_compression")],
    },
    "less_contrast_than_target": [do("volume_automation"), do("ease_bus_comp", more=True)],
    "more_contrast_than_target": [do("tame_contrast"), do("glue_compression", more=True)],
    # Relative to the user's reference tracks (reference.py).
    "ref_louder": [do("ease_limiting")],
    "ref_quieter": [do("push_limiting"), do("loudness_meter", more=True)],
    "ref_more_limited": {
        "master": [do("ease_limiting"), do("restore_transients", more=True)],
        "mix": [do("remove_mix_limiting"), do("ease_bus_comp"), do("restore_transients", more=True)],
    },
    "ref_more_dynamic": {
        "master": [do("glue_compression"), do("push_limiting", more=True)],
        "mix": [do("glue_compression")],
    },
    "ref_less_contrast": [do("volume_automation"), do("ease_bus_comp", more=True)],
    "ref_more_contrast": [do("tame_contrast"), do("glue_compression", more=True)],
    "ref_narrower": [
        do("widen_image"),
        say("Keep the kick, bass and lead vocal in the middle; width should come from pads, guitars, "
            "backing vocals and effects returns.", more=True),
    ],
    "ref_wider": [do("narrow_width"), do("mono_check", more=True)],
    "tone_more_than_target": {
        "master": [do("eq_cut_band")],
        "mix": [
            say("Solo the parts that fill {band} in the loud sections and turn down or EQ the one doing the most; "
                "fixing it at the source beats EQ on the whole mix."),
            do("eq_cut_band", more=True),
        ],
    },
    "tone_less_than_target": {
        "master": [do("eq_boost_band")],
        "mix": [
            say("Find the parts that should carry {band} in the loud sections and bring them up or EQ them there; "
                "fixing it at the source beats EQ on the whole mix."),
            do("eq_boost_band", more=True),
        ],
    },
    "ref_tone_more": {
        "master": [do("eq_cut_band"), say("Loop the loudest section and switch between your master and the reference, "
                                          "at matched volume, while you set the cut.", more=True)],
        "mix": [
            say("Solo the parts that fill {band} in the loud sections and turn down or EQ the one doing the most; "
                "fixing it at the source beats EQ on the whole mix."),
            do("eq_cut_band", more=True),
        ],
    },
    "ref_tone_less": {
        "master": [do("eq_boost_band"), say("Loop the loudest section and switch between your master and the reference, "
                                            "at matched volume, while you set the boost.", more=True)],
        "mix": [
            say("Find the parts that should carry {band} in the loud sections and bring them up or EQ them there; "
                "fixing it at the source beats EQ on the whole mix."),
            do("eq_boost_band", more=True),
        ],
    },
    "negative_correlation": [
        say("The whole mix is out of polarity between left and right. Check the master and bus inserts, "
            "and the output routing, for a flip on one side."),
        do("flip_one_side"),
    ],
    "phase_section": [
        say("Solo tracks between {start} and {end} to find the source. Usual suspects: stereo wideners, "
            "a very short delay on one side, a stereo bass patch, or double-miked sources."),
        do("flip_one_side"),
        do("correlation_meter", more=True),
        do("invert_track", more=True),
    ],
    "mono_loss": [do("mono_check"), do("narrow_width")],
    "wide_low_end": [
        do("mono_low_end"),
        say("Check the kick and bass tracks for chorus, wideners or stereo patches.", more=True),
    ],
    "imbalance": [
        do("recenter_image"),
        say("Check that the master's output isn't unbalanced and that no plugin is inserted on one side only.", more=True),
    ],
    "dc_offset": [do("remove_dc")],
    "silent": [say("Check that the bounce or export source is your main output and that no tracks are muted.")],
    "long_head": [do("trim_silence")],
    "long_tail": [do("trim_silence")],
    "abrupt_end": [do("include_tail"), do("fade_out", more=True)],
    "no_air": [
        say("Check the session for MP3 or AAC files, such as samples or imported references."),
        do("find_lowpass"),
    ],
    # The vocal on its own (vocal.py). Estimated when the vocal was split from the mix.
    "vocal_uncompressed": [
        do("compress_vocal"),
        say("Then ride the words that still jump out, so the vocal holds one level against the beat.", more=True),
    ],
    "vocal_muddy": [do("cut_vocal_mud"), do("highpass_vocal", more=True)],
    "vocal_thin": [
        do("add_vocal_warmth"),
        say("If it sounds thin on every vocal, check the mic distance and the room before reaching for EQ.", more=True),
    ],
    "vocal_rumble": [do("highpass_vocal")],
    "vocal_sibilant": [do("deess_vocal")],
    "vocal_buried": [do("raise_vocal"), do("compress_vocal", more=True)],
    "vocal_dominant": [do("lower_vocal")],
}

# How a finding should be rated when the file is a mix rather than a master.
STAGE_SEVERITY = {
    "mix": {
        "true_peak_hot": "info",   # fine for a mix; mastering sets the final ceiling
        "very_loud": "warning",    # a limited mix leaves mastering nothing to work with
        "low_plr": "warning",
    },
}
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}

# Actions about *any* tool of a kind (e.g. "turn off your limiters"): name every
# owned tool that fits instead of picking one.
ANY_OWNED = {"remove_mix_limiting": "Check for"}


def detect_stage(report):
    """Guess mix or master from loudness; the user can override it."""
    lufs = report["loudness"]["integrated_lufs"]
    if lufs is not None and lufs > MASTER_LUFS:
        return "master", f"It measures {lufs:.1f} LUFS, which is master-level loudness.".replace("-", "−")
    return "mix", "It isn't limited to master loudness, so it looks like a mix."


def normalize_setup(setup):
    setup = setup or {}
    daw = setup.get("daw") if setup.get("daw") in DAWS else DEFAULT_SETUP["daw"]
    return {"daw": daw, "packages": expand_packages(setup.get("packages"))}


def describe_setup(setup):
    # Waves plugins are listed together, like "Waves (L2, F6)", rather than as many separate items.
    waves = [PACKAGES[p]["name"] for p in setup["packages"] if PACKAGES[p]["group"] == "Waves"]
    others = [PACKAGES[p]["name"] for p in setup["packages"] if PACKAGES[p]["group"] != "Waves"]
    parts = [DAWS[setup["daw"]]] + ([f"Waves ({', '.join(waves)})"] if waves else []) + others
    return " + ".join(parts)


def _context(flag):
    times = list(dict.fromkeys(fmt_time(t) for t in flag.get("times_s") or []))  # one per second
    shown = ", ".join(times[:3]) + (f" and {len(times) - 3} more" if len(times) > 3 else "")
    return {
        "value": flag.get("value") if isinstance(flag.get("value"), (int, float)) else 0.0,
        "times": shown or "the marked spots",
        "start": fmt_time(flag["start_s"]) if "start_s" in flag else "the marked section",
        "end": fmt_time(flag["end_s"]) if "end_s" in flag else "",
        "band": flag.get("band_name") or "that range",
        "amount": flag.get("amount") or "2",
        "shape": flag.get("shape") or "wide bell",
    }


def _ranked(action, tools):
    """Tools that can do an action, best first."""
    found = [(t["can"][action][0], tid, t) for tid, t in tools.items() if action in t["can"]]
    return [(tid, t) for _, tid, t in sorted(found, key=lambda x: -x[0])]


def steps_for(flag_id, stage):
    spec = FIXES.get(flag_id, [])
    return spec[stage] if isinstance(spec, dict) else spec


def build_fix(flag, setup, stage):
    """{"steps": [...], "more": [...]}; each step is {"text", "tool", "action"}."""
    tools, ctx = owned_tools(setup), _context(flag)
    fix = {"steps": [], "more": []}
    for step in steps_for(flag["id"], stage):
        target = fix["more"] if step["more"] else fix["steps"]
        if "say" in step:
            target.append({"text": step["say"].format(**ctx), "tool": None, "action": None})
            continue
        action = step["do"]
        ranked = _ranked(action, tools)
        if not ranked:
            target.append({"text": ACTIONS[action].format(**ctx), "tool": None, "action": action})
            continue
        if action in ANY_OWNED:
            names = ", ".join(t["name"] for _, t in ranked)
            target.append({"text": f"{ACTIONS[action]} {ANY_OWNED[action]}: {names}.", "tool": None, "action": action})
            continue
        (best_id, best), *others = ranked
        target.append({"text": best["can"][action][1].format(**ctx), "tool": best["name"], "action": action})
        # Other tools the user owns for the same job are alternatives, not extra steps.
        for _, t in others:
            fix["more"].append({"text": t["can"][action][1].format(**ctx), "tool": t["name"], "action": action})
    return fix


def attach_fixes(flags, setup=None, stage="mix"):
    """Rate each finding for the stage and attach fixes for the user's tools."""
    setup = normalize_setup(setup)
    for f in flags:
        base = f.setdefault("base_severity", f["severity"])
        f["severity"] = STAGE_SEVERITY.get(stage, {}).get(f["id"], base)
        f["fix"] = build_fix(f, setup, stage)
        f["remediation"] = [s["text"] for s in f["fix"]["steps"]]
        f.pop("remediation_optional", None)
    flags.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])
    return flags
