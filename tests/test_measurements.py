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


def _floor_ids():
    """Every finding build_flags can raise: the floors."""
    import inspect
    import re
    from mixcheck import analyze
    return set(re.findall(r'flag\("(\w+)"', inspect.getsource(analyze.build_flags)))


def _finding_ids():
    """The floors plus the playbook keys observations use: every key that has fix steps."""
    from mixcheck.observations import PLAYBOOK
    return _floor_ids() | set(PLAYBOOK.values())


def _observations(m, target, stage, reference=None, vocal=None):
    from mixcheck.observations import build_observations
    from mixcheck.style import canonical, style_match
    return build_observations(m, stage, canonical(target), style_match(m, target, stage), reference, vocal)


def test_floors_are_the_only_findings():
    from mixcheck.analyze import FLOOR_IDS
    assert FLOOR_IDS == _floor_ids()  # the named set and the code that raises findings agree
    path = _clean_mix_file()
    report = analyze_file(path, stage="master", target="hiphop_rap")
    assert {f["id"] for f in report["flags"]} <= FLOOR_IDS
    assert report["observations"] and all("severity" not in o for o in report["observations"])


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
    typical = {"true_peak_over": 0.5, "true_peak_hot": -0.5, "clipping": 3, "negative_correlation": -0.3,
               "mono_loss": 4.0, "wide_low_end": 0.2, "imbalance": 2.0, "dc_offset": -40.0, "long_head": 3.0,
               "long_tail": 6.0, "abrupt_end": -20.0, "phase_section": None}
    for fid in _floor_ids() - {"silent"}:
        flag = {"id": fid, "severity": "warning", "value": typical[fid]}
        assert max(_points(flag, st)[1] for st in ("mix", "master")) > 0, f"{fid} is never scored"


def test_observations_are_complete_and_every_one_outside_its_range_has_steps():
    from mixcheck.observations import CHAIN, PLAYBOOK, STAGE_OF
    assert set(CHAIN) == set(range(1, 11)) and set(STAGE_OF.values()) <= set(CHAIN)
    assert {dim for (_, dim, _) in PLAYBOOK} <= set(STAGE_OF)
    report = analyze_file(_clean_mix_file(), stage="master", target="acoustic")
    outside = [o for o in report["observations"] if o["status"] != "in"]
    assert outside, "the test file should sit outside the acoustic ranges"
    for o in outside:
        assert o["playbook"] and o["fix"]["steps"], o["id"]  # steps written for the person's own tools
        assert 1 <= o["stage_no"] <= 10 and o["trust"]["label"] and o["range"].keys() == {"low", "high"}
    assert all(o.get("fix") is None for o in report["observations"] if o["status"] == "in")


def test_fixes_rebuilds_observations_for_a_new_stage():
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):
        return
    from mixcheck.web import server
    client = TestClient(server.app)
    body = {"flags": [], "measures": {"lufs": -20.0, "plr": 10.0, "lra": 5.0}, "target": "acoustic"}
    master = client.post("/api/fixes", json={**body, "stage": "master"}).json()
    mix = client.post("/api/fixes", json={**body, "stage": "mix"}).json()
    assert "style.loudness" in {o["id"] for o in master["observations"]}
    assert "style.loudness" not in {o["id"] for o in mix["observations"]}  # a mix isn't judged on loudness
    assert master["score"]["verdict"] is None and master["score"]["label"] == "No technical errors found"

def test_style_is_judged_against_the_target():
    from mixcheck.observations import CHAIN
    from mixcheck.style import style_match
    loud = {"lufs": -7.0, "plr": 8.0, "lra": 4.0, "air_pct": 0.001}
    trap, jazz = style_match(loud, "hiphop_rap", "master"), style_match(loud, "acoustic", "master")
    assert trap["percent"] == 100 and jazz["percent"] < 50
    # Observations say where each measure sits against the range, tagged to a stage, with no severity.
    acoustic = {o["id"]: o for o in _observations(loud, "acoustic", "master")}
    assert acoustic["style.loudness"]["status"] == "high" and acoustic["style.loudness"]["playbook"] == "louder_than_target"
    assert acoustic["style.punch"]["status"] == "low" and acoustic["style.punch"]["playbook"] == "more_limited_than_target"
    assert acoustic["style.loudness"]["stage_no"] == 10 and acoustic["style.contrast"]["stage_no"] == 4
    assert all(o["stage"] == CHAIN[o["stage_no"]] and "severity" not in o for o in acoustic.values())
    # Inside the range there is nothing to fix.
    inside = {o["id"]: o for o in _observations(loud, "hiphop_rap", "master")}
    assert inside["style.loudness"]["status"] == "in" and inside["style.loudness"]["playbook"] is None
    # Lo-fi is dull on purpose, so its missing top end isn't pointed out; other styles still get the note.
    assert "file.top_end" not in {o["id"] for o in _observations(loud, "lofi", "master")}
    top = {o["id"]: o for o in _observations(loud, "pop", "master")}["file.top_end"]
    assert top["status"] == "low" and top["playbook"] == "no_air"
    # A mix isn't judged on loudness.
    assert "lufs" not in {d["id"] for d in style_match(loud, "acoustic", "mix")["dims"]}
    assert "style.loudness" not in {o["id"] for o in _observations(loud, "acoustic", "mix")}
    # No style chosen: no match, and neutral defaults instead.
    assert style_match(loud, None, "master") is None
    default = {o["id"]: o for o in _observations(loud, None, "master")}
    assert default["default.loudness"]["status"] == "high" and default["default.loudness"]["playbook"] == "very_loud"
    assert not any(i.startswith("style.") for i in default)
    # Changing the style swaps the style observations and leaves the file's alone.
    assert {i for i in {o["id"] for o in _observations(loud, "hiphop_rap", "master")} if i.startswith("file.")} == {"file.top_end"}


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


def test_reference_observations_are_relative():
    from mixcheck.observations import attach_observation_fixes, reference_observations
    from mixcheck.reference import compare, measure_profile
    ref = measure_profile(_song(seed=2), FS, "Ref")
    same = compare(measure_profile(_song(seed=3), FS), [ref], "master")
    assert same["percent"] == 100 and all(o["status"] == "in" for o in reference_observations(same, "master"))

    light = compare(measure_profile(_song(bass_db=-3.5, width=0.15, seed=3) * 0.4, FS), [ref], "master")
    obs = {o["id"]: o for o in reference_observations(light, "master") if o["status"] != "in"}
    assert set(obs) == {"reference.tone.lows", "reference.width", "reference.loudness"}
    lows = obs["reference.tone.lows"]
    assert -4.0 < lows["value"] - lows["reference"] < -2.8 and lows["stage_no"] == 3
    assert "lighter below 100 Hz than your reference" in lows["summary"]
    assert obs["reference.width"]["stage_no"] == 9 and obs["reference.loudness"]["stage_no"] == 10
    assert all("severity" not in o for o in obs.values()) and light["percent"] < 70
    attach_observation_fixes([lows], {"daw": "ableton", "packages": ["fabfilter"]}, "master")
    assert "the lows (below 100 Hz)" in lows["fix"]["steps"][0]["text"] and lows["fix"]["steps"][0]["tool"] == "FabFilter Pro-Q"

    # A mix isn't compared on loudness.
    mix = compare(measure_profile(_song(seed=3) * 0.2, FS), [ref], "mix")
    assert "loudness" in mix["skipped"] and "loudness" not in {d["id"] for d in mix["dims"]}
    assert "reference.loudness" not in {o["id"] for o in reference_observations(mix, "mix")}


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
    from mixcheck.style import calibration_path, options, style_match, targets
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
        tone = [o for o in _observations(m, "hiphop_rap", "master") if o["dimension"] == "tone" and o["status"] == "low"]
        assert [o["band"] for o in tone] == ["lows", "highs"]
        assert "4.0 dB lighter below 100 Hz than typical for Hip-hop / rap" in tone[0]["summary"]
        assert all(o["stage_no"] == 3 and o["playbook"] == "tone_less_than_target" for o in tone)
        # Lo-fi's dull top end is the point, so it isn't pointed out.
        lofi = [o for o in _observations(m, "lofi", "master") if o["dimension"] == "tone" and o["status"] == "low"]
        assert [o["band"] for o in lofi] == ["lows"]
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
    from mixcheck.style import canonical, style_match
    assert canonical("trap_hiphop") == canonical("hiphop_rap") == "hiphop_rap"
    assert canonical("hiphop_rap.drill") == "hiphop_rap.drill"
    assert canonical("nope") is None and canonical(None) is None and canonical("") is None and canonical(["x"]) is None

    loud = {"lufs": -7.0, "plr": 8.0, "lra": 4.0, "air_pct": 0.001}
    assert style_match(loud, "trap_hiphop", "master") == style_match(loud, "hiphop_rap", "master")
    assert _observations(loud, "trap_hiphop", "master") == _observations(loud, "hiphop_rap", "master")
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
    from mixcheck.style import SUBGENRES, TARGETS, calibration_path, options, style_ids, style_match, targets
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

    # Flags come down too: lo-fi is dull on purpose, so its sub-genre isn't told it has no top end.
    quiet_top = {"air_pct": 0.001}
    assert "file.top_end" not in {o["id"] for o in _observations(quiet_top, "lofi.chillhop", "master")}
    assert "file.top_end" in {o["id"] for o in _observations(quiet_top, "pop.dance_pop", "master")}

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
        quiet = next(o for o in _observations({"lufs": -20.0}, "hiphop_rap.drill", "master") if o["id"] == "style.loudness")
        assert "the range for Drill (Hip-hop / rap) is -12 to -7 LUFS" in quiet["summary"]
        assert quiet["playbook"] == "quieter_than_target" and quiet["trust"]["kind"] == "rough"
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


def _load_listing_tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "list_installed_plugins", os.path.join(os.path.dirname(__file__), "..", "tools", "list_installed_plugins.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plugin_listing_tool_reads_mac_bundles_and_prints_no_paths():
    import json
    import tempfile
    from pathlib import Path
    tool = _load_listing_tool()
    root = Path(tempfile.mkdtemp())
    au, vst3, aax = root / "Components", root / "VST3", root / "Avid"
    for d in (au, vst3, aax):
        d.mkdir()
    _fake_bundle(vst3, "FabFilter Pro-Q 3", ".vst3", "com.fabfilter.Pro-Q.3")
    _fake_bundle(au, "FabFilter Pro-Q 3", ".component", "com.fabfilter.Pro-Q.3")  # the same plugin in another format
    _fake_bundle(aax, "UAD 1176", ".aaxplugin", "com.uaudio.1176")
    (au / "Broken.component" / "Contents").mkdir(parents=True)  # no plist: still listed, by its file name
    (vst3 / "readme.txt").write_text("not a plugin")
    result = tool.list_plugins("mac", [au, vst3, aax, root / "Missing"])
    found = {(p["name"], p["format"]): p for p in result["plugins"]}
    assert set(found) == {("FabFilter Pro-Q 3", "VST3"), ("FabFilter Pro-Q 3", "AU"), ("UAD 1176", "AAX"), ("Broken", "AU")}
    assert found[("UAD 1176", "AAX")]["vendor"] == "uaudio" and found[("UAD 1176", "AAX")]["version"] == "1.0"
    assert found[("Broken", "AU")]["vendor"] is None and result["count"] == 4
    assert str(root) not in json.dumps(result)  # no full path anywhere in the output
    assert len(result["folders_found"]) == 3 and all(len(f.split("/")) == 2 for f in result["folders_found"])  # last two parts only


def test_plugin_listing_tool_reads_windows_files_by_vendor_folder():
    import tempfile
    from pathlib import Path
    tool = _load_listing_tool()
    root = Path(tempfile.mkdtemp())
    vst3, vst2 = root / "VST3", root / "VSTPlugins"
    (vst3 / "Waves").mkdir(parents=True)
    vst2.mkdir()
    (vst3 / "Waves" / "WaveShell1-VST3 14.0.vst3").write_text("x")
    (vst3 / "FabFilter Pro-L 2.vst3").write_text("x")
    (vst2 / "OldComp.dll").write_text("x")
    (vst2 / "notes.txt").write_text("x")
    got = {(p["name"], p["format"], p["vendor"]) for p in tool.list_plugins("windows", [vst3, vst2])["plugins"]}
    assert got == {("WaveShell1-VST3 14.0", "VST3", "Waves"), ("FabFilter Pro-L 2", "VST3", None), ("OldComp", "VST2", None)}
    other = tool.list_plugins("other")
    assert other["count"] == 0 and other["plugins"] == []


def test_plugin_picker_options_and_setups_accept_listed_plugins():
    from mixcheck import catalog
    from mixcheck.remediation import normalize_setup
    opts = {p["id"]: p for p in catalog.options()["packages"]}
    assert set(catalog.PACKAGES) <= set(opts) and all(opts[i]["has_steps"] for i in catalog.PACKAGES)
    catalog.LISTED["uad_1176"] = {"name": "UAD 1176", "group": "Universal Audio", "category": "compressor"}
    try:
        listed = {p["id"]: p for p in catalog.options()["packages"]}["uad_1176"]
        assert listed["has_steps"] is False and listed["group"] == "Universal Audio"
        setup = normalize_setup({"daw": "logic", "packages": ["uad_1176", "waves_l2", "made_up"]})
        assert setup["packages"] == ["uad_1176", "waves_l2"]  # known ids are kept, unknown ones dropped
        # A plugin with no steps adds no tools: the fixes are the same as without it.
        plain = normalize_setup({"daw": "logic", "packages": ["waves_l2"]})
        assert catalog.owned_tools(setup).keys() == catalog.owned_tools(plain).keys()
    finally:
        catalog.LISTED.pop("uad_1176")


def test_every_floor_has_a_stage_and_listed_plugins_describe_cleanly():
    from mixcheck import analyze, catalog, observations
    from mixcheck.remediation import describe_setup, normalize_setup, render_actions
    assert set(analyze.FLOOR_STAGE) == analyze.FLOOR_IDS
    assert all(n in observations.CHAIN for n, _ in analyze.FLOOR_STAGE.values())
    import tempfile
    import soundfile as sf
    t = np.arange(96000) / 48000
    x = np.clip(1.6 * np.sin(2 * np.pi * 220 * t), -1, 1)  # clipped and hot: raises several floors
    with tempfile.TemporaryDirectory() as d:
        sf.write(f"{d}/c.wav", np.stack([x, x], axis=1), 48000)
        flags = analyze.analyze_file(f"{d}/c.wav")["flags"]
    assert flags
    for f in flags:
        assert f["stage_no"] == analyze.FLOOR_STAGE[f["id"]][0] and f["stage"] == observations.CHAIN[f["stage_no"]]
    listed = next(i for i, v in catalog.LISTED.items() if v["group"] == "Universal Audio (UAD)")
    label = describe_setup(normalize_setup({"daw": "logic", "packages": [listed, "waves_l2"]}))
    assert catalog.LISTED[listed]["name"] in label and "Waves (L2)" in label


def test_render_actions_uses_the_persons_tools_and_rejects_unknown_ids():
    from mixcheck.remediation import render_actions
    plain = render_actions(["limit_true_peak", "made_up", "limit_true_peak"], {"daw": "other", "packages": []})
    assert plain["rejected"] == ["made_up"] and len(plain["steps"]) == 1 and plain["steps"][0]["tool"] is None
    owned = render_actions(["limit_true_peak"], {"daw": "other", "packages": ["waves_l2"]})
    assert owned["steps"][0]["tool"] == "Waves L2" and "L2" in owned["steps"][0]["text"]
    ctx = render_actions(["clip_gain"], None, {"id": "clipping", "times_s": [12.0]})
    assert "0:12" in ctx["steps"][0]["text"]


def test_the_library_points_only_at_things_that_exist():
    from mixcheck import analyze, catalog, library, observations, remediation
    data = library.load()
    assert data["status"] == "draft" and library.source_label() == "general knowledge"
    keys = set()
    for e in data["entries"]:
        assert e["stage_no"] in observations.CHAIN and e["scope"] in ("vocal", "mix", "master")
        assert e["causes"] and all(c["likelihood"] in ("common", "possible", "rare") for c in e["causes"])
        for k in e["applies_to"]:
            assert k in remediation.FIXES, k          # a floor id or playbook key
            assert k not in keys, f"{k} is in two entries"
            keys.add(k)
        for a in e["fix_actions"]:
            assert a in catalog.ACTIONS, a
        for oid in e["observation_ids"]:
            source, dim = oid.split(".")[:2]
            assert source in ("style", "reference", "default", "file", "vocal"), oid
            assert dim in observations.STAGE_OF or dim in ("tone", "top_end"), oid
        assert all(c["upstream"] is False or e["vigil"] for c in e["causes"]), f"{e['id']}: upstream cause without Vigil"
    assert analyze.FLOOR_IDS - {"silent"} <= keys   # every floor except a silent file has an entry
    assert library.entry_for("clipping")["id"] == "clipping" and library.entry_for("nope") is None


def test_plugin_list_and_bundles_resolve():
    from mixcheck import catalog
    known = set(catalog.PACKAGES) | set(catalog.LISTED)
    assert len(catalog.LISTED) > 500 and not set(catalog.LISTED) & set(catalog.PACKAGES)
    for b in catalog.BUNDLES:
        assert b["plugins"] and set(b["plugins"]) <= known, b["id"]
    ids = {b["id"] for b in catalog.options()["bundles"]}
    assert {"waves_essential", "waves_ultimate", "pro_tools_artist", "pro_tools_studio"} <= ids
    ess = next(b for b in catalog.BUNDLES if b["id"] == "waves_essential")["plugins"]
    assert "waves_l2" in ess and "waves_f6" in ess   # the plugins with steps keep their ids inside the bundle


def test_plugin_requests_are_noted_on_this_computer():
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):
        return
    import json
    from mixcheck.util import mixcheck_home
    from mixcheck.web import server
    client = TestClient(server.app)
    assert client.get("/api/scan").status_code in (404, 405)  # the scan is gone
    ok = client.post("/api/plugins/request", json={"name": "  UAD   Pultec\x07 EQP-1A  "})
    assert ok.status_code == 200 and ok.json() == {"noted": "UAD Pultec EQP-1A"}
    assert client.post("/api/plugins/request", json={"name": "x"}).status_code == 422
    long = client.post("/api/plugins/request", json={"name": "Z" * 300}).json()["noted"]
    assert len(long) == 80
    lines = [json.loads(line) for line in open(mixcheck_home() / "plugin_requests.jsonl", encoding="utf-8")]
    assert lines[0]["name"] == "UAD Pultec EQP-1A" and set(lines[0]) == {"name", "day"}  # nothing else is kept


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


def _vocal_obs(vocal, beat_db=-20):
    """{dimension: observation} for the vocal observations that sit outside their range."""
    from mixcheck.observations import vocal_observations
    from mixcheck.vocal import measure_vocal
    return {o["dimension"]: o for o in vocal_observations(measure_vocal(vocal, _beat(beat_db), VFS)) if o["status"] != "in"}


def _far(o):
    return o is not None and o["beyond_second_limit"]


def test_vocal_dynamics_tell_a_raw_vocal_from_a_compressed_one():
    raw = _vocal_obs(_voice([-30, -14, -22, -10, -26, -12])).get("vocal_dynamics")
    assert raw["status"] == "high" and _far(raw) and raw["playbook"] == "vocal_uncompressed" and raw["stage_no"] == 4
    assert "vocal_dynamics" not in _vocal_obs(_voice(EVEN))  # an even vocal is within range


def test_vocal_tone_observations():
    for kwargs, dim, status, stage_no in ((dict(thin=True), "vocal_body", "low", 3), (dict(rumble=True), "vocal_rumble", "high", 2),
                                          (dict(mud_db=14), "vocal_mud", "high", 3), (dict(sib_db=4), "vocal_sibilance", "high", 5)):
        o = _vocal_obs(_voice(EVEN, **kwargs)).get(dim)
        assert o and o["status"] == status and _far(o) and o["stage_no"] == stage_no and o["estimated"] and o["scope"] == "vocal", dim
    # A plain, evenly-leveled vocal is within range everywhere.
    assert _vocal_obs(_voice(EVEN)) == {}


def test_vocal_level_against_the_beat():
    buried = _vocal_obs(_voice(EVEN), beat_db=-6).get("vocal_level")
    assert buried["status"] == "low" and _far(buried) and buried["playbook"] == "vocal_buried" and buried["stage_no"] == 8
    dominant = _vocal_obs(_voice(EVEN), beat_db=-40).get("vocal_level")
    assert dominant["status"] == "high" and _far(dominant) and dominant["playbook"] == "vocal_dominant"


def test_no_vocal_means_no_observations_on_it():
    from mixcheck.observations import vocal_observations
    from mixcheck.vocal import measure_vocal
    quiet = measure_vocal(np.zeros((VFS * 10, 2)), _beat(-20, 10), VFS)
    assert quiet["found"] is False and "instrumental" in quiet["reason"]
    assert vocal_observations(quiet) == []
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


def test_split_vocal_adds_estimated_observations_and_leaves_the_score_alone():
    path = _clean_mix_file()
    unchecked = analyze_file(path, stage="mix")
    assert unchecked["vocal"] is None and unchecked["score"]["vocal_checked"] is False
    assert unchecked["score"]["label"] == "No technical errors found"
    assert not any(o["source"] == "vocal" for o in unchecked["observations"])

    raw, beat = _voice([-30, -14, -22, -10, -26, -12]), _beat(-20)
    stages = []
    checked = _with_fake_split(raw, beat, lambda: analyze_file(path, stage="mix", split_vocal=True, progress=stages.append))
    from mixcheck.analyze import PROGRESS_STAGES
    assert stages == [*PROGRESS_STAGES[:5], "vocal", *PROGRESS_STAGES[5:]]
    v = checked["vocal"]
    assert v["found"] and v["source"] == {"method": "split", "model": "htdemucs", "estimated": True}
    assert "more accurate" in v["disclaimer"]
    obs = next(o for o in checked["observations"] if o["id"] == "vocal.vocal_dynamics")
    assert obs["estimated"] and obs["status"] == "high" and obs["fix"]["steps"]  # steps written for the user's tools
    assert not any(f["id"].startswith("vocal_") for f in checked["flags"])  # observations, not findings
    # The vocal estimates never cost technical points: the score counts only the floors.
    assert checked["score"]["vocal_checked"] and checked["score"]["value"] == unchecked["score"]["value"]

    # A well-made vocal that was checked has nothing outside its range. It still isn't called "ready": only a verdict can.
    good = _with_fake_split(_voice(EVEN), beat, lambda: analyze_file(path, stage="mix", split_vocal=True))
    assert good["score"]["label"] == "No technical errors found"
    assert not [o for o in good["observations"] if o["source"] == "vocal" and o["status"] != "in"]
    assert good["score"]["verdict"] is None


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
    assert not any(o["source"] == "vocal" for o in report["observations"])
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
    items = notes_input(report)["observations"]
    assert any(o["kind"] == "vocal_uncompressed" and o["estimated"] and o["trust"] for o in items)
    assert not any(f["kind"].startswith("vocal_") for f in notes_input(report)["findings"])


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
    # Fixes rebuilt for a new stage keep the vocal observations the page sends back.
    report = events[-1]["report"]
    fixed = client.post("/api/fixes", json={"flags": report["flags"], "stage": "mix", "measures": report["measures"],
                                            "vocal": True, "observations": report["observations"]}).json()
    assert fixed["score"]["vocal_checked"] and any(o["id"] == "vocal.vocal_dynamics" for o in fixed["observations"])
    assert not any(f["id"].startswith("vocal_") for f in fixed["flags"])
    # A page from before the refactor may still send old findings; they are not findings any more and are dropped.
    stale = client.post("/api/fixes", json={"flags": [{"id": "louder_than_target", "severity": "warning"},
                                                      {"id": "clipping", "severity": "warning"}],
                                            "stage": "master", "measures": report["measures"]}).json()
    assert [f["id"] for f in stale["flags"]] == ["clipping"]


def test_labels_say_what_was_found_and_never_claim_readiness():
    from mixcheck.score import LABELS, READY_LABELS, score_flags
    # No label of the technical score, at any level or stage, says a mix is ready.
    words = " ".join(name for _, name in LABELS).lower()
    assert "ready" not in words and "release" not in words and "solid" not in words and "wings" not in words
    for stage in ("mix", "master"):
        clean = score_flags([], stage)
        assert clean["value"] == 10.0 and clean["label"] == "No technical errors found" and clean["verdict"] is None
        assert score_flags([], stage, vocal=True)["label"] == "No technical errors found"
    assert score_flags([{"id": "silent", "severity": "critical"}], "mix")["label"] == "Major technical problems"
    assert set(READY_LABELS) == {"mix", "master"}


def test_only_a_verdict_can_earn_the_ready_label_and_code_checks_it():
    from mixcheck.score import apply_verdict, score_flags
    warn = {"id": "true_peak_hot", "severity": "warning", "value": -0.4}
    for stage in ("mix", "master"):
        ready_label = "Ready for Wings"
        clean = score_flags([], stage)
        # Not judged yet: nothing changes.
        assert apply_verdict(clean, [], stage, None)["label"] == "No technical errors found"
        assert apply_verdict(clean, [], stage, None)["verdict"] is None
        # Judged ready, with nothing open and nothing wrong: granted.
        ok = apply_verdict(clean, [], stage, {"ready": True, "open_diagnoses": 0})
        assert ok["label"] == ready_label and ok["verdict"] == {"ready": True, "granted": True, "blockers": []}
        # Judged ready but a diagnosis is still open: not granted, and it says why.
        held = apply_verdict(clean, [], stage, {"ready": True, "open_diagnoses": 2})
        assert held["label"] == "No technical errors found" and not held["verdict"]["granted"]
        assert "2 diagnoses still open" in held["verdict"]["blockers"][0]
        # Judged not ready: label unchanged.
        no = apply_verdict(clean, [], stage, {"ready": False, "open_diagnoses": 0})
        assert no["label"] == "No technical errors found" and no["verdict"] == {"ready": False, "granted": False, "blockers": []}
    # The score itself is not enough, and neither is the verdict: a floor finding at warning level blocks it.
    flagged = score_flags([warn], "master")
    blocked = apply_verdict(flagged, [warn], "master", {"ready": True, "open_diagnoses": 0})
    assert not blocked["verdict"]["granted"] and "true_peak_hot" in " ".join(blocked["verdict"]["blockers"])
    # So does a technical score under 9.
    low = score_flags([{"id": "clipping", "severity": "warning", "value": 20}, {"id": "negative_correlation", "severity": "critical"}], "master")
    assert low["value"] < 9.0
    assert not apply_verdict(low, [], "master", {"ready": True, "open_diagnoses": 0})["verdict"]["granted"]
    # A verdict that isn't well formed is refused.
    for bad in ({}, {"ready": "yes"}, {"ready": True, "open_diagnoses": True}, "ready"):
        try:
            apply_verdict(score_flags([], "mix"), [], "mix", bad)
            assert False, bad
        except ValueError:
            pass

def _decay_input(kind, rt60, bed_db=None, seconds=20):
    from decay_synth import sounds, with_bed, with_reverb
    x = with_reverb(sounds(kind, seconds=seconds), rt60)
    if bed_db is not None:
        x = with_bed(x, bed_db)
    return np.column_stack([x, x])


def test_decay_reads_known_reverb():
    from mixcheck.decay import measure_decay
    for kind in ("word", "hit"):
        for rt in (0.6, 1.6):
            overall = measure_decay(_decay_input(kind, rt), FS)["overall"]
            assert overall["status"] == "estimated", (kind, rt, overall)
            assert abs(overall["t60_s"] - rt) / rt < 0.20, (kind, rt, overall)  # within 20% of the true decay time
            assert overall["confidence"] > 0.4


def test_decay_sees_no_tail_in_dry_sound_and_declines_a_masked_mix():
    from mixcheck.decay import measure_decay
    for kind in ("word", "hit"):
        dry = measure_decay(_decay_input(kind, None), FS)["overall"]
        assert dry["status"] == "estimated" and dry["no_measurable_tail"] and dry["t60_s"] is None, (kind, dry)
    # A steady bed only 15 dB under the peaks covers every ending: the honest answer is "couldn't tell".
    masked = measure_decay(_decay_input("word", 1.0, bed_db=-15.0), FS)["overall"]
    assert masked["status"] == "couldnt_tell" and masked["confidence"] == 0.0 and "reason" in masked


def test_decay_is_an_upper_limit_not_a_room_reading():
    from mixcheck.decay import measure_decay
    # A note that rings by itself reads as a tail even with no room: the method cannot tell the room from the source,
    # so the result is an upper limit, and says so.
    dry_note = measure_decay(_decay_input("note", None), FS)
    assert dry_note["overall"]["status"] == "estimated" and 0.9 < dry_note["overall"]["t60_s"] < 1.5
    assert "upper limit" in dry_note["meaning"]
    # With a real, shorter room added the reading never drops below the room (the limit holds).
    roomy = measure_decay(_decay_input("note", 0.3), FS)["overall"]
    assert roomy["t60_s"] >= 0.3 * 0.85


def test_decay_tells_a_ringing_note_from_reverb():
    from mixcheck.decay import measure_decay
    # A note ringing by itself falls smoothly, so its long reading is flagged as a loose limit, with or without a short room.
    for rt in (None, 0.3):
        assert measure_decay(_decay_input("note", rt), FS)["overall"]["attribution"] == "source_ringing", rt
    # A diffuse reverb tail fluctuates as it falls: abrupt sources in a real room read as reverb.
    for kind in ("word", "hit"):
        assert measure_decay(_decay_input(kind, 1.6), FS)["overall"]["attribution"] == "reverb_like", kind
    # No tail, no attribution.
    assert measure_decay(_decay_input("word", None), FS)["overall"]["attribution"] == "none"

def test_decay_can_be_limited_to_time_ranges():
    from mixcheck.decay import measure_decay
    x = _decay_input("hit", 1.0)
    everything = measure_decay(x, FS)["overall"]
    assert everything["status"] == "estimated"
    assert measure_decay(x, FS, ranges=[(0.0, 20.0)])["overall"]["t60_s"] == everything["t60_s"]
    assert measure_decay(x, FS, ranges=[(0.0, 1.0)])["overall"]["status"] == "couldnt_tell"  # fewer than 3 endings


def test_decay_handles_silence_and_very_short_input():
    from mixcheck.decay import measure_decay
    assert measure_decay(np.zeros((FS * 5, 2)), FS)["overall"]["status"] == "couldnt_tell"
    assert measure_decay(np.random.default_rng(0).standard_normal((FS // 5, 2)) * 0.1, FS)["overall"]["status"] == "couldnt_tell"
    assert measure_decay(np.zeros(FS), FS)["overall"]["status"] == "couldnt_tell"  # 1-D input

if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS  {name}")
    print(f"\nAll {len(tests)} tests passed.")
