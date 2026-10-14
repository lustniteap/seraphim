"""Thumbs up or down on engineer's notes, kept on this computer, with an export for the eval.

A rating belongs to one set of notes (one "notes_id", made when the notes are written). It's
saved to ~/.mixcheck/notes_feedback.jsonl (or $MIXCHECK_HOME) next to the measurements the notes
were written from, so a person can later export it. Nothing is sent anywhere.

The reasons offered on a thumbs down are the eval judge's own criteria in plain words, so a rating
with reasons becomes a hand label the eval already understands. A thumbs up, or a thumbs down
without reasons, says the notes were or weren't useful overall and labels no single criterion.
There's no free-text comment on purpose: it's the one place a song title could slip into an export.

The export has the notes, the measurements they were written from and the rating, and nothing else:
no audio, no file name (notes_input never includes one), and the day instead of the time.
"""
import hashlib
import json
import secrets
import threading
from collections import OrderedDict
from datetime import datetime, timezone

from .util import mixcheck_home

# reason id -> (what the page says, the eval criterion it labels as failed; see evals/judge.py)
REASONS = {
    "made_something_up": ("It said something that isn't true", "faithful"),
    "wrong_priority": ("It put the wrong thing first", "priority_order"),
    "no_impact": ("It didn't say why a problem matters", "explains_impact"),
    "mixed_up_causes": ("It mixed up what causes what", "groups_causes"),
    "generic": ("It could be about any song", "specific"),
    "wrong_stage": ("Wrong advice for a mix or a master", "stage_appropriate"),
    "too_long": ("Too long or padded", "concise"),
}
RATINGS = ("up", "down")
REMEMBERED = 40  # recent notes kept in memory so they can be rated; older ones are gone after a restart

_recent = OrderedDict()
_lock = threading.Lock()


class Gone(KeyError):
    """The notes being rated are no longer known (the app restarted, or they're too old)."""


def feedback_file():
    return mixcheck_home() / "notes_feedback.jsonl"


def options():
    return [{"id": k, "label": label} for k, (label, _) in REASONS.items()]


def remember(result):
    """Keep a set of notes just written (write_notes() output) so it can be rated. Returns its notes_id."""
    notes_id = secrets.token_hex(8)
    with _lock:
        _recent[notes_id] = {key: result[key] for key in ("input", "notes", "model", "prompt_version")}
        while len(_recent) > REMEMBERED:
            _recent.popitem(last=False)
    return notes_id


def _read(path):
    """Every saved line, oldest first. A damaged line is skipped rather than losing the rest."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _latest(rows):
    """The last line per notes id: a changed or cleared rating replaces the earlier one."""
    by_id = {}
    for row in rows:
        by_id[row.get("id")] = row
    return list(by_id.values())


def current(path=None):
    """Ratings that stand now (cleared ones are gone), oldest first."""
    return [r for r in _latest(_read(path or feedback_file())) if r.get("rating") in RATINGS]


def stats(path=None):
    rows = current(path)
    return {"count": len(rows), "up": sum(r["rating"] == "up" for r in rows),
            "down": sum(r["rating"] == "down" for r in rows)}


def rate(notes_id, rating, reasons=()):
    """Save, change or clear (rating=None) the rating on a set of notes. Returns what stands now."""
    if rating is not None and rating not in RATINGS:
        raise ValueError("rating must be up or down")
    reasons = [r for r in dict.fromkeys(reasons or []) if isinstance(r, str)]
    unknown = [r for r in reasons if r not in REASONS]
    if unknown:
        raise ValueError(f"unknown reason: {unknown[0]}")
    if rating != "down":
        reasons = []  # reasons say what was wrong; they only go with a thumbs down

    path = feedback_file()
    with _lock:
        base = _recent.get(notes_id)
        if base is None:  # after a restart: carry the notes over from an earlier rating of the same set
            earlier = [r for r in _read(path) if r.get("id") == notes_id]
            if not earlier:
                raise Gone(notes_id)
            base = earlier[-1]
        row = {
            "id": notes_id,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rating": rating,
            "reasons": reasons,
            "prompt_version": base["prompt_version"],
            "model": base["model"],
            "input": base["input"],
            "notes": base["notes"],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"rating": rating, "reasons": reasons, **stats(path)}


def _safe_name(name):
    return "".join(ch for ch in (name or "").lower() if ch.isalnum() or ch == "-")[:30] or "me"


def export_rows(rows):
    """The shareable form of ratings: measurements, notes and the rating, with the labels it implies."""
    out = []
    for r in rows:
        out.append({
            "schema": 1,
            "id": hashlib.sha256(r["id"].encode()).hexdigest()[:12],
            "day": r["at"][:10],
            "prompt_version": r["prompt_version"],
            "model": r["model"],
            "rating": r["rating"],
            "reasons": r["reasons"],
            # Only what the person said: a reason fails its criterion; nothing else is labelled.
            "labels": {REASONS[x][1]: 0.0 for x in r["reasons"] if x in REASONS},
            "input": r["input"],
            "notes": r["notes"],
        })
    return out


def export(name=None):
    """(file name, text, count) for everything rated so far, one JSON object per line."""
    rows = export_rows(current())
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    return f"feedback-{_safe_name(name)}.jsonl", text, len(rows)


def load_exports(paths):
    """Ratings from exported or local files, the latest per set of notes, cleared ones left out."""
    rows = []
    for path in paths:
        rows += _read(path)
    return [r for r in _latest(rows) if r.get("rating") in RATINGS]
