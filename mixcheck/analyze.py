"""Run every measurement and produce one JSON-ready report.

This JSON is the contract between the analysis engine and everything else
(the AI report in Phase 2, a web UI, a future plugin). Change the schema on
purpose, and bump SCHEMA_VERSION when you do.
"""
import math
from pathlib import Path

from . import __version__
from .audio_io import load_audio
from .edges import measure_edges
from .loudness import measure_loudness
from .peaks import measure_peaks
from .remediation import STAGES, attach_fixes, describe_setup, detect_stage, normalize_setup
from .score import score_flags
from .style import TARGETS, measures, style_flags, style_match
from .spectrum import measure_spectrum
from .stereo import measure_stereo
from .util import fmt_time

SCHEMA_VERSION = "1.1"

# Loudness normalization references (LUFS). Platforms change these, so
# verify against their current documentation before relying on them.
STREAMING_TARGETS = {
    "Spotify": -14.0,
    "Apple Music": -16.0,
    "YouTube": -14.0,
    "Tidal": -14.0,
    "Amazon Music": -14.0,
}

# Your ears, your rules: tune these to taste and genre.
THRESHOLDS = {
    "true_peak_warn_dbtp": -1.0,
    "mono_loss_warn_db": 3.0,
    "low_end_corr_warn": 0.5,
    "dc_offset_warn_dbfs": -50.0,
    "imbalance_warn_db": 1.5,
    "long_head_silence_s": 2.0,
    "long_tail_silence_s": 5.0,
    "abrupt_end_rms_dbfs": -30.0,
}
# Loudness, punch, contrast and top end are style, judged in style.py against the user's target.


def analyze_file(path, setup=None, stage="auto", target=None):
    """Measure a file and attach fixes for this user's setup.

    setup: {"daw": id, "packages": [ids]} from catalog.py.
    stage: "mix", "master", or "auto" to guess from loudness.
    target: a style id from style.TARGETS, or None for no preference.
    """
    path = Path(path)
    x, fs = load_audio(path)
    if x.shape[1] > 2:
        raise ValueError(f"{x.shape[1]}-channel files aren't supported yet (mono or stereo only).")

    loud = measure_loudness(x, fs)
    peaks = measure_peaks(x, fs)
    integrated = loud["integrated_lufs"]

    report = {
        "schema_version": SCHEMA_VERSION,
        "analyzer_version": __version__,
        "file": {
            "name": path.name,
            "sample_rate_hz": fs,
            "channels": x.shape[1],
            "duration_s": round(len(x) / fs, 2),
        },
        "loudness": loud,
        "peaks": peaks,
        "dynamics": {
            # Peak-to-loudness ratio: how much the peaks stick out above the average.
            "plr_db": round(peaks["true_peak_max_dbtp"] - integrated, 1)
            if math.isfinite(integrated) else None,
        },
        "stereo": measure_stereo(x, fs),
        "spectrum": measure_spectrum(x, fs),
        "edges": measure_edges(x, fs),
        "streaming": streaming_adjustments(integrated),
    }
    detected, reason = detect_stage(report)
    stage = stage if stage in STAGES else detected
    setup = normalize_setup(setup)
    report["stage"] = {"value": stage, "detected": detected, "reason": reason}
    report["setup"] = {**setup, "label": describe_setup(setup)}
    target = target if target in TARGETS else None
    report["measures"] = measures(report)
    report["target"] = target
    flags = build_flags(report) + style_flags(report["measures"], target, stage)
    report["flags"] = attach_fixes(flags, setup, stage)
    report["score"] = score_flags(report["flags"], stage)
    report["style"] = style_match(report["measures"], target, stage)
    return clean(report)


def streaming_adjustments(integrated):
    if not math.isfinite(integrated):
        return None
    return {
        name: {"target_lufs": target, "gain_db": round(target - integrated, 1)}
        for name, target in STREAMING_TARGETS.items()
    }


def build_flags(r):
    """Rule-based findings. Messages stay factual; Phase 2 adds the voice."""
    t, flags = THRESHOLDS, []

    def flag(fid, severity, message, **data):
        flags.append({"id": fid, "severity": severity, "message": message, **data})

    tp = r["peaks"]["true_peak_max_dbtp"]
    if tp > 0:
        flag("true_peak_over", "critical",
             f"True peak is {tp:+.1f} dBTP, above full scale; expect distortion on playback and after lossy encoding.", value=tp)
    elif tp > t["true_peak_warn_dbtp"]:
        flag("true_peak_hot", "warning",
             f"True peak is {tp:+.1f} dBTP; most delivery specs ask for {t['true_peak_warn_dbtp']} dBTP or lower.", value=tp)

    clips = r["peaks"]["clip_events_total"]
    if clips:
        times = sorted({s for c in r["peaks"]["channels"] for s in c["clip_times_s"]})
        flag("clipping", "warning",
             f"{clips} run(s) of clipped samples, first at {', '.join(list(dict.fromkeys(fmt_time(s) for s in times))[:5])}.",
             value=clips, times_s=times)

    st = r["stereo"]
    if st:
        if st["correlation"] is not None and st["correlation"] < 0:
            flag("negative_correlation", "critical",
                 f"Overall L/R correlation is {st['correlation']:.2f}; likely a polarity problem.", value=st["correlation"])
        if st["mono_loudness_loss_db"] is not None and st["mono_loudness_loss_db"] > t["mono_loss_warn_db"]:
            flag("mono_loss", "warning",
                 f"The mix loses {st['mono_loudness_loss_db']:.1f} dB when summed to mono.", value=st["mono_loudness_loss_db"])
        lec = st["low_end_correlation"]
        if lec is not None and lec < t["low_end_corr_warn"]:
            flag("wide_low_end", "critical" if lec < 0 else "warning",
                 f"Below {st['low_end_cutoff_hz']} Hz the correlation is {lec:.2f}; bass and kick may thin out in mono.", value=lec)
        for sec in st["negative_correlation_sections"][:5]:
            flag("phase_section", "warning",
                 f"Negative correlation from {fmt_time(sec['start_s'])} to {fmt_time(sec['end_s'])} "
                 f"(min {sec['min_correlation']}).", **sec)
        bal = st["left_right_balance_db"]
        if abs(bal) > t["imbalance_warn_db"]:
            side = "left" if bal > 0 else "right"
            flag("imbalance", "warning", f"The mix leans {abs(bal):.1f} dB to the {side}.", value=bal)

    dc = [(i + 1, ch["dc_offset_dbfs"]) for i, ch in enumerate(r["peaks"]["channels"])
          if ch["dc_offset_dbfs"] > t["dc_offset_warn_dbfs"]]
    if dc:
        names = {1: "left", 2: "right"} if len(r["peaks"]["channels"]) == 2 else {1: "mono"}
        detail = ", ".join(f"{names[c]} {v} dBFS" for c, v in dc)
        flag("dc_offset", "warning", f"DC offset detected ({detail}).",
             channels=[c for c, _ in dc], value=max(v for _, v in dc))

    e = r["edges"]
    if e.get("silent_file"):
        flag("silent", "critical", "The file is silent.")
    else:
        if e["head_silence_s"] > t["long_head_silence_s"]:
            flag("long_head", "info", f"{e['head_silence_s']:.1f} s of silence before the audio starts.", value=e["head_silence_s"])
        if e["tail_silence_s"] > t["long_tail_silence_s"]:
            flag("long_tail", "info", f"{e['tail_silence_s']:.1f} s of silence after the audio ends.", value=e["tail_silence_s"])
        if e["tail_silence_s"] < 0.05 and e["final_50ms_rms_dbfs"] > t["abrupt_end_rms_dbfs"]:
            flag("abrupt_end", "warning", "The audio is still loud at the last sample; the ending may be cut off.",
                 value=e["final_50ms_rms_dbfs"])

    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(flags, key=lambda f: order[f["severity"]])


def clean(obj):
    """Make the report valid JSON: -inf/NaN become null, numpy types become Python."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "item"):  # numpy scalar
        obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj
