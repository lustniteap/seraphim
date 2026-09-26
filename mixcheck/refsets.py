"""Saved reference sets: named lists of reference profiles, so they can be reused.

Sets hold the profiles from reference.py (numbers only, no audio) and live in
~/.mixcheck/reference_sets.json, shared by the command line and the web page.
Set MIXCHECK_HOME to keep them somewhere else.
"""
import json
import os
import tempfile
import time

from .reference import MAX_REFERENCES, sanitize_profile
from .util import mixcheck_home

MAX_NAME = 60


def store_path():
    return mixcheck_home() / "reference_sets.json"


def _load():
    try:
        with open(store_path()) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(sets):
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temporary file and swap it in, so a crash can't leave half a file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        json.dump(sets, fh, indent=2)
    os.replace(tmp, path)


def clean_name(name):
    name = " ".join(str(name or "").split())
    if not name:
        raise ValueError("Give the reference set a name.")
    if len(name) > MAX_NAME:
        raise ValueError(f"Keep the name under {MAX_NAME} characters.")
    return name


def list_sets():
    """Saved sets, most recently saved first."""
    return sorted(_load().values(), key=lambda s: -s.get("saved_at", 0))


def get_set(name):
    s = _load().get(clean_name(name))
    if s is None:
        raise KeyError(f"No saved reference set called “{name}”.")
    return s


def save_set(name, references):
    """Save (or replace) a set of 1–3 reference profiles under a name."""
    name = clean_name(name)
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_REFERENCES:
        raise ValueError(f"A reference set holds 1 to {MAX_REFERENCES} songs.")
    entry = {"name": name, "references": [sanitize_profile(r) for r in references], "saved_at": time.time()}
    sets = _load()
    sets[name] = entry
    _write(sets)
    return entry


def delete_set(name):
    sets = _load()
    if sets.pop(clean_name(name), None) is None:
        raise KeyError(f"No saved reference set called “{name}”.")
    _write(sets)
