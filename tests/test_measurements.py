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
    except ImportError:  # the web extra isn't installed
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
    except ImportError:  # the web extra isn't installed
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
    assert "couldn't be read as audio" in error and "/tmp" not in error
    assert "/tmp" not in client.post("/api/analyze", files={"file": ("x.wav", b"not audio", "audio/wav")}).json()["detail"]
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
    from mixcheck import feedback
    with _TempHome():
        result, _ = _written_notes()
        for rating, why in (("up", []), ("down", ["too_long"]), ("down", ["too_long", "generic"])):
            feedback.rate(feedback.remember(result), rating, why)
        _, text, _ = feedback.export("sam")
        path = Path(os.environ["MIXCHECK_HOME"]) / "feedback-sam.jsonl"
        path.write_text(text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            notes_eval.cmd_feedback(NS(files=[str(path)], local=False))
        summary = out.getvalue()
        assert "3 rating(s)" in summary and "notes-v2" in summary and "33%" in summary
        assert "too_long 2" in summary and "generic 1" in summary


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS  {name}")
    print(f"\nAll {len(tests)} tests passed.")
