"""Engineer's notes: an optional, AI-written summary of a MixCheck report.

The engine stays the source of truth. This module only *writes*: it sends Claude
a trimmed copy of the report (numbers, findings and the fix steps already chosen
for the user's tools; never audio, never the file name) and asks for notes in a
fixed structure. Every finding and step the notes point to is checked against the
report, and anything that doesn't exist is dropped and recorded as an issue.

Optional by design: it needs `pip install -e ".[ai]"` and Anthropic credentials
(ANTHROPIC_API_KEY or an `ant auth login` profile). MIXCHECK_AI=off turns it off.
"""
import importlib.util
import json
import os
from pathlib import Path
from typing import List

from .util import fmt_time

PROMPT_FILE = Path(__file__).parent / "prompts" / "notes.md"
PROMPT_VERSION = "notes-v2"  # bump whenever prompts/notes.md or notes_input() changes
DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000
# If the model declines, the API retries the same request on a fallback model it picks.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class NotesUnavailable(RuntimeError):
    """The notes can't be written right now; the message says why, in plain words."""


def model():
    return os.environ.get("MIXCHECK_AI_MODEL") or DEFAULT_MODEL


def available():
    """(True, "") when notes can be written, else (False, reason)."""
    if os.environ.get("MIXCHECK_AI", "").lower() in ("0", "off", "false", "no"):
        return False, "AI notes are turned off (MIXCHECK_AI=off)."
    if importlib.util.find_spec("anthropic") is None:
        return False, 'AI notes need the optional package: pip install -e ".[ai]"'
    return True, ""


# ---------------------------------------------------------------- input

def _when(flag):
    if "start_s" in flag:
        return f"{fmt_time(flag['start_s'])}–{fmt_time(flag['end_s'])}"
    times = list(dict.fromkeys(fmt_time(t) for t in flag.get("times_s") or []))
    return ", ".join(times[:5]) or None


def notes_input(report):
    """The part of the report the notes are written from, with ids to point at.

    Leaves out audio-derived bulk (the loudness timeline, per-channel detail) and the
    file name, which the notes don't need.
    """
    loud, st, pk = report["loudness"], report.get("stereo") or {}, report["peaks"]
    findings = []
    for i, f in enumerate(report["flags"], 1):
        fix = f.get("fix") or {"steps": [], "more": []}
        steps = [{"id": f"F{i}.{j}", "text": s["text"], "tool": s["tool"]}
                 for j, s in enumerate(fix["steps"] + fix["more"], 1)]
        findings.append({
            "id": f"F{i}", "kind": f["id"], "severity": f["severity"], "measured": f["message"],
            **({"when": _when(f)} if _when(f) else {}),
            "steps": steps[:len(fix["steps"])], "other_options": steps[len(fix["steps"]):],
        })
    style, ref, score = report.get("style"), report.get("reference"), report["score"]
    return {
        "stage": report["stage"]["value"],
        "setup": report["setup"]["label"],
        "duration": fmt_time(report["file"]["duration_s"]),
        "channels": "stereo" if report["file"]["channels"] == 2 else "mono",
        "score": {"value": score["value"], "of": 10, "label": score["label"], "if_fixed": score["if_fixed"]},
        "measurements": {
            "integrated_loudness_lufs": loud["integrated_lufs"],
            "loudness_range_lu": loud["loudness_range_lu"],
            "true_peak_dbtp": pk["true_peak_max_dbtp"],
            "peak_to_loudness_db": report["dynamics"]["plr_db"],
            **({
                "lr_correlation": st.get("correlation"),
                "low_end_correlation": st.get("low_end_correlation"),
                "mono_loss_db": st.get("mono_loudness_loss_db"),
                "left_right_balance_db": st.get("left_right_balance_db"),
            } if st else {}),
        },
        "style": {
            "going_for": style["name"], "match_percent": style["percent"],
            "ranges_from": f"{style['songs']} measured releases" if style.get("songs") else "built-in starting points",
        } if style else None,
        "reference": {
            "songs": len(ref["references"]), "match_percent": ref["percent"],
            "compared": [d["id"] for d in ref["dims"]], "not_compared": ref["skipped"],
        } if ref else None,
        "findings": findings,
    }


# ---------------------------------------------------------------- output

def _schema():
    try:
        from pydantic import BaseModel
    except ImportError:  # only possible with a stand-in client in tests; the SDK brings pydantic
        return None

    class Priority(BaseModel):
        finding_ids: List[str]
        title: str
        why: str
        step_ids: List[str]

    class Notes(BaseModel):
        headline: str
        summary: str
        priorities: List[Priority]
        listen_for: List[str]
        strengths: List[str]

    return Notes


def check(notes, inp):
    """Drop ids that don't exist in the input and list what was wrong. Returns (notes, issues)."""
    findings = {f["id"]: f for f in inp["findings"]}
    steps = {s["id"] for f in inp["findings"] for s in f["steps"] + f["other_options"]}
    issues, kept = [], []
    for p in notes["priorities"]:
        bad_f = [i for i in p["finding_ids"] if i not in findings]
        bad_s = [i for i in p["step_ids"] if i not in steps]
        issues += [{"type": "unknown_finding", "id": i} for i in bad_f]
        issues += [{"type": "unknown_step", "id": i} for i in bad_s]
        p = {**p, "finding_ids": [i for i in p["finding_ids"] if i in findings],
             "step_ids": [i for i in p["step_ids"] if i in steps]}
        if p["finding_ids"]:
            kept.append(p)
        else:
            issues.append({"type": "priority_dropped", "title": p["title"]})
    covered = {i for p in kept for i in p["finding_ids"]}
    issues += [{"type": "missed_critical", "id": fid} for fid, f in findings.items()
               if f["severity"] == "critical" and fid not in covered]
    return {**notes, "priorities": kept}, issues


def write_notes(report, client=None, model_id=None):
    """Ask Claude for engineer's notes on a report.

    Returns {"notes", "issues", "input", "model", "prompt_version", "usage", "stop_reason"}.
    Raises NotesUnavailable with a plain-English reason when it can't.
    """
    if client is None:
        ok, why = available()
        if not ok:
            raise NotesUnavailable(why)
        import anthropic
        client = anthropic.Anthropic()
    model_id = model_id or model()
    inp = notes_input(report)
    try:
        response = client.beta.messages.parse(
            model=model_id,
            max_tokens=MAX_TOKENS,
            # The prompt never changes, so it's marked for caching. It's short, so it may fall under
            # the model's minimum cacheable size; check usage.cache_read_input_tokens before counting on it.
            system=[{"type": "text", "text": PROMPT_FILE.read_text(encoding="utf-8"), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": "MixCheck analysis:\n" + json.dumps(inp, indent=1, ensure_ascii=False)}],
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            output_format=_schema(),
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except Exception as exc:
        raise _plain_error(exc) from exc

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise NotesUnavailable(f"The notes couldn't be written (stop reason: {response.stop_reason}).")
    notes, issues = check(response.parsed_output.model_dump(), inp)
    usage = response.usage
    return {
        "notes": notes,
        "issues": issues,
        "input": inp,
        "model": getattr(response, "model", model_id),
        "prompt_version": PROMPT_VERSION,
        "stop_reason": response.stop_reason,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
        },
    }


def _plain_error(exc):
    """An SDK error as a NotesUnavailable the user can act on; anything unexpected passes through."""
    try:
        import anthropic
    except ImportError:
        return exc
    # With no credentials at all, the SDK raises TypeError before sending anything.
    if isinstance(exc, TypeError) and "authentication" in str(exc):
        return NotesUnavailable(
            "No Anthropic API key found. Set ANTHROPIC_API_KEY in the Terminal window you start Seraphim from "
            "(or run `ant auth login`), then start it again.")
    if isinstance(exc, anthropic.AuthenticationError):
        return NotesUnavailable(
            "Anthropic rejected the API key. It may have been copied incompletely or deleted; "
            "create a new one in the Anthropic console and set ANTHROPIC_API_KEY again.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return NotesUnavailable(f"This API key isn't allowed to use {model()}. Check the key's workspace in the Anthropic console.")
    if isinstance(exc, anthropic.RateLimitError):
        return NotesUnavailable("The AI service is busy right now. Try again in a minute.")
    if isinstance(exc, anthropic.APIConnectionError):
        return NotesUnavailable("Couldn't reach the AI service. Check your internet connection.")
    if isinstance(exc, anthropic.BadRequestError) and "credit balance" in str(exc).lower():
        return NotesUnavailable("Your Anthropic account is out of credit. Add some under Billing in the Anthropic console.")
    if isinstance(exc, anthropic.APIStatusError):
        return NotesUnavailable(f"The AI service returned an error ({exc.status_code}): {getattr(exc, 'message', exc)}")
    return exc


def format_notes(result):
    """Plain-text notes for the terminal, with step ids turned back into the steps themselves."""
    n, inp = result["notes"], result["input"]
    steps = {s["id"]: s["text"] for f in inp["findings"] for s in f["steps"] + f["other_options"]}
    lines = [n["headline"], "", n["summary"]]
    if n["priorities"]:
        lines.append("")
        for k, p in enumerate(n["priorities"], 1):
            lines.append(f"{k}. {p['title']}")
            lines.append(f"   {p['why']}")
            lines += [f"   -> {steps[s]}" for s in p["step_ids"]]
    for title, items in (("Listen for", n["listen_for"]), ("Already working", n["strengths"])):
        if items:
            lines += ["", f"{title}:"] + [f"  - {x}" for x in items]
    return "\n".join(lines)
