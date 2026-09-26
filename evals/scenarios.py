"""Turn one saved report into several eval cases: the same bounce judged a few different ways.

A report records one stage, setup and style. Notes have to be right for all of them, so each
report is re-judged, without the audio, using the same functions the web page uses when the user
switches mix/master, changes their setup or picks a style (see /api/fixes in web/server.py).
"""
import copy

from mixcheck.reference import REFERENCE_IDS
from mixcheck.remediation import attach_fixes, describe_setup, normalize_setup
from mixcheck.score import score_flags
from mixcheck.style import apply_style, style_match

# id -> how to re-judge. None keeps what the report recorded.
SCENARIOS = {
    # Exactly what the user saw.
    "as_recorded": {"stage": None, "setup": None, "target": None},
    # The other stage and a different toolset: stage-appropriate advice, and only owned tools.
    "other_stage": {"stage": "flip", "setup": {"daw": "logic", "packages": ["fabfilter"]}, "target": ""},
    # A style to aim for, with stock tools only.
    "trap_target": {"stage": None, "setup": {"daw": "ableton", "packages": []}, "target": "trap_hiphop"},
}


def rejudge(report, stage=None, setup=None, target=None):
    """A copy of the report as MixCheck would show it for this stage, setup and style."""
    r = copy.deepcopy(report)
    stage = stage or r["stage"]["value"]
    if stage == "flip":
        stage = "master" if r["stage"]["value"] == "mix" else "mix"
    setup = normalize_setup(setup if setup is not None else r["setup"])
    target = (r.get("target") or "") if target is None else target

    flags = r["flags"]
    if stage != r["stage"]["value"]:
        # The reference comparison depends on the stage (a mix isn't compared on loudness), and the
        # reference profiles themselves aren't saved in the report, so it can't be redone here.
        flags = [f for f in flags if f["id"] not in REFERENCE_IDS]
        r["reference"] = None
    flags = attach_fixes(apply_style(flags, r["measures"], target, stage), setup, stage)
    r.update(
        flags=flags,
        score=score_flags(flags, stage),
        style=style_match(r["measures"], target, stage),
        target=target or None,
        setup={**setup, "label": describe_setup(setup)},
        stage={**r["stage"], "value": stage},
    )
    return r


def cases_for(name, report, scenarios=SCENARIOS):
    """[(case_id, scenario_id, report)] for one saved report."""
    return [(f"{name}__{sid}", sid, rejudge(report, **spec)) for sid, spec in scenarios.items()]
