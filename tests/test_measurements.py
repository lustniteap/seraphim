"""Checks against signals with known answers.

Run with:  python -m pytest tests   (or: python tests/test_measurements.py)
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Keep the user's own reference sets and style calibration out of the tests.
os.environ["MIXCHECK_HOME"] = __import__("tempfile").mkdtemp(prefix="mixcheck-test-")

from mixcheck.analyze import analyze_file  # noqa: E402
from mixcheck.loudness import integrated_lufs, k_weighting_coeffs  # noqa: E402
from mixcheck.peaks import find_clipping, true_peak  # noqa: E402
from mixcheck.stereo import measure_stereo  # noqa: E402

FS = 48000


def sine(freq, dbfs, seconds=10.0, fs=FS, phase=0.0):
    t = np.arange(int(seconds * fs)) / fs
    return 10 ** (dbfs / 20) * np.sin(2 * np.pi * freq * t + phase)


def stereo(sig):
    return np.column_stack([sig, sig])


def test_k_weighting_matches_itu_48k():
    # Reference coefficients published in ITU-R BS.1770-4 for 48 kHz.
    (b1, a1), (b2, a2) = k_weighting_coeffs(48000)
    assert np.allclose(b1, [1.53512485958697, -2.69169618940638, 1.19839281085285], atol=1e-9)
    assert np.allclose(a1, [1.0, -1.69065929318241, 0.73248077421585], atol=1e-9)
    assert np.allclose(b2, [1.0, -2.0, 1.0])
    assert np.allclose(a2, [1.0, -1.99004745483398, 0.99007225036621], atol=1e-9)


def test_ebu_sine_reads_its_own_level():
    # EBU Tech 3341: a stereo 1 kHz sine at -23 dBFS reads -23.0 LUFS.
    for level in (-23.0, -33.0):
        assert abs(integrated_lufs(stereo(sine(1000, level)), FS) - level) < 0.1


def test_works_at_44k1():
    assert abs(integrated_lufs(stereo(sine(1000, -23, fs=44100)), 44100) + 23) < 0.1


def test_true_peak_catches_intersample_peak():
    # A sine at fs/4 sampled 45 degrees off its peaks: samples reach only
    # about -3 dB of the real peak, but the true peak is the full amplitude.
    sig = sine(FS / 4, -1.0, phase=np.pi / 4)
    sample_peak = 20 * np.log10(np.max(np.abs(sig)))
    tp = 20 * np.log10(true_peak(sig))
    assert sample_peak < -3.5
    assert abs(tp - (-1.0)) < 0.2


def test_clipping_detected():
    sig = np.clip(sine(100, 3.0, seconds=1), -1, 1)
    count, times = find_clipping(sig, FS)
    assert count > 50 and times[0] < 0.01
    assert find_clipping(sine(100, -1.0, seconds=1), FS)[0] == 0


def test_polarity_flip_is_caught():
    sig = sine(80, -12)
    st = measure_stereo(np.column_stack([sig, -sig]), FS)
    assert st["correlation"] < -0.99
    assert st["low_end_correlation"] < -0.99
    assert st["mono_loudness_loss_db"] is None or st["mono_loudness_loss_db"] > 40


def test_uncorrelated_noise_loses_3db_in_mono():
    rng = np.random.default_rng(0)
    x = 0.1 * rng.standard_normal((FS * 10, 2))
    st = measure_stereo(x, FS)
    assert abs(st["correlation"]) < 0.02
    assert abs(st["mono_loudness_loss_db"] - 3.0) < 0.2


def test_full_report_on_file(tmp_path=None):
    from scipy.io import wavfile
    import json
    import tempfile

    folder = tmp_path or tempfile.mkdtemp()
    path = os.path.join(str(folder), "clipped.wav")
    sig = np.clip(sine(220, 2.0), -1, 1)
    wavfile.write(path, FS, (stereo(sig) * 32767).astype(np.int16))

    report = analyze_file(path)
    json.dumps(report)  # must be valid JSON
    ids = {f["id"] for f in report["flags"]}
    assert "clipping" in ids and "abrupt_end" in ids


def _finding_ids():
    import inspect
    import re
    from mixcheck import analyze
    from mixcheck.reference import REFERENCE_IDS
    from mixcheck.style import STYLE_IDS
    return set(re.findall(r'flag\("(\w+)"', inspect.getsource(analyze.build_flags))) | STYLE_IDS | REFERENCE_IDS


def test_every_finding_has_a_fix():
    from mixcheck.remediation import FIXES, STAGES, steps_for
    ids = _finding_ids()
    assert not ids - set(FIXES), f"no fix for {ids - set(FIXES)}"
    for fid in ids:
        for stage in STAGES:
            assert any(not s["more"] for s in steps_for(fid, stage)), f"{fid} has no main step for a {stage}"


def test_catalog_is_consistent():
    from mixcheck.catalog import ACTIONS, DAWS, PACKAGES, TOOLS
    from mixcheck.remediation import FIXES, STAGES, steps_for
    for tid, tool in TOOLS.items():
        assert set(tool["in"]) <= set(DAWS) | set(PACKAGES), f"{tid} is in an unknown package"
        assert set(tool["can"]) <= set(ACTIONS), f"{tid} can do an unknown action"
    for fid in FIXES:
        for stage in STAGES:
            for step in steps_for(fid, stage):
                assert "say" in step or step["do"] in ACTIONS, f"{fid} uses unknown action {step.get('do')}"


def test_every_fix_renders_for_every_setup():
    # Formatting every step with every tool catches typos in {placeholders}.
    from mixcheck.catalog import DAWS, PACKAGES
    from mixcheck.remediation import STAGES, attach_fixes
    everything = list(PACKAGES)
    for daw in DAWS:
        for packages in ([], everything):
            for stage in STAGES:
                flags = [{"id": fid, "severity": "warning", "message": "", "value": -0.5,
                          "times_s": [1.0, 1.2, 14.0, 20.0, 31.0], "start_s": 6.0, "end_s": 8.0}
                         for fid in _finding_ids()]
                for f in attach_fixes(flags, {"daw": daw, "packages": packages}, stage):
                    assert f["fix"]["steps"], f"{f['id']} has no steps for {daw}/{stage}"
                    texts = [s["text"] for s in f["fix"]["steps"] + f["fix"]["more"]]
                    assert not any("{" in t or "}" in t for t in texts), f"unfilled placeholder in {f['id']}"


def test_best_owned_tool_wins():
    from mixcheck.remediation import attach_fixes
    flag = lambda: [{"id": "true_peak_over", "severity": "critical", "message": "", "value": 1.2}]
    stock = attach_fixes(flag(), {"daw": "pro_tools", "packages": []}, "master")[0]["fix"]
    assert stock["steps"][0]["tool"] == "Pro Limiter"
    pro = attach_fixes(flag(), {"daw": "pro_tools", "packages": ["fabfilter", "waves_essential"]}, "master")[0]["fix"]
    assert pro["steps"][0]["tool"] == "FabFilter Pro-L 2"
    assert {"Pro Limiter", "Waves L2"} <= {s["tool"] for s in pro["more"]}
    generic = attach_fixes(flag(), {"daw": "other", "packages": []}, "master")[0]["fix"]
    assert generic["steps"][0]["tool"] is None and "true-peak limiter" in generic["steps"][0]["text"]


def test_stage_changes_the_fix_and_rating():
    from mixcheck.remediation import attach_fixes
    flag = lambda: [{"id": "true_peak_hot", "severity": "warning", "message": "", "value": -0.4}]
    master = attach_fixes(flag(), {"daw": "logic"}, "master")[0]
    mix = attach_fixes(flag(), {"daw": "logic"}, "mix")[0]
    assert master["severity"] == "warning" and mix["severity"] == "info"
    assert "Adaptive Limiter" in master["fix"]["steps"][0]["text"]
    assert "Gain" in mix["fix"]["steps"][0]["text"] and "−6" in mix["fix"]["steps"][0]["text"]
    # Switching back restores the engine's rating.
    assert attach_fixes([mix], {"daw": "logic"}, "master")[0]["severity"] == "warning"


def test_score_rewards_clean_and_scales_with_severity():
    from mixcheck.score import score_flags
    assert score_flags([], "master")["value"] == 10.0
    assert score_flags([{"id": "silent", "severity": "critical"}], "mix")["value"] == 1.0
    over = lambda tp: score_flags([{"id": "true_peak_over", "severity": "critical", "value": tp}], "master")["value"]
    assert 10.0 > over(0.2) > over(3.0) >= 1.0
    # A peak just under 0 dB matters for a master, not for a mix.
    hot = [{"id": "true_peak_hot", "severity": "warning", "value": -0.4}]
    assert score_flags(hot, "master")["value"] < score_flags(hot, "mix")["value"] == 10.0
    # Area caps stop one kind of problem from sinking the score.
    many = [{"id": "phase_section", "severity": "warning"}] * 20
    assert score_flags(many, "mix")["value"] == 6.5
    # Style findings never cost technical points.
    style = [{"id": "very_loud", "severity": "info", "value": -5.0},
             {"id": "quieter_than_target", "severity": "warning", "value": -14.0}]
    assert score_flags(style, "master")["value"] == 10.0
    # "If fixed" keeps only the notes.
    s = score_flags([{"id": "clipping", "severity": "warning", "value": 4},
                     {"id": "dc_offset", "severity": "info", "value": -40.0}], "master")
    assert s["value"] < s["if_fixed"] == 9.6


def test_every_finding_is_scored():
    from mixcheck.score import _points
    # Realistic values for each finding; every one must cost points on at least one stage.
    typical = {"true_peak_over": 0.5, "true_peak_hot": -0.5, "clipping": 3, "very_loud": -7.0, "low_plr": 6.0,
               "low_lra": 3.0, "negative_correlation": -0.3, "mono_loss": 4.0, "wide_low_end": 0.2,
               "imbalance": 2.0, "dc_offset": -40.0, "long_head": 3.0, "long_tail": 6.0, "abrupt_end": -20.0,
               "no_air": 0.001, "phase_section": None}
    from mixcheck.reference import REFERENCE_IDS
    from mixcheck.style import STYLE_IDS
    for fid in _finding_ids() - {"silent"} - STYLE_IDS - REFERENCE_IDS:
        flag = {"id": fid, "severity": "warning", "value": typical[fid]}
        assert max(_points(flag, st)[1] for st in ("mix", "master")) > 0, f"{fid} is never scored"


def test_style_is_judged_against_the_target():
    from mixcheck.style import apply_style, style_flags, style_match
    loud = {"lufs": -7.0, "plr": 8.0, "lra": 4.0, "air_pct": 0.001}
    trap, jazz = style_match(loud, "trap_hiphop", "master"), style_match(loud, "acoustic", "master")
    assert trap["percent"] == 100 and jazz["percent"] < 50
    assert {f["id"] for f in style_flags(loud, "acoustic", "master")} >= {"louder_than_target", "more_limited_than_target"}
    # Lo-fi is dull on purpose; other styles still get the note.
    assert "no_air" not in {f["id"] for f in style_flags(loud, "lofi", "master")}
    assert "no_air" in {f["id"] for f in style_flags(loud, "pop", "master")}
    # A mix isn't judged on loudness.
    assert "lufs" not in {d["id"] for d in style_match(loud, "acoustic", "mix")["dims"]}
    # No target: the neutral notes, and no match.
    assert style_match(loud, None, "master") is None
    assert "very_loud" in {f["id"] for f in style_flags(loud, None, "master")}
    # Changing target swaps the style findings and leaves the rest alone.
    flags = [{"id": "clipping", "severity": "warning"}] + style_flags(loud, "acoustic", "master")
    swapped = apply_style(flags, loud, "trap_hiphop", "master")
    assert [f["id"] for f in swapped] == ["clipping", "no_air"]


def _song(seconds=30, bass_db=0.0, width=0.3, seed=1):
    """Noise 'song': a quiet first half, a loud second half, with adjustable lows and width."""
    rng = np.random.default_rng(seed)
    n = FS * seconds
    mid, side = rng.standard_normal(n), width * rng.standard_normal(n)
    x = 0.1 * np.column_stack([mid + side, mid - side])
    spec, f = np.fft.rfft(x, axis=0), np.fft.rfftfreq(n, 1 / FS)
    spec[(f >= 20) & (f < 100)] *= 10 ** (bass_db / 20)
    x = np.fft.irfft(spec, n=n, axis=0)
    x[: n // 2] *= 0.3
    return x


def test_reference_profile_is_matched_volume():
    # Turning a song down changes its loudness and nothing else.
    from mixcheck.reference import measure_profile
    a, b = measure_profile(_song(), FS), measure_profile(_song() * 0.5, FS)
    assert abs(a["loudness_lufs"] - b["loudness_lufs"] - 6.02) < 0.05
    for key in ("punch_db", "contrast_lu", "width_db"):
        assert abs(a[key] - b[key]) < 0.05, key
    assert all(abs(a["tone_db"][k] - b["tone_db"][k]) < 0.05 for k in a["tone_db"])


def test_reference_uses_the_loudest_sections():
    # A long, quiet, bass-only intro shouldn't change the tone of the loud part.
    from mixcheck.reference import measure_profile
    loud = _song(seconds=20)[FS * 10:]
    intro = np.column_stack([sine(60, -40, seconds=30)] * 2)
    alone, with_intro = measure_profile(loud, FS), measure_profile(np.vstack([intro, loud]), FS)
    assert abs(with_intro["loud_seconds"] - alone["loud_seconds"]) < 2.0
    assert all(abs(alone["tone_db"][k] - with_intro["tone_db"][k]) < 0.5 for k in alone["tone_db"])


def test_reference_findings_are_relative():
    from mixcheck.reference import compare, measure_profile, reference_flags
    from mixcheck.remediation import attach_fixes
    ref = measure_profile(_song(seed=2), FS, "Ref")
    same = compare(measure_profile(_song(seed=3), FS), [ref], "master")
    assert same["percent"] == 100 and not reference_flags(same)

    light = compare(measure_profile(_song(bass_db=-3.5, width=0.15, seed=3) * 0.4, FS), [ref], "master")
    flags = {f["id"]: f for f in reference_flags(light)}
    assert set(flags) == {"ref_tone_less", "ref_narrower", "ref_quieter"}
    assert flags["ref_tone_less"]["band"] == "lows" and -4.0 < flags["ref_tone_less"]["diff"] < -2.8
    assert "lighter below 100 Hz than your reference" in flags["ref_tone_less"]["message"]
    assert light["percent"] < 70
    fix = attach_fixes([flags["ref_tone_less"]], {"daw": "ableton", "packages": ["fabfilter"]}, "master")[0]["fix"]
    assert "the lows (below 100 Hz)" in fix["steps"][0]["text"] and fix["steps"][0]["tool"] == "FabFilter Pro-Q"

    # A mix isn't compared on loudness, and reference findings never cost technical points.
    mix = compare(measure_profile(_song(seed=3) * 0.2, FS), [ref], "mix")
    assert "loudness" in mix["skipped"] and "loudness" not in {d["id"] for d in mix["dims"]}
    from mixcheck.score import score_flags
    assert score_flags(reference_flags(light), "master")["value"] == 10.0


def test_reference_sets_are_saved_and_reused(tmp_path=None):
    import tempfile
    from mixcheck import refsets
    from mixcheck.reference import measure_profile
    old = os.environ.get("MIXCHECK_HOME")
    os.environ["MIXCHECK_HOME"] = str(tmp_path or tempfile.mkdtemp())
    try:
        prof = measure_profile(_song(seconds=10), FS, "Ref A")
        refsets.save_set("  Trap   refs ", [prof])
        assert [s["name"] for s in refsets.list_sets()] == ["Trap refs"]
        assert refsets.get_set("Trap refs")["references"][0]["tone_db"] == prof["tone_db"]
        for bad in ([], [prof] * 4, [{"name": "no numbers"}]):
            try:
                refsets.save_set("Bad", bad)
                raise AssertionError("bad set was saved")
            except ValueError:
                pass
        refsets.delete_set("Trap refs")
        assert refsets.list_sets() == []
    finally:
        if old is None:
            os.environ.pop("MIXCHECK_HOME", None)
        else:
            os.environ["MIXCHECK_HOME"] = old


def _calibrate_to(styles):
    import json
    from mixcheck.style import calibration_path
    calibration_path().parent.mkdir(parents=True, exist_ok=True)
    with open(calibration_path(), "w") as fh:
        json.dump({"version": 1, "styles": styles}, fh)
    os.utime(calibration_path(), ns=(0, len(json.dumps(styles))))  # so the cache sees each rewrite


def test_calibrated_style_ranges_and_tone():
    from mixcheck.style import calibration_path, options, style_flags, style_match, targets
    tone = {"lows": [-24, -20], "low_mids": [-26, -22], "mids": [-17, -13], "presence": [-13, -9], "highs": [-8, -4]}
    m = {"lufs": -7.0, "plr": 8.0, "lra": 4.0, "air_pct": 0.1,
         "tone": {"lows": -28.0, "low_mids": -24.0, "mids": -15.0, "presence": -11.0, "highs": -10.0}}
    try:
        _calibrate_to({"trap_hiphop": {"songs": 12, "lufs": [-8, -5], "plr": [5, 8], "lra": [3, 6], "tone": tone},
                       "lofi": {"songs": 6, "lufs": [-14, -9], "plr": [8, 12], "lra": [3, 8], "tone": tone},
                       "pop": {"lufs": "loud", "tone": {"lows": [3, 1]}}})
        t = targets()
        assert t["trap_hiphop"]["lufs"] == (-8, -5) and t["trap_hiphop"]["songs"] == 12
        assert t["pop"]["lufs"] == (-10.0, -7.0) and "tone" not in t["pop"]  # malformed values are ignored
        assert t["edm"]["lufs"] == (-8.0, -5.0)  # styles that weren't calibrated keep their ranges
        assert {o["id"]: o["songs"] for o in options()}["trap_hiphop"] == 12

        sm = style_match(m, "trap_hiphop", "mix")
        assert sm["songs"] == 12 and [d["id"] for d in sm["dims"]] == ["plr", "lra", "tone"]
        lows = next(b for b in sm["tone"] if b["id"] == "lows")
        assert lows["status"] == "low" and lows["off_by"] == 4.0
        tone_flags = [f for f in style_flags(m, "trap_hiphop", "master") if f["id"] == "tone_less_than_target"]
        assert [f["band"] for f in tone_flags] == ["lows", "highs"]
        assert "4.0 dB lighter below 100 Hz than typical for Trap / hip-hop" in tone_flags[0]["message"]
        # Lo-fi's dull top end is the point, not a finding.
        lofi = [f for f in style_flags(m, "lofi", "master") if f["id"] == "tone_less_than_target"]
        assert [f["band"] for f in lofi] == ["lows"]
    finally:
        calibration_path().unlink()
    assert targets()["trap_hiphop"]["lufs"] == (-9.0, -6.0) and "tone" not in targets()["trap_hiphop"]


def test_calibrate_builds_ranges_from_songs():
    from mixcheck.calibrate import aliases, calibrate, collect, spread
    from mixcheck.style import calibration_path, targets
    # The middle 15–85% of the songs, never narrower than the minimum, rounded outward.
    assert spread([-8.2, -7.9, -7.5, -7.1, -6.6], 2.0) == [-8.5, -6.0]
    assert spread([-7.0] * 5, 2.0) == [-8.0, -6.0]
    names = aliases()
    assert names["trap"] == names["hiphop"] == names["traphiphop"] == "trap_hiphop"
    assert names["lofi"] == "lofi" and names["rb"] == "rnb" and names["jazz"] == "acoustic"

    import tempfile
    import soundfile as sf
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "Hip-Hop"))
    os.makedirs(os.path.join(root, "not a style"))
    for i in range(3):
        sf.write(os.path.join(root, "Hip-Hop", f"s{i}.wav"), _song(seconds=31, bass_db=6.0, seed=i) * 2.5, FS)
    sf.write(os.path.join(root, "Hip-Hop", "clip.wav"), _song(seconds=10, seed=9), FS)
    groups, unknown = collect(root)
    assert list(groups) == ["trap_hiphop"] and len(groups["trap_hiphop"]) == 4 and unknown == ["not a style"]
    try:
        assert calibrate(groups, min_songs=4, jobs=1, out=lambda *a: None) == {}  # the clip is too short to count
        new = calibrate(groups, min_songs=3, jobs=1, out=lambda *a: None)["trap_hiphop"]
        assert new["songs"] == 3 and len(new["tone"]) == 5
        t = targets()["trap_hiphop"]
        assert t["songs"] == 3 and list(t["lufs"]) == new["lufs"]
        assert t["lufs"][1] - t["lufs"][0] >= 2.0
    finally:
        calibration_path().unlink()


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS  {name}")
    print(f"\nAll {len(tests)} tests passed.")
