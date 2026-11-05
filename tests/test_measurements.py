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
    from mixcheck.vocal import VOCAL_IDS
    return (set(re.findall(r'flag\("(\w+)"', inspect.getsource(analyze.build_flags)))
            | STYLE_IDS | REFERENCE_IDS | VOCAL_IDS)


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
    from mixcheck.vocal import VOCAL_IDS
    typical.update({fid: 1.0 for fid in VOCAL_IDS})  # estimated vocal findings cost points in their own area
    for fid in _finding_ids() - {"silent"} - STYLE_IDS - REFERENCE_IDS:
        flag = {"id": fid, "severity": "warning", "value": typical[fid]}
        assert max(_points(flag, st)[1] for st in ("mix", "master")) > 0, f"{fid} is never scored"


def test_style_is_judged_against_the_target():
    from mixcheck.style import apply_style, style_flags, style_match
    loud = {"lufs": -7.0, "plr": 8.0, "lra": 4.0, "air_pct": 0.001}
    trap, jazz = style_match(loud, "hiphop_rap", "master"), style_match(loud, "acoustic", "master")
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
    swapped = apply_style(flags, loud, "hiphop_rap", "master")
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
    with open(calibration_path(), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "styles": styles}, fh)
    os.utime(calibration_path(), ns=(0, len(json.dumps(styles))))  # so the cache sees each rewrite


def test_calibrated_style_ranges_and_tone():
    from mixcheck.style import calibration_path, options, style_flags, style_match, targets
    tone = {"lows": [-24, -20], "low_mids": [-26, -22], "mids": [-17, -13], "presence": [-13, -9], "highs": [-8, -4]}
    m = {"lufs": -7.0, "plr": 8.0, "lra": 4.0, "air_pct": 0.1,
         "tone": {"lows": -28.0, "low_mids": -24.0, "mids": -15.0, "presence": -11.0, "highs": -10.0}}
    try:
        _calibrate_to({"hiphop_rap": {"songs": 12, "lufs": [-8, -5], "plr": [5, 8], "lra": [3, 6], "tone": tone},
                       "lofi": {"songs": 6, "lufs": [-14, -9], "plr": [8, 12], "lra": [3, 8], "tone": tone},
                       "pop": {"lufs": "loud", "tone": {"lows": [3, 1]}}})
        t = targets()
        assert t["hiphop_rap"]["lufs"] == (-8, -5) and t["hiphop_rap"]["songs"] == 12
        assert t["pop"]["lufs"] == (-10.0, -7.0) and "tone" not in t["pop"]  # malformed values are ignored
        assert t["edm"]["lufs"] == (-8.0, -5.0)  # styles that weren't calibrated keep their ranges
        assert {o["id"]: o["songs"] for o in options()}["hiphop_rap"] == 12

        sm = style_match(m, "hiphop_rap", "mix")
        assert sm["songs"] == 12 and [d["id"] for d in sm["dims"]] == ["plr", "lra", "tone"]
        lows = next(b for b in sm["tone"] if b["id"] == "lows")
        assert lows["status"] == "low" and lows["off_by"] == 4.0
        tone_flags = [f for f in style_flags(m, "hiphop_rap", "master") if f["id"] == "tone_less_than_target"]
        assert [f["band"] for f in tone_flags] == ["lows", "highs"]
        assert "4.0 dB lighter below 100 Hz than typical for Hip-hop / rap" in tone_flags[0]["message"]
        # Lo-fi's dull top end is the point, not a finding.
        lofi = [f for f in style_flags(m, "lofi", "master") if f["id"] == "tone_less_than_target"]
        assert [f["band"] for f in lofi] == ["lows"]
    finally:
        calibration_path().unlink()
    assert targets()["hiphop_rap"]["lufs"] == (-9.0, -6.0) and "tone" not in targets()["hiphop_rap"]


def test_calibrate_builds_ranges_from_songs():
    from mixcheck.calibrate import aliases, calibrate, collect, spread
    from mixcheck.style import calibration_path, targets
    # The middle 15–85% of the songs, never narrower than the minimum, rounded outward.
    assert spread([-8.2, -7.9, -7.5, -7.1, -6.6], 2.0) == [-8.5, -6.0]
    assert spread([-7.0] * 5, 2.0) == [-8.0, -6.0]
    names = aliases()
    assert names["trap"] == names["hiphop"] == names["traphiphop"] == "hiphop_rap"
    assert names["lofi"] == "lofi" and names["rb"] == "rnb" and names["jazz"] == "acoustic"

    import json
    import tempfile
    import soundfile as sf
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "Hip-Hop"))
    os.makedirs(os.path.join(root, "not a style"))
    for i in range(3):
        sf.write(os.path.join(root, "Hip-Hop", f"s{i}.wav"), _song(seconds=31, bass_db=6.0, seed=i) * 2.5, FS)
    sf.write(os.path.join(root, "Hip-Hop", "clip.wav"), _song(seconds=10, seed=9), FS)
    groups, unknown = collect(root)
    assert list(groups) == ["hiphop_rap"] and len(groups["hiphop_rap"]) == 4 and unknown == ["not a style"]
    try:
        _calibrate_to({"trap_hiphop": {"songs": 99, "lufs": [-30, -29]}, "lofi": {"songs": 6, "lufs": [-14, -9]}})
        assert calibrate(groups, min_songs=4, jobs=1, out=lambda *a: None) == {}  # the clip is too short to count
        new = calibrate(groups, min_songs=3, jobs=1, out=lambda *a: None)["hiphop_rap"]
        assert new["songs"] == 3 and len(new["tone"]) == 5
        t = targets()["hiphop_rap"]
        assert t["songs"] == 3 and list(t["lufs"]) == new["lufs"]
        assert t["lufs"][1] - t["lufs"][0] >= 2.0
        # A calibration saved under the old id moves to the new one when the file is rewritten; others are kept.
        with open(calibration_path(), encoding="utf-8") as fh:
            saved = json.load(fh)["styles"]
        assert "trap_hiphop" not in saved and saved["hiphop_rap"]["songs"] == 3 and saved["lofi"]["songs"] == 6
    finally:
        calibration_path().unlink()


def test_old_style_id_keeps_working():
    import argparse
    import tempfile
    from scipy.io import wavfile
    from mixcheck.cli import style_arg
    from mixcheck.style import canonical, style_flags, style_match
    assert canonical("trap_hiphop") == canonical("hiphop_rap") == "hiphop_rap"
    assert canonical("hiphop_rap.drill") == "hiphop_rap.drill"
    assert canonical("nope") is None and canonical(None) is None and canonical("") is None and canonical(["x"]) is None

    loud = {"lufs": -7.0, "plr": 8.0, "lra": 4.0, "air_pct": 0.001}
    assert style_match(loud, "trap_hiphop", "master") == style_match(loud, "hiphop_rap", "master")
    assert style_flags(loud, "trap_hiphop", "master") == style_flags(loud, "hiphop_rap", "master")
    assert style_match(loud, "nope", "master") is None

    # The command line takes the old id and the new ones, and says which ids exist when it's wrong.
    assert style_arg("trap_hiphop") == "hiphop_rap" and style_arg("hiphop_rap.drill") == "hiphop_rap.drill"
    try:
        style_arg("rock_n_roll")
        assert False, "an unknown style should be refused"
    except argparse.ArgumentTypeError as exc:
        assert "hiphop_rap" in str(exc) and "hiphop_rap.drill" in str(exc)

    # A whole analysis: the report records the current id, and an unknown one still means no preference.
    path = os.path.join(tempfile.mkdtemp(), "tone.wav")
    wavfile.write(path, FS, (stereo(sine(220, -12.0)) * 32767).astype(np.int16))
    report = analyze_file(path, target="trap_hiphop")
    assert report["target"] == "hiphop_rap" and report["style"]["name"] == "Hip-hop / rap"
    assert analyze_file(path, target="nope")["target"] is None

    # The page: it's told the old ids, the style list is grouped, and /api/fixes answers with the current id.
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):  # the web extra or httpx isn't installed
        return
    from mixcheck.web import server
    client = TestClient(server.app)
    info = client.get("/api/info").json()
    ids = [o["id"] for o in info["style_options"]]
    assert info["style_aliases"] == {"trap_hiphop": "hiphop_rap"}
    assert ids[0] == "hiphop_rap" and "hiphop_rap.drill" in ids and len(ids) == 39
    res = client.post("/api/fixes", json={"flags": [], "stage": "master", "target": "trap_hiphop", "measures": loud})
    body = res.json()
    assert res.status_code == 200 and body["target"] == "hiphop_rap" and body["style"]["name"] == "Hip-hop / rap"


def test_calibration_saved_under_the_old_id_still_applies():
    from mixcheck.style import calibration_path, targets
    try:
        _calibrate_to({"trap_hiphop": {"songs": 9, "lufs": [-8, -5]}})
        t = targets()
        assert t["hiphop_rap"]["lufs"] == (-8, -5) and t["hiphop_rap"]["source"]["label"] == "calibrated (9 songs)"
        assert t["hiphop_rap.drill"]["lufs"] == (-8, -5)  # its sub-genres follow it
        # If a file somehow holds both, the current id wins.
        _calibrate_to({"trap_hiphop": {"songs": 9, "lufs": [-8, -5]}, "hiphop_rap": {"songs": 10, "lufs": [-7, -4]}})
        assert targets()["hiphop_rap"]["lufs"] == (-7, -4) and targets()["hiphop_rap"]["songs"] == 10
    finally:
        calibration_path().unlink()


def test_subgenres_use_their_parents_ranges_until_calibrated():
    from mixcheck.style import SUBGENRES, TARGETS, calibration_path, options, style_flags, style_ids, style_match, targets
    # The table: 31 sub-genres, each under a real parent, keyed parent.sub, with a calibration priority.
    assert len(SUBGENRES) == 31 and len(style_ids()) == 39
    for sid, sub in SUBGENRES.items():
        assert sid == f"{sub['parent']}.{sub['slug']}" and sub["parent"] in TARGETS and sub["priority"] in (1, 2, 3)
    assert len({(s["parent"], s["name"]) for s in SUBGENRES.values()}) == 31
    assert all(sum(s["parent"] == p for s in SUBGENRES.values()) >= 2 for p in TARGETS)
    ids = style_ids()
    assert ids[:7] == ["hiphop_rap", "hiphop_rap.trap", "hiphop_rap.drill", "hiphop_rap.boom_bap",
                       "hiphop_rap.rage", "hiphop_rap.melodic", "edm"]
    opts = options()
    assert [o["id"] for o in opts] == ids
    assert opts[0]["parent"] is None and opts[0]["name"] == "Hip-hop / rap"
    assert opts[1]["parent"] == "hiphop_rap" and opts[1]["group"] == "Hip-hop / rap" and opts[1]["name"] == "Trap"

    # Nothing calibrated: every sub-genre has exactly its parent's numbers, and says so.
    t = targets()
    for sid, sub in SUBGENRES.items():
        assert all(t[sid][d] == t[sub["parent"]][d] for d in ("lufs", "plr", "lra"))
        assert t[sid]["source"]["kind"] == "inherited" and t[sid]["source"]["from"] == sub["parent"]
        assert "songs" not in t[sid]
    assert t["hiphop_rap"]["source"]["label"] == "built-in estimate"
    drill = t["hiphop_rap.drill"]
    assert drill["source"]["label"] == "inherited from Hip-hop / rap: built-in estimate"
    assert drill["source"]["from_name"] == "Hip-hop / rap" and drill["source"]["parent_label"] == "built-in estimate"
    assert t["hiphop_rap"]["source"]["from"] is None and t["hiphop_rap"]["source"]["parent_label"] is None
    assert drill["name"] == "Drill" and drill["full_name"] == "Drill (Hip-hop / rap)"

    # Flags come down too: lo-fi is dull on purpose, so its sub-genre isn't told it has no air.
    quiet_top = {"air_pct": 0.001}
    assert "no_air" not in {f["id"] for f in style_flags(quiet_top, "lofi.chillhop", "master")}
    assert "no_air" in {f["id"] for f in style_flags(quiet_top, "pop.dance_pop", "master")}

    tone = {"lows": [-24, -20], "low_mids": [-26, -22], "mids": [-17, -13], "presence": [-13, -9], "highs": [-8, -4]}
    try:
        _calibrate_to({"hiphop_rap": {"songs": 12, "lufs": [-8, -5], "plr": [5, 8], "lra": [3, 6], "tone": tone},
                       "hiphop_rap.drill": {"songs": 4, "lufs": [-12, -7]}})
        t = targets()
        assert t["hiphop_rap"]["source"]["label"] == "calibrated (12 songs)"
        # Trap has nothing of its own, so it follows the parent's calibration, tone included.
        trap = t["hiphop_rap.trap"]
        assert trap["lufs"] == (-8, -5) and trap["tone"] == t["hiphop_rap"]["tone"]
        assert trap["source"]["label"] == "inherited from Hip-hop / rap: calibrated (12 songs)"
        # Drill has its own loudness and takes the rest from the parent, which is unaffected.
        d = t["hiphop_rap.drill"]
        assert d["lufs"] == (-12, -7) and d["plr"] == (5, 8) and d["lra"] == (3, 6) and d["tone"] == t["hiphop_rap"]["tone"]
        assert d["songs"] == 4 and d["source"]["kind"] == "rough" and d["source"]["inherits"] == ["plr", "lra", "tone"]
        assert d["source"]["label"] == "rough (4 songs); punch, contrast, tone from Hip-hop / rap"
        assert t["hiphop_rap"]["lufs"] == (-8, -5) and t["hiphop_rap"]["songs"] == 12
        # What the user sees names the sub-genre and its parent, and where the numbers came from.
        sm = style_match({"lufs": -20.0, "plr": 6.0, "lra": 4.0}, "hiphop_rap.drill", "master")
        assert sm["name"] == "Drill (Hip-hop / rap)" and sm["source"]["kind"] == "rough"
        quiet = next(f for f in style_flags({"lufs": -20.0}, "hiphop_rap.drill", "master") if f["id"] == "quieter_than_target")
        assert "typical for Drill (Hip-hop / rap) is -12 to -7 LUFS" in quiet["message"]
        # Under 8 songs is rough; 8 or more is calibrated.
        _calibrate_to({"pop": {"songs": 7, "lufs": [-9, -7]}, "rock": {"songs": 8, "lufs": [-9, -7]},
                       "edm": {"songs": 1, "lufs": [-9, -7]}})
        t = targets()
        assert t["pop"]["source"]["label"] == "rough (7 songs)" and t["rock"]["source"]["label"] == "calibrated (8 songs)"
        assert t["edm"]["source"]["label"] == "rough (1 song)"
    finally:
        calibration_path().unlink()


def test_calibrate_finds_subgenre_folders():
    import tempfile
    from pathlib import Path
    from mixcheck.calibrate import collect, style_for
    # Qualified names mean a sub-genre; a bare name keeps meaning the whole parent, as it always did.
    assert style_for("hiphop_rap.drill") == style_for("Hip-hop / rap Drill") == "hiphop_rap.drill"
    assert style_for("trap") == style_for("rap") == style_for("trap_hiphop") == "hiphop_rap"
    assert style_for("jazz") == "acoustic" and style_for("classical") == "film" and style_for("Boom bap") is None

    root = Path(tempfile.mkdtemp())
    for rel in ("Hip-Hop/a.wav", "Hip-Hop/drill/b.wav", "Hip-Hop/drill/deeper/c.wav", "Hip-Hop/Boom Bap/d.wav",
                "Hip-Hop/other/e.wav", "EDM/house/f.wav"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")
    groups, unknown = collect(root)
    names = lambda sid: sorted(p.name for p in groups[sid])
    assert unknown == []
    # Songs in a sub-genre's folder calibrate the sub-genre, not the parent; everything else stays with the parent.
    assert names("hiphop_rap.drill") == ["b.wav", "c.wav"] and names("hiphop_rap.boom_bap") == ["d.wav"]
    assert names("hiphop_rap") == ["a.wav", "e.wav"]
    # A parent folder holding nothing but sub-genre folders doesn't also ask to calibrate the parent on no songs.
    assert names("edm.house") == ["f.wav"] and "edm" not in groups

    # --style takes the current id, a sub-genre, or an id the style used to have.
    folder = root / "refs"
    folder.mkdir()
    (folder / "x.flac").write_bytes(b"")
    groups, _ = collect(None, [f"trap_hiphop={folder}", f"hiphop_rap.rage={folder}"])
    assert sorted(groups) == ["hiphop_rap", "hiphop_rap.rage"]
    try:
        collect(None, [f"made_up={folder}"])
        assert False, "an unknown style should be refused"
    except ValueError as exc:
        assert "hiphop_rap.drill" in str(exc)


class _FakeClient:
    """Stands in for anthropic.Anthropic(): records the request and returns canned notes."""

    def __init__(self, notes, stop_reason="end_turn"):
        from types import SimpleNamespace as NS
        self.calls = []
        parsed = NS(model_dump=lambda: notes) if notes is not None else None
        response = NS(parsed_output=parsed, stop_reason=stop_reason, model="fake-model",
                      usage=NS(input_tokens=3000, output_tokens=600, cache_read_input_tokens=0))

        def parse(**kwargs):
            self.calls.append(kwargs)
            return response
        self.beta = NS(messages=NS(parse=parse))


def _clipped_report():
    import tempfile
    from scipy.io import wavfile
    path = os.path.join(tempfile.mkdtemp(), "secret-song-name.wav")
    wavfile.write(path, FS, (stereo(np.clip(sine(220, 2.0), -1, 1)) * 32767).astype(np.int16))
    return analyze_file(path, setup={"daw": "logic", "packages": ["fabfilter"]}, stage="master")


def test_notes_input_is_trimmed_and_pointable():
    import json
    from mixcheck.notes import notes_input
    report = _clipped_report()
    inp = notes_input(report)
    text = json.dumps(inp)
    assert "secret-song-name" not in text and "timeline" not in text  # no file name, no bulk
    assert inp["stage"] == "master" and inp["setup"] == "Logic Pro + FabFilter (Pro-L 2, Pro-Q, Pro-C 2)"
    ids = [f["id"] for f in inp["findings"]]
    assert ids == [f"F{i}" for i in range(1, len(report["flags"]) + 1)]
    clip = next(f for f in inp["findings"] if f["kind"] == "clipping")
    assert clip["steps"][0]["id"] == f"{clip['id']}.1" and clip["when"]
    assert len(text) < 12000  # a few thousand tokens at most


def test_notes_request_and_checks():
    from mixcheck.notes import FALLBACK_BETA, NotesUnavailable, format_notes, notes_input, write_notes
    report = _clipped_report()
    inp = notes_input(report)
    crit = [f["id"] for f in inp["findings"] if f["severity"] == "critical"]
    clip = next(f for f in inp["findings"] if f["kind"] == "clipping")
    notes = {
        "headline": "Clipping is the one thing to fix.", "summary": "It clips.",
        "priorities": [
            {"finding_ids": [clip["id"], "F99"], "title": "Stop the clipping", "why": "It crackles.",
             "step_ids": [clip["steps"][0]["id"], "F99.1"]},
            {"finding_ids": ["F42"], "title": "Invented", "why": "Not real.", "step_ids": []},
        ],
        "listen_for": ["The first chorus on earbuds."], "strengths": [],
    }
    client = _FakeClient(notes)
    result = write_notes(report, client=client, model_id="claude-opus-5")

    call = client.calls[0]
    assert call["model"] == "claude-opus-5" and call["thinking"] == {"type": "adaptive"}
    assert call["fallbacks"] == "default" and call["betas"] == [FALLBACK_BETA]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "secret-song-name" not in call["messages"][0]["content"]

    # Ids that don't exist are dropped and recorded; a priority with nothing real left goes.
    kinds = {(i["type"], i.get("id")) for i in result["issues"]}
    assert {("unknown_finding", "F99"), ("unknown_step", "F99.1"), ("unknown_finding", "F42")} <= kinds
    assert [p["title"] for p in result["notes"]["priorities"]] == ["Stop the clipping"]
    assert result["notes"]["priorities"][0]["finding_ids"] == [clip["id"]]
    assert {("missed_critical", c) for c in crit if c != clip["id"]} <= kinds
    assert clip["steps"][0]["text"] in format_notes(result)

    try:
        write_notes(report, client=_FakeClient(None, stop_reason="refusal"))
        raise AssertionError("a refusal should not produce notes")
    except NotesUnavailable:
        pass


def test_notes_endpoint():
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):  # the web extra or httpx isn't installed
        return
    from mixcheck import notes
    from mixcheck.web import server
    report = _clipped_report()
    client = TestClient(server.app)
    real = notes.write_notes
    try:
        notes.write_notes = lambda r: (_ for _ in ()).throw(notes.NotesUnavailable("No valid Anthropic API key."))
        res = client.post("/api/notes", json={"report": report})
        assert res.status_code == 503 and "API key" in res.json()["detail"]

        inp = notes.notes_input(report)
        canned = {"headline": "h", "summary": "s", "listen_for": [], "strengths": [],
                  "priorities": [{"finding_ids": ["F1"], "title": "t", "why": "w", "step_ids": ["F1.1"]}]}
        notes.write_notes = lambda r: real(r, client=_FakeClient(canned))
        data = client.post("/api/notes", json={"report": report}).json()
        assert data["steps"]["F1.1"] == inp["findings"][0]["steps"][0]["text"]
        assert data["findings"]["F1"] == report["flags"][0]["id"] and "input" not in data
        assert client.post("/api/notes", json={"report": {"flags": []}}).status_code == 422
    finally:
        notes.write_notes = real


def test_analyze_streams_progress():
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):  # the web extra or httpx isn't installed
        return
    import io
    import json
    from scipy.io import wavfile
    from mixcheck.analyze import PROGRESS_STAGES
    from mixcheck.web import server
    buf = io.BytesIO()
    wavfile.write(buf, FS, (stereo(sine(220, -12, seconds=4)) * 32767).astype(np.int16))
    client = TestClient(server.app)
    res = client.post("/api/analyze", data={"progress": "1"},
                      files={"file": ("my song.wav", buf.getvalue(), "audio/wav")})
    events = [json.loads(line) for line in res.text.splitlines()]
    assert [e["stage"] for e in events[:-1]] == list(PROGRESS_STAGES)
    assert events[-1]["report"]["file"]["name"] == "my song.wav"
    # A file that isn't audio ends the stream with an error the page can show.
    bad = client.post("/api/analyze", data={"progress": "1"}, files={"file": ("x.wav", b"not audio", "audio/wav")})
    error = json.loads(bad.text.splitlines()[-1])["error"]
    import tempfile
    temp = tempfile.gettempdir()  # the real temp folder on this system, not a guess like /tmp
    assert "couldn't be read as audio" in error and temp not in error
    assert temp not in client.post("/api/analyze", files={"file": ("x.wav", b"not audio", "audio/wav")}).json()["detail"]
    # Without progress=1, the plain JSON report as before.
    assert "flags" in client.post("/api/analyze", files={"file": ("a.wav", buf.getvalue(), "audio/wav")}).json()


def test_anonymize_removes_titles():
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location("anonymize", os.path.join(os.path.dirname(__file__), "..", "evals", "anonymize.py"))
    anon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(anon)
    report = _clipped_report()
    report["reference"] = {"references": [{"name": "Somebody - Hit Song.mp3"}]}
    titles = anon.scrub(report, "song07")
    text = json.dumps(report)
    assert "secret-song-name" not in text and "Hit Song" not in text
    assert report["file"]["name"] == report["profile"]["name"] == "song07.wav"
    assert titles == ["secret-song-name.wav", "Somebody - Hit Song.mp3"]


def _graded(writer, report, setup=None):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from evals.fakes import FakeClient
    from evals.graders import grade
    from mixcheck.notes import write_notes
    result = write_notes(report, client=FakeClient(writer))
    return grade(result, result["input"], setup or report["setup"])


def test_eval_checks_pass_oracle_and_fail_null_and_sloppy():
    from evals.scenarios import rejudge
    master = _clipped_report()
    mix = rejudge(master, stage="mix")

    for report in (master, mix):
        scores, details = _graded("oracle", report)
        assert all(v == 1.0 for v in scores.values() if v is not None), details

    scores, details = _graded("null", master)
    assert scores["covers_critical"] == 0.0 and scores["ids_valid"] == 1.0

    scores, details = _graded("sloppy", mix)
    assert scores["ids_valid"] == 0.0 and "F99" in details["ids_valid"]
    assert scores["numbers_grounded"] == 0.0 and "3.7 LUFS" in details["numbers_grounded"]
    assert scores["tools_owned"] == 0.0 and "Ozone" in details["tools_owned"]
    assert scores["stage_appropriate"] == 0.0
    # An invented priority on a clean report counts, even though check() hides it from the user.
    from evals.graders import no_invented_problems
    clean = {"findings": []}
    dropped = [{"type": "priority_dropped", "title": "Invented"}]
    assert no_invented_problems({"priorities": []}, clean, dropped)[0] == 0.0
    assert no_invented_problems({"priorities": []}, clean, [])[0] == 1.0
    # On a master, pushing loudness isn't a stage error.
    assert _graded("sloppy", master)[0]["stage_appropriate"] is None


def test_eval_scenarios_rejudge_like_the_page():
    from evals.scenarios import cases_for, rejudge
    report = _clipped_report()
    mix = rejudge(report, stage="mix", setup={"daw": "ableton", "packages": []})
    assert mix["stage"]["value"] == "mix" and mix["setup"]["label"] == "Ableton Live"
    # Same finding, re-rated and re-fixed for a mix: gain staging, not a limiter.
    tp = next(f for f in mix["flags"] if f["id"] == "true_peak_over")
    assert "Utility" in tp["fix"]["steps"][0]["text"]
    ids = [c[0] for c in cases_for("song01", report)]
    assert ids == ["song01__as_recorded", "song01__other_stage", "song01__trap_target"]
    # A report whose vocal was checked keeps the label the page showed; one that wasn't can't earn it.
    report["flags"] = [f for f in report["flags"] if f["id"] not in ("true_peak_over", "true_peak_hot", "clipping")]
    checked = rejudge({**report, "vocal": {"found": True}}, stage="mix")
    unchecked = rejudge({**report, "vocal": None}, stage="mix")
    assert checked["score"]["vocal_checked"] and not unchecked["score"]["vocal_checked"]


def test_eval_number_check_is_fair_to_rounding_but_not_to_invention():
    from evals.graders import numbers_grounded
    inp = {"measurements": {"integrated_loudness_lufs": -14.23, "true_peak_dbtp": -0.3},
           "findings": [{"id": "F1", "measured": "Peaks at 0:42 and 1:05.", "steps": [], "other_options": []}]}
    notes = lambda text: {"headline": text, "summary": "", "priorities": [], "listen_for": [], "strengths": []}
    assert numbers_grounded(notes("It sits at −14.2 LUFS, about −14 LUFS."), inp)[0] == 1.0
    assert numbers_grounded(notes("True peak is 0.3 dB under full scale."), inp)[0] == 1.0
    assert numbers_grounded(notes("It sits at −12.5 LUFS."), inp)[0] == 0.0
    assert numbers_grounded(notes("−14.2 dB"), inp)[0] == 0.0  # right number, wrong quantity
    assert numbers_grounded(notes("Check 0:42, then 2:10."), inp)[0] == 0.0
    assert numbers_grounded(notes("No numbers."), inp)[0] is None
    # Found in the first real pilot: "808s" (the drum machine) was read as 808 seconds.
    assert numbers_grounded(notes("Let the 808s carry the low end."), inp)[0] is None
    assert numbers_grounded(notes("Trim the last 30 s."), inp)[0] == 0.0
    # Found in the baseline: a 0:40 song is "the whole 40 seconds"; times in m:ss count as seconds too.
    assert numbers_grounded(notes("Check the 42 seconds mark."), inp)[0] == 1.0
    assert numbers_grounded(notes("Check the 50 seconds mark."), inp)[0] == 0.0


def _fake_bundle(folder, name, suffix, bundle_id, app=False):
    import plistlib
    path = folder / (name + suffix)
    (path / "Contents").mkdir(parents=True)
    with open(path / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleShortVersionString": "1.0"}, fh)


def test_scan_maps_installed_plugins_and_daws():
    import tempfile
    from pathlib import Path
    from mixcheck import scan
    tmp_path = Path(tempfile.mkdtemp())
    plugins, apps = tmp_path / "plugins", tmp_path / "apps"
    plugins.mkdir(); apps.mkdir()
    _fake_bundle(plugins, "iZOzone8 Maximizer", ".vst3", "com.izotope.audioplugins")
    _fake_bundle(plugins, "iZOzone8 Insight", ".aaxplugin", "com.izotope.audioplugins")
    _fake_bundle(plugins, "Neutron 2 Compressor", ".vst3", "com.izotope.audioplugins")
    _fake_bundle(plugins, "WaveShell1-AU 16.2", ".component", "com.WavesAudio.WaveShell1-AU")
    _fake_bundle(plugins, "UAD API 2500", ".component", "com.uaudio.api2500")
    _fake_bundle(apps, "Pro Tools", ".app", "com.avid.ProTools")
    _fake_bundle(apps, "FL Studio 2026", ".app", "com.image-line.flstudio")
    _fake_bundle(apps, "Notes", ".app", "com.apple.Notes")
    old = (scan.PLUGIN_FOLDERS, scan.APP_FOLDERS, scan.PLATFORM)
    scan.PLUGIN_FOLDERS, scan.APP_FOLDERS, scan.PLATFORM = [plugins], [apps], "mac"
    try:
        r = scan.scan_this_computer()
    finally:
        scan.PLUGIN_FOLDERS, scan.APP_FOLDERS, scan.PLATFORM = old
    assert set(r["packages"]) == {"izotope_ozone", "izotope_insight"}
    assert r["packages"]["izotope_ozone"]["count"] == 1 and r["packages"]["izotope_insight"]["count"] == 1
    assert r["waves_installed"] is True
    assert [d["id"] for d in r["daws"]] == ["pro_tools", "fl_studio"]  # Pro Tools pre-selected
    assert "com.uaudio" in r["other_vendors"] and "com.izotope" in r["other_vendors"]


def test_scan_never_reports_plugins_it_cannot_identify():
    from mixcheck.scan import _package_for, _vendor
    assert _package_for("Waves L2", "com.WavesAudio.WaveShell1-AAX") == "waves"  # shell only, never a fake Waves plugin
    assert _package_for("Serum", "com.xfer.serum") is None
    assert _vendor("jp.co.roland.TR-808") == "jp.co.roland"
    assert _vendor("com.arturia.component.Pigments") == "com.arturia"


def test_waves_tiers_and_the_old_waves_essential_id():
    from mixcheck.catalog import DAWS, LEGACY_PACKAGES, PACKAGES, TOOLS, WAVES_TIERS, expand_packages, options, owned_tools
    from mixcheck.remediation import attach_fixes, describe_setup, normalize_setup
    waves = {k for k, v in PACKAGES.items() if v["group"] == "Waves"}
    ess, ult = set(WAVES_TIERS["essential"]["plugins"]), set(WAVES_TIERS["ultimate"]["plugins"])
    assert ess <= waves and ult <= waves and ess <= ult  # Ultimate has everything Essential has
    assert waves - ult == {"waves_s1_shuffler"}  # not in either bundle on Waves' own list, so it's chosen alone
    assert {t["id"] for t in options()["waves_tiers"]} == {"essential", "ultimate"}
    # No tool belongs to a DAW or package that doesn't exist, so every tool can be owned from the setup screen.
    for tid, tool in TOOLS.items():
        assert set(tool["in"]) <= set(DAWS) | set(PACKAGES), f"{tid} is in an unknown package"
    # Older saved setups, scripts and eval cases name "waves_essential"; it still means the same four plugins.
    assert expand_packages(["waves_essential", "waves_l2", "nonsense"]) == LEGACY_PACKAGES["waves_essential"]
    setup = normalize_setup({"daw": "pro_tools", "packages": ["waves_essential", "fabfilter"]})
    assert setup["packages"] == LEGACY_PACKAGES["waves_essential"] + ["fabfilter"]
    assert describe_setup(setup) == "Pro Tools + Waves (L2, F6, Renaissance EQ, Renaissance Compressor) + FabFilter (Pro-L 2, Pro-Q, Pro-C 2)"
    flags = [{"id": "true_peak_over", "severity": "critical", "message": "", "value": 1.0}]
    names = {s["tool"] for s in attach_fixes(flags, {"daw": "pro_tools", "packages": ["waves_essential"]}, "master")[0]["fix"]["more"]}
    assert "Waves L2" in names
    # Owning only L2 gives the L2 and none of the other Waves plugins.
    assert {t["name"] for t in owned_tools({"daw": "other", "packages": ["waves_l2"]}).values()} == {"Waves L2"}


def _touch(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_finds_windows_daws_and_plugins():
    import tempfile
    from pathlib import Path
    from mixcheck import scan
    root = Path(tempfile.mkdtemp())
    pf, common, data, local = root / "Program Files", root / "Common Files", root / "ProgramData", root / "Local"
    _touch(pf / "Avid" / "Pro Tools" / "ProTools.exe")
    _touch(pf / "Image-Line" / "FL Studio 2026" / "FL64.exe")
    _touch(data / "Ableton" / "Live 12 Suite" / "Program" / "Ableton Live 12 Suite.exe")
    _touch(pf / "Avid" / "Other App" / "other.exe")  # not a DAW
    _touch(common / "VST3" / "iZotope" / "Ozone 9.vst3")                       # vendor sub-folder, single file
    _touch(common / "VST3" / "iZotope" / "Insight 2.vst3")
    _touch(common / "VST3" / "Waves 16.0" / "WaveShell1-VST3 16.0_x64.vst3")   # a folder name with a dot
    _touch(common / "VST3" / "Solo Synth.vst3")                                 # no vendor folder: no vendor to report
    _touch(common / "VST3" / "FabFilter" / "FabFilter Pro-L 2.vst3" / "Contents" / "x86_64-win" / "FabFilter Pro-L 2.vst3")
    _touch(common / "Avid" / "Audio" / "Plug-Ins" / "WaveShell1-AAX 16.0.aaxplugin" / "Contents" / "x64" / "WaveShell1-AAX 16.0.aaxplugin")
    _touch(pf / "VSTPlugins" / "Old Delay.dll")
    _touch(pf / "VSTPlugins" / "Insight Other Company.dll")                     # "insight" without iZotope is not Insight
    names = ["ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "CommonProgramFiles", "CommonProgramFiles(x86)",
             "CommonProgramW6432", "ProgramData", "LOCALAPPDATA"]
    saved = {n: os.environ.get(n) for n in names}
    old_platform = scan.PLATFORM
    try:
        for n in names:
            os.environ.pop(n, None)
        os.environ.update({"ProgramFiles": str(pf), "CommonProgramFiles": str(common),
                           "ProgramData": str(data), "LOCALAPPDATA": str(local)})
        scan.PLATFORM = "windows"
        r = scan.scan_this_computer()
    finally:
        scan.PLATFORM = old_platform
        for n, v in saved.items():
            os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v)
    assert r["platform"] == "windows" and r["supported"] is True
    assert [d["id"] for d in r["daws"]] == ["pro_tools", "ableton", "fl_studio"]  # Pro Tools pre-selected first
    assert {d["id"]: d["app"] for d in r["daws"]}["ableton"] == "Ableton Live 12 Suite"
    assert set(r["packages"]) == {"izotope_ozone", "izotope_insight"}
    assert r["waves_installed"] is True
    assert "fabfilter" in r["other_vendors"] and "vst3" not in r["other_vendors"]  # a vendor folder, not the plugin folder


def test_scan_on_other_systems_says_it_is_unsupported():
    from mixcheck import scan
    old = scan.PLATFORM
    scan.PLATFORM = "other"
    try:
        r = scan.scan_this_computer()
    finally:
        scan.PLATFORM = old
    assert r["supported"] is False and r["daws"] == [] and r["packages"] == {} and r["waves_installed"] is False


def test_console_output_survives_a_legacy_code_page():
    import subprocess
    code = "from mixcheck.util import utf8_console; utf8_console(); print('Out Ceiling to \u22121.0 dB \u203a Bounce')"
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}  # what a Windows redirect can default to
    root = os.path.join(os.path.dirname(__file__), "..")
    env["PYTHONPATH"] = root
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, check=True).stdout
    assert out.decode("utf-8").strip() == "Out Ceiling to \u22121.0 dB \u203a Bounce"
    # Without the helper the same print fails on that code page, which is what the helper is for.
    bare = subprocess.run([sys.executable, "-c", "print('\u22121.0')"], env=env, capture_output=True)
    assert bare.returncode != 0 and b"UnicodeEncodeError" in bare.stderr


def test_every_text_file_is_opened_with_an_explicit_encoding():
    # Windows reads and writes text in a legacy code page unless told otherwise, and this app's text
    # has characters like the minus sign and angle quotes. Fails the moment new code forgets.
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    problems = []
    for path in sorted(list((root / "mixcheck").rglob("*.py")) + list((root / "evals").rglob("*.py"))):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
            is_open = (name == "open" and not owner) or (name == "fdopen" and owner == "os")
            if not (is_open or name in ("read_text", "write_text")):
                continue
            if any(k.arg == "encoding" for k in node.keywords):
                continue
            if is_open and any(isinstance(a, ast.Constant) and isinstance(a.value, str) and "b" in a.value for a in node.args[1:2]):
                continue  # binary
            problems.append(f"{path.relative_to(root)}:{node.lineno} {name}(...)")
    assert not problems, "text opened without encoding=: " + ", ".join(problems)


def test_info_says_which_system_this_is():
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):  # the web extra or httpx isn't installed
        return
    from mixcheck.web import server
    info = TestClient(server.app).get("/api/info").json()["platform"]
    assert info["id"] in ("mac", "windows", "other") and info["noun"] and info["launcher"]


class _TempHome:
    """A fresh MIXCHECK_HOME for one test, so ratings from another test can't leak in."""

    def __enter__(self):
        import tempfile
        self.old = os.environ.get("MIXCHECK_HOME")
        os.environ["MIXCHECK_HOME"] = tempfile.mkdtemp()
        return self

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("MIXCHECK_HOME", None)
        else:
            os.environ["MIXCHECK_HOME"] = self.old


def _written_notes(report=None):
    """(result of write_notes, report) with canned notes; the result is what the server remembers."""
    from mixcheck.notes import write_notes
    report = report or _clipped_report()
    canned = {"headline": "h", "summary": "s", "listen_for": [], "strengths": [],
              "priorities": [{"finding_ids": ["F1"], "title": "t", "why": "w", "step_ids": ["F1.1"]}]}
    return write_notes(report, client=_FakeClient(canned)), report


def test_feedback_ratings_are_saved_changed_and_cleared():
    from mixcheck import feedback
    with _TempHome():
        result, _ = _written_notes()
        nid = feedback.remember(result)
        assert feedback.stats() == {"count": 0, "up": 0, "down": 0}
        assert feedback.rate(nid, "up", ["too_long"])["reasons"] == []  # reasons only go with a thumbs down
        assert feedback.stats() == {"count": 1, "up": 1, "down": 0}
        out = feedback.rate(nid, "down", ["made_something_up", "too_long", "too_long"])
        assert out["rating"] == "down" and out["reasons"] == ["made_something_up", "too_long"]
        assert feedback.stats() == {"count": 1, "up": 0, "down": 1}  # a changed rating replaces the old one
        assert feedback.rate(nid, None)["count"] == 0  # clearing takes it back
        for bad in (lambda: feedback.rate(nid, "sideways"), lambda: feedback.rate(nid, "down", ["rude"])):
            try:
                bad()
                raise AssertionError("a bad rating was saved")
            except ValueError:
                pass
        try:
            feedback.rate("not-a-real-id", "up")
            raise AssertionError("notes that were never written were rated")
        except feedback.Gone:
            pass
        # After a restart the page can still change a rating it already made.
        feedback.rate(nid, "up")
        feedback._recent.clear()
        assert feedback.rate(nid, "down", ["generic"])["reasons"] == ["generic"]
        assert feedback.stats()["down"] == 1


def test_feedback_export_has_no_audio_or_file_name():
    import json
    from mixcheck import feedback
    with _TempHome():
        result, report = _written_notes()
        assert report["file"]["name"] == "secret-song-name.wav"
        nid = feedback.remember(result)
        feedback.rate(nid, "down", ["made_something_up", "wrong_stage"])
        name, text, count = feedback.export("Sam K!")
        assert name == "feedback-samk.jsonl" and count == 1
        assert "secret-song-name" not in text and nid not in text and '"at"' not in text
        row = json.loads(text)
        assert row["rating"] == "down" and row["prompt_version"] and row["input"]["findings"]
        assert row["labels"] == {"faithful": 0.0, "stage_appropriate": 0.0}  # only what the person said
        assert len(row["day"]) == 10
        # A thumbs up labels no criterion; nothing rated means nothing to export.
        feedback.rate(nid, "up")
        assert json.loads(feedback.export()[1])["labels"] == {}
        feedback.rate(nid, None)
        assert feedback.export()[2] == 0


def test_feedback_reasons_match_the_judges_criteria():
    from evals.judge import CRITERIA
    from mixcheck import feedback
    # Every criterion can be labelled from the page, and no reason points at one that doesn't exist.
    assert sorted(c for _, c in feedback.REASONS.values()) == sorted(CRITERIA)


def test_feedback_endpoints():
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # the web extra isn't installed
        return
    from mixcheck import notes
    from mixcheck.web import server
    client = TestClient(server.app)
    real = notes.write_notes
    with _TempHome():
        try:
            import copy
            canned, report = _written_notes()  # built before patching, so it can't call the stand-in
            notes.write_notes = lambda r: copy.deepcopy(canned)  # the server removes "input" from what it gets
            reasons = client.get("/api/info").json()["notes_feedback"]["reasons"]
            assert {r["id"] for r in reasons} >= {"made_something_up", "too_long"}
            assert client.get("/api/notes/feedback/export").status_code == 404  # nothing yet
            data = client.post("/api/notes", json={"report": report}).json()
            nid = data["notes_id"]
            assert nid and "input" not in data
            ok = client.post("/api/notes/feedback", json={"notes_id": nid, "rating": "down", "reasons": ["too_long"]})
            assert ok.status_code == 200 and ok.json()["down"] == 1
            assert client.get("/api/info").json()["notes_feedback"]["count"] == 1
            assert client.post("/api/notes/feedback", json={"notes_id": nid, "rating": "meh"}).status_code == 422
            assert client.post("/api/notes/feedback", json={"notes_id": nid, "rating": "up", "reasons": ["rude"]}).status_code == 422
            assert client.post("/api/notes/feedback", json={"notes_id": "nope", "rating": "up"}).status_code == 404
            export = client.get("/api/notes/feedback/export", params={"name": "sam"})
            assert export.status_code == 200
            assert 'filename="feedback-sam.jsonl"' in export.headers["content-disposition"]
            assert "secret-song-name" not in export.text
        finally:
            notes.write_notes = real


def test_feedback_summary_reads_exports():
    import contextlib
    import io
    from pathlib import Path
    from types import SimpleNamespace as NS
    from evals import notes_eval
    from mixcheck import feedback, notes
    with _TempHome():
        result, _ = _written_notes()
        for rating, why in (("up", []), ("down", ["too_long"]), ("down", ["too_long", "generic"])):
            feedback.rate(feedback.remember(result), rating, why)
        _, text, _ = feedback.export("sam")
        path = Path(os.environ["MIXCHECK_HOME"]) / "feedback-sam.jsonl"
        path.write_text(text, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            notes_eval.cmd_feedback(NS(files=[str(path)], local=False))
        summary = out.getvalue()
        assert "3 rating(s)" in summary and notes.PROMPT_VERSION in summary and "33%" in summary
        assert "too_long 2" in summary and "generic 1" in summary


# ---------------------------------------------------------------- vocal checks (vocal.py, separate.py)

VFS = 44100  # the rate the separation model works at


def _voice(levels_db, rumble=False, mud_db=None, sib_db=None, thin=False, seconds=24, seed=1):
    """A stand-in vocal: half-second 'words' with a harmonic tone, one level per word (cycled)."""
    from scipy.signal import butter, sosfilt
    from scipy.signal.windows import tukey
    rng = np.random.default_rng(seed)
    n = int(seconds * VFS)
    t = np.arange(n) / VFS
    base = sum(np.sin(2 * np.pi * k * 160 * t + rng.uniform(0, 6.28)) / k ** 0.75 for k in range(1, 30))
    if thin:
        base = sosfilt(butter(4, 300, "high", fs=VFS, output="sos"), base)
    mud = sum(np.sin(2 * np.pi * f * t) for f in (250, 320, 400)) / 3
    hiss = sosfilt(butter(4, [5000, 9000], "band", fs=VFS, output="sos"), rng.standard_normal(n))
    out, pos, i = np.zeros(n), 0.0, 0
    while pos + 0.5 < seconds:
        a, b = int(pos * VFS), int((pos + 0.5) * VFS)
        seg = base[a:b] / (np.sqrt(np.mean(base[a:b] ** 2)) + 1e-9)
        if mud_db is not None:
            seg = seg + mud[a:b] * 10 ** (mud_db / 20)
        if rumble:
            seg = seg + 0.5 * np.sin(2 * np.pi * 45 * t[a:b])
        if sib_db is not None:
            seg = seg + hiss[a:b] / np.sqrt(np.mean(hiss[a:b] ** 2)) * 10 ** (sib_db / 20)
        seg = seg * tukey(b - a, 0.3)  # flat-topped, like a sustained word
        out[a:b] += seg / (np.sqrt(np.mean(seg ** 2)) + 1e-9) * 10 ** (levels_db[i % len(levels_db)] / 20)
        pos, i = pos + 0.8, i + 1
    return np.column_stack([out, out])


def _beat(db, seconds=24):
    rng = np.random.default_rng(2)
    n = int(seconds * VFS)
    t = np.arange(n) / VFS
    b = 0.5 * np.sin(2 * np.pi * 55 * t) + 0.2 * np.sin(2 * np.pi * 110 * t) + 0.05 * rng.standard_normal(n)
    return stereo(b / np.sqrt(np.mean(b ** 2)) * 10 ** (db / 20))


EVEN = [-18, -17, -18, -19, -17, -18]


def _vocal_ids(vocal, beat_db=-20):
    from mixcheck.vocal import measure_vocal, vocal_flags
    return {f["id"]: f["severity"] for f in vocal_flags(measure_vocal(vocal, _beat(beat_db), VFS))}


def test_vocal_dynamics_tell_a_raw_vocal_from_a_compressed_one():
    raw = _vocal_ids(_voice([-30, -14, -22, -10, -26, -12]))
    assert raw.get("vocal_uncompressed") == "warning"
    assert "vocal_uncompressed" not in _vocal_ids(_voice(EVEN))  # an even vocal isn't flagged


def test_vocal_tone_findings():
    assert _vocal_ids(_voice(EVEN, thin=True)).get("vocal_thin") == "warning"
    assert _vocal_ids(_voice(EVEN, rumble=True)).get("vocal_rumble") == "warning"
    assert _vocal_ids(_voice(EVEN, mud_db=14)).get("vocal_muddy") == "warning"
    assert _vocal_ids(_voice(EVEN, sib_db=4)).get("vocal_sibilant") == "warning"
    # A plain, evenly-leveled vocal trips none of them.
    assert _vocal_ids(_voice(EVEN)) == {}


def test_vocal_level_against_the_beat():
    assert _vocal_ids(_voice(EVEN), beat_db=-6).get("vocal_buried") == "warning"
    assert _vocal_ids(_voice(EVEN), beat_db=-40).get("vocal_dominant") == "warning"


def test_no_vocal_means_no_verdict_on_it():
    from mixcheck.vocal import measure_vocal, vocal_flags
    quiet = measure_vocal(np.zeros((VFS * 10, 2)), _beat(-20, 10), VFS)
    assert quiet["found"] is False and "instrumental" in quiet["reason"]
    assert vocal_flags(quiet) == []
    assert measure_vocal(np.zeros((100, 2)), np.zeros((100, 2)), VFS)["found"] is False  # too short


def _with_fake_split(vocal, instrumental, work):
    from mixcheck import separate
    real = separate.separate_vocals
    separate.separate_vocals = lambda x, fs: (vocal, instrumental, VFS)
    try:
        return work()
    finally:
        separate.separate_vocals = real


def _clean_mix_file():
    import tempfile
    from scipy.io import wavfile
    path = os.path.join(tempfile.mkdtemp(), "mix.wav")
    wavfile.write(path, FS, (stereo(sine(220, -18)) * 32767).astype(np.int16))
    return path


def test_split_vocal_adds_estimated_findings_and_changes_the_verdict():
    path = _clean_mix_file()
    unchecked = analyze_file(path, stage="mix")
    assert unchecked["vocal"] is None and unchecked["score"]["vocal_checked"] is False
    assert unchecked["score"]["label"] == "No technical errors found"  # nothing has judged the vocal
    assert all(a["id"] != "vocal" for a in unchecked["score"]["areas"])

    raw, beat = _voice([-30, -14, -22, -10, -26, -12]), _beat(-20)
    stages = []
    checked = _with_fake_split(raw, beat, lambda: analyze_file(path, stage="mix", split_vocal=True, progress=stages.append))
    from mixcheck.analyze import PROGRESS_STAGES
    assert stages == [*PROGRESS_STAGES[:5], "vocal", *PROGRESS_STAGES[5:]]
    v = checked["vocal"]
    assert v["found"] and v["source"] == {"method": "split", "model": "htdemucs", "estimated": True}
    assert "more accurate" in v["disclaimer"]
    flag = next(f for f in checked["flags"] if f["id"] == "vocal_uncompressed")
    assert flag["estimated"] and flag["fix"]["steps"]  # steps written for the user's tools
    assert checked["score"]["vocal_checked"] and any(a["id"] == "vocal" and a["lost"] > 0 for a in checked["score"]["areas"])
    assert checked["score"]["value"] < unchecked["score"]["value"]

    # A well-made vocal that was checked earns the label.
    good = _with_fake_split(_voice(EVEN), beat, lambda: analyze_file(path, stage="mix", split_vocal=True))
    assert good["score"]["label"] == "Ready for mastering" and not any(f["id"].startswith("vocal_") for f in good["flags"])


def test_split_vocal_when_it_cannot_run_still_gives_the_report():
    from mixcheck import separate
    real = separate.separate_vocals

    def fail(x, fs):
        raise separate.SeparationUnavailable("Vocal splitting needs the optional packages.")
    separate.separate_vocals = fail
    try:
        report = analyze_file(_clean_mix_file(), stage="mix", split_vocal=True)
    finally:
        separate.separate_vocals = real
    assert report["vocal"]["found"] is False and report["vocal"]["unavailable"] is True
    assert not any(f["id"].startswith("vocal_") for f in report["flags"])
    assert report["score"]["vocal_checked"] is False


def test_separation_availability_is_honest():
    import importlib.util
    from mixcheck import separate
    real_find, real_env = importlib.util.find_spec, os.environ.get("MIXCHECK_SEPARATION")
    try:
        importlib.util.find_spec = lambda name, *a, **k: None if name in ("torch", "demucs") else real_find(name, *a, **k)
        ok, why = separate.available()
        assert not ok and "optional packages" in why
        try:
            separate.separate_vocals(stereo(sine(220, -18, seconds=1)), FS)
            assert False, "should refuse without the packages"
        except separate.SeparationUnavailable:
            pass
        importlib.util.find_spec = real_find
        os.environ["MIXCHECK_SEPARATION"] = "off"
        assert not separate.available()[0]
    finally:
        importlib.util.find_spec = real_find
        if real_env is None:
            os.environ.pop("MIXCHECK_SEPARATION", None)
        else:
            os.environ["MIXCHECK_SEPARATION"] = real_env


def test_notes_see_the_vocal_numbers_only_when_they_exist():
    from mixcheck.notes import notes_input
    path = _clean_mix_file()
    assert not any(k.startswith("vocal_") for k in notes_input(analyze_file(path, stage="mix"))["measurements"])
    report = _with_fake_split(_voice([-30, -14, -22, -10, -26, -12]), _beat(-20),
                              lambda: analyze_file(path, stage="mix", split_vocal=True))
    m = notes_input(report)["measurements"]
    assert m["vocal_range_db"] == report["vocal"]["range_db"] and "vocal_to_beat_db" in m
    assert any(f["kind"] == "vocal_uncompressed" for f in notes_input(report)["findings"])


def test_web_split_vocal_option():
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # the web extra isn't installed
        return
    import io
    import json
    from scipy.io import wavfile
    from mixcheck.web import server
    client = TestClient(server.app)
    sep = client.get("/api/info").json()["separation"]
    assert set(sep) == {"available", "reason"}
    buf = io.BytesIO()
    wavfile.write(buf, FS, (stereo(sine(220, -18, seconds=4)) * 32767).astype(np.int16))
    post = lambda **data: client.post("/api/analyze", data={"progress": "1", **data},
                                      files={"file": ("a.wav", buf.getvalue(), "audio/wav")})
    # Without the option, nothing changes: no vocal stage, no vocal block.
    plain = [json.loads(line) for line in post().text.splitlines()]
    assert "vocal" not in [e.get("stage") for e in plain] and plain[-1]["report"]["vocal"] is None
    events = _with_fake_split(_voice([-30, -14, -22, -10, -26, -12]), _beat(-20),
                              lambda: [json.loads(line) for line in post(split_vocal="1").text.splitlines()])
    assert "vocal" in [e.get("stage") for e in events] and events[-1]["report"]["vocal"]["found"]
    # Fixes rebuilt for a new stage keep the vocal in the score.
    report = events[-1]["report"]
    fixed = client.post("/api/fixes", json={"flags": report["flags"], "stage": "mix", "measures": report["measures"],
                                            "vocal": True}).json()
    assert fixed["score"]["vocal_checked"] and any(f["id"] == "vocal_uncompressed" for f in fixed["flags"])


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS  {name}")
    print(f"\nAll {len(tests)} tests passed.")
