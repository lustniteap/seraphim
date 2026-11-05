"""Deterministic checks on engineer's notes: free, exact, and run on every case.

Each check returns (score, details): score is 1.0 (pass), 0.0 (fail), a fraction for coverage,
or None when the check doesn't apply to the case. details says what failed, so a zero can be
traced to the sentence that caused it.

The ground truth is the MixCheck report the notes were written from. The engine measured the
file and chose the fixes, so anything the notes claim can be checked against it.
"""
import json
import re

from mixcheck.catalog import PACKAGES, TOOLS, owned_tools

# A number with a unit, as it would be quoted from the report: "-14.7 LUFS", "+0.3 dBTP", "3 dB".
# A bare "s" only counts as seconds after a space ("30 s"): "808s" is the drum machine, not a duration.
NUMBER_WITH_UNIT = re.compile(
    r"(?<![\w.])([+\-−]?\d+(?:\.\d+)?)\s*(dBTP|dBFS|LUFS|LU|dB|kHz|Hz|%|ms|seconds?\b|(?<=\s)s\b)")
TIME = re.compile(r"\b\d{1,2}:\d{2}\b")

# Pushing loudness up is mastering's job; notes on a mix shouldn't ask for it.
MIX_LOUDNESS_PUSH = re.compile(
    r"\b(push|raise|increase|bring up|boost|drive|crank|turn up)\b[^.;:]{0,40}"
    r"\b(loudness|LUFS|limit(er|ing)?|maximi[sz](er|e|ing))\b", re.I)


def notes_text(notes):
    """Everything the user reads in the notes, except the fix steps (which come from MixCheck)."""
    parts = [notes["headline"], notes["summary"]]
    for p in notes["priorities"]:
        parts += [p["title"], p["why"]]
    return "\n".join(parts + notes["listen_for"] + notes["strengths"])


def _num(s):
    return float(s.replace("−", "-").replace("+", ""))


# Units that mean the same quantity. dB, dBTP and dBFS are used loosely for levels, so they're one family.
FAMILY = {"LUFS": "LUFS", "LU": "LU", "dB": "dB", "dBTP": "dB", "dBFS": "dB", "Hz": "Hz", "kHz": "kHz",
          "%": "%", "ms": "ms", "s": "s", "second": "s", "seconds": "s"}
# Units of the measurement fields in notes_input(), by key suffix.
KEY_UNITS = {"_lufs": "LUFS", "_lu": "LU", "_dbtp": "dB", "_db": "dB", "_percent": "%"}
RANGE_WITH_UNIT = re.compile(
    r"([+\-−]?\d+(?:\.\d+)?)\s*(?:to|–|-)\s*([+\-−]?\d+(?:\.\d+)?)\s*(dBTP|dBFS|LUFS|LU|dB|kHz|Hz|%)")


def _input_numbers(inp):
    """{unit family: {abs values}} for every number-with-unit anywhere in the input."""
    found = {}

    def add(unit, v):
        found.setdefault(FAMILY[unit], set()).add(abs(v))

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            unit = next((u for suffix, u in KEY_UNITS.items() if key.endswith(suffix)), None)
            if unit:
                add(unit, float(o))
        elif isinstance(o, str):
            for m in NUMBER_WITH_UNIT.finditer(o):
                add(m.group(2), _num(m.group(1)))
            for m in RANGE_WITH_UNIT.finditer(o):  # "−6 to −3 dBFS": the first number has the unit too
                add(m.group(3), _num(m.group(1)))
    walk(inp)
    # Durations and times are written m:ss ("duration": "0:40"), and notes rightly say "the whole 40 seconds".
    for t in TIME.findall(json.dumps(inp, ensure_ascii=False)):
        m, sec = t.split(":")
        add("s", 60 * int(m) + int(sec))
    return found


def _tolerance(quoted):
    """Honest rounding passes: "−14 LUFS" for −14.2, "3.3 dB" for 3.34, but "0.14 dB" must be 0.14."""
    decimals = len(quoted.split(".")[1]) if "." in quoted else 0
    return 0.5 * 10 ** -decimals + 1e-9


def numbers_grounded(notes, inp):
    """Every number-with-unit in the notes appears in the report with that unit (sign ignored: "3 dB lighter")."""
    allowed = _input_numbers(inp)
    times = set(TIME.findall(json.dumps(inp, ensure_ascii=False)))
    text = notes_text(notes)
    quoted = list(NUMBER_WITH_UNIT.finditer(text))
    bad = [m.group(0) for m in quoted
           if not any(abs(abs(_num(m.group(1))) - a) <= _tolerance(m.group(1))
                      for a in allowed.get(FAMILY[m.group(2)], ()))]
    bad += [t for t in TIME.findall(text) if t not in times]
    n = len(quoted) + len(TIME.findall(text))
    if not n:
        return None, "no numbers quoted"
    return (0.0 if bad else 1.0), ("not in the report: " + ", ".join(bad) if bad else f"{n} quoted, all found")


def ids_valid(issues):
    """The notes only pointed at findings and steps that exist (check() in notes.py drops the rest)."""
    bad = [f"{i['type']} {i.get('id') or i.get('title')}" for i in issues
           if i["type"] in ("unknown_finding", "unknown_step", "priority_dropped")]
    return (0.0 if bad else 1.0), "; ".join(bad) or "all ids exist"


def covers(notes, inp, severities):
    """Share of findings with these severities that some priority points at."""
    wanted = [f["id"] for f in inp["findings"] if f["severity"] in severities]
    if not wanted:
        return None, f"no {'/'.join(severities)} findings"
    cited = {i for p in notes["priorities"] for i in p["finding_ids"]}
    missed = [f"{i} ({next(f['kind'] for f in inp['findings'] if f['id'] == i)})" for i in wanted if i not in cited]
    return 1 - len(missed) / len(wanted), ("missed " + ", ".join(missed) if missed else "all covered")


def no_invented_problems(notes, inp, issues=()):
    """With nothing to fix, there are no priorities. Counts what the model wrote, including priorities
    notes.check() already dropped for pointing at nothing, so an invention the user never sees still counts."""
    if inp["findings"]:
        return None, "the report has findings"
    n = len(notes["priorities"]) + sum(i["type"] == "priority_dropped" for i in issues)
    return (0.0 if n else 1.0), (f"{n} priorities for a clean report" if n else "no priorities, as expected")


def stage_appropriate(notes, inp):
    """A mix isn't told to push its loudness or limiting; that's mastering's job."""
    if inp["stage"] != "mix":
        return None, "not a mix"
    hits = [m.group(0) for m in MIX_LOUDNESS_PUSH.finditer(notes_text(notes))]
    return (0.0 if hits else 1.0), ("asks a mix to: " + "; ".join(hits) if hits else "no loudness push")


def _tool_names():
    """Names a note might use for each tool in the catalog, mapped to the tool ids that carry them."""
    names = {}
    for tid, t in TOOLS.items():
        full = t["name"]
        names.setdefault(full, set()).add(tid)
        # "FabFilter Pro-L 2" is also written "Pro-L 2"; "Waves L2" as "L2".
        for prefix in ("FabFilter ", "Waves ", "iZotope "):
            if full.startswith(prefix):
                names.setdefault(full[len(prefix):], set()).add(tid)
    # Short forms people actually write.
    for alias, tid in {"PAZ": "waves_paz", "WLM": "waves_wlm", "Insight": "insight", "MultiMeter": "logic_meters",
                       "Pro-L": "ff_pro_l2", "Pro-C": "ff_pro_c2", "Dyn 3": "pt_dyn3", "EQ3": "pt_eq3",
                       "Renaissance": "waves_rcomp"}.items():
        names.setdefault(alias, set()).add(tid)
    names["Renaissance"].add("waves_renaissance_eq")
    # Names that are also ordinary words or shared by several DAWs aren't a claim about a product.
    for generic in ("Limiter", "Compressor", "Gain", "Trim", "Utility", "Mixer", "Export", "Bounce",
                    "Clip Gain", "Volume automation", "Automation clip", "Clip View", "Channel EQ",
                    "Region inspector"):
        names.pop(generic, None)
    return names


TOOL_NAMES = _tool_names()
# Brand names on their own ("try Ozone") count as naming a product the user may not own.
BRANDS = {
    "FabFilter": {"fabfilter"},
    "iZotope": {"izotope_ozone", "izotope_insight"},
    "Ozone": {"izotope_ozone"},
    "Waves": {p for p in PACKAGES if p.startswith("waves_")},
}


def tools_owned(notes, inp, setup):
    """Every catalog tool or brand the notes name is one the user owns."""
    owned, packages = set(owned_tools(setup)), set(setup["packages"])
    text = notes_text(notes)
    said = lambda name: re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text)
    bad = {n for n, tids in TOOL_NAMES.items() if said(n) and not tids & owned}
    bad |= {b for b, pids in BRANDS.items() if said(b) and not pids & packages}
    return (0.0 if bad else 1.0), ("names tools not owned: " + ", ".join(sorted(bad)) if bad else "only owned tools")


def length(notes):
    """Words the user reads, for the report's length column (not pass/fail)."""
    return len(notes_text(notes).split())


def grade(result, inp, setup):
    """All deterministic checks for one case: ({metric: score}, {metric: details})."""
    notes, issues = result["notes"], result["issues"]
    checks = {
        "ids_valid": ids_valid(issues),
        "covers_critical": covers(notes, inp, ("critical",)),
        "covers_warnings": covers(notes, inp, ("warning",)),
        "numbers_grounded": numbers_grounded(notes, inp),
        "tools_owned": tools_owned(notes, inp, setup),
        "stage_appropriate": stage_appropriate(notes, inp),
        "no_invented_problems": no_invented_problems(notes, inp, issues),
    }
    return {k: v[0] for k, v in checks.items()}, {k: v[1] for k, v in checks.items()}
