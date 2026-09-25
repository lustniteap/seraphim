"""Turn findings into fixes for a specific studio setup.

Each finding id maps to steps written for Pro Tools + Waves Essential.
Steps marked with `needs` only appear if you list that plugin in
EXTRA_PLUGINS (plugins you own that may not be in Waves Essential).

To support another setup later (e.g. Logic + stock plugins), add a new
profile to PROFILES with the same finding ids.
"""

# Plugins you own beyond Waves Essential. Add names exactly as used below,
# e.g. {"S1 Stereo Imager", "WLM Plus", "PAZ Analyzer"}.
EXTRA_PLUGINS = set()

PT_WAVES = {
    "true_peak_over": [
        "On your master chain, set the Waves L2's Out Ceiling to -1.5 dB or lower. The L2 limits sample peaks, "
        "so leave extra headroom for inter-sample overs (measured: {value:+.1f} dBTP).",
        "Or finish with Avid Pro Limiter with inter-sample peak (ISP) detection on, ceiling at -1.0 dBTP.",
        {"needs": "WLM Plus", "text": "Confirm with WLM Plus in true-peak mode before bouncing."},
    ],
    "true_peak_hot": [
        "Set the L2 Out Ceiling to -1.5 dB. You're {over:.1f} dB over the -1.0 dBTP target, and the extra "
        "margin covers inter-sample peaks the L2 doesn't see.",
        "Or use Pro Limiter with ISP detection as the last insert, ceiling -1.0 dBTP.",
    ],
    "clipping": [
        "Jump to the timestamps below in Pro Tools and check the master fader and any bus clip indicators.",
        "If the clips come from the final limiter, lower the L2 Threshold input or pull down a Trim placed "
        "before it. If they're in the source, use Clip Gain on the offending region.",
        "Make sure nothing after the L2 (like a tape emulation such as Kramer Master Tape) adds gain.",
    ],
    "very_loud": [
        "Streaming will turn this down, so the extra limiting costs punch without adding loudness. "
        "Try easing the L2 Threshold back 2-4 dB and compare level-matched.",
    ],
    "low_plr": [
        "Ease the L2 Threshold and let some transients through; check whether the SSL E-Channel "
        "compressor or any bus compression is also clamping the peaks.",
        "For drums, a Renaissance Compressor with a slower attack on the drum bus can restore punch before the limiter.",
    ],
    "low_lra": [
        "Contrast between sections is very small. Consider volume automation or Clip Gain so verses sit "
        "a bit lower than choruses, and lighten master-bus compression.",
    ],
    "negative_correlation": [
        "The whole mix is out of polarity between left and right. Check the master fader and bus inserts "
        "for a flipped Trim, and check output routing.",
        "To test, put a Trim plugin on the master as multi-mono, flip polarity (Ø) on one side only, and check "
        "whether the problem clears.",
    ],
    "phase_section": [
        "Solo tracks in this range to find the source. Common culprits are stereo widening, "
        "an H-Delay with a very short time on one side, a stereo bass patch, and double-miked sources.",
        "On a stereo track, insert Trim as multi-mono and flip Ø on one side to test. "
        "For a track that's inverted throughout, the Invert AudioSuite plugin fixes it permanently.",
        {"needs": "PAZ Analyzer", "text": "Watch PAZ Analyzer's position/correlation display while you loop this range."},
        {"needs": "S1 Stereo Imager", "text": "S1 Imager's Rotation and Asymmetry controls can re-center a lopsided stereo source."},
    ],
    "mono_loss": [
        "Audition in mono on the master. Find the tracks that disappear and back off their widening "
        "(chorus, doubler, short stereo delays with H-Delay).",
        {"needs": "S1 Stereo Imager", "text": "Use S1 Imager on the master with Width at 0 as a quick mono check."},
    ],
    "wide_low_end": [
        "Make the bass and kick mono: check for chorus, widening or a stereo patch on those tracks.",
        "For a stereo synth bass, duplicate it: put a low-pass at ~150 Hz on a mono copy (EQ3 7-Band or "
        "Renaissance EQ), and a high-pass at the same frequency on the stereo copy.",
        {"needs": "S1 Shuffler", "text": "S1 Shuffler can narrow just the lows on a stereo source."},
    ],
    "imbalance": [
        "Check pans on the loudest elements and any stereo reverb/delay returns that lean one way.",
        "Verify the master fader's stereo output isn't unbalanced, and look for a mono-inserted plugin on only one side.",
    ],
    "dc_offset": [
        "Run the DC Offset Removal AudioSuite plugin on source tracks with offset (often old samples or "
        "recordings from a faulty interface).",
        "Or add a gentle high-pass at 20-25 Hz with Renaissance EQ or EQ3 on the master.",
    ],
    "silent": [
        "Check the Bounce Mix source: the output bus may not match the master fader's path.",
    ],
    "long_head": [
        "Tighten the timeline selection before File > Bounce Mix so it starts closer to the first note "
        "(about {value:.1f} s of silence now). Leave a few hundred milliseconds if you want a pre-roll.",
    ],
    "long_tail": [
        "Shorten the bounce selection; there's about {value:.1f} s of silence after the last sound.",
    ],
    "abrupt_end": [
        "Extend the timeline selection past the last reverb and delay tails before bouncing, "
        "then add a short fade-out on the final region, or on a new track, before bouncing again.",
    ],
    "no_air": [
        "Check the session for MP3/AAC files, such as samples or references imported into the session.",
        "Look for a low-pass on the master or a bus (EQ3, Renaissance EQ, PuigTec) cutting the top end.",
    ],
}

PROFILES = {"protools_waves_essential": PT_WAVES}
DEFAULT_PROFILE = "protools_waves_essential"


def _context(flag):
    value = flag.get("value")
    number = value if isinstance(value, (int, float)) else 0.0
    return {"value": number, "over": number + 1.0}


def steps_for(flag, profile=DEFAULT_PROFILE, extras=None):
    """Fix steps as plain strings, keeping optional ones only for owned plugins."""
    extras = EXTRA_PLUGINS if extras is None else extras
    return [s["text"] for s in all_steps_for(flag, profile)
            if s["needs"] is None or s["needs"] in extras]


def all_steps_for(flag, profile=DEFAULT_PROFILE):
    """Every step as {"text", "needs"}; needs is None for steps anyone can follow."""
    ctx, out = _context(flag), []
    for step in PROFILES[profile].get(flag["id"], []):
        if isinstance(step, dict):
            out.append({"text": step["text"].format(**ctx), "needs": step["needs"]})
        else:
            out.append({"text": step.format(**ctx), "needs": None})
    return out


def optional_plugins(profile=DEFAULT_PROFILE):
    """Names of plugins that unlock extra steps in this profile."""
    names = {s["needs"] for steps in PROFILES[profile].values() for s in steps if isinstance(s, dict)}
    return sorted(names)


def attach_remediation(flags, profile=DEFAULT_PROFILE, extras=None):
    for f in flags:
        f["remediation"] = steps_for(f, profile, extras)
        f["remediation_optional"] = [s for s in all_steps_for(f, profile) if s["needs"]]
    return flags
