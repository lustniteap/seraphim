"""The explanation library: why a finding or observation usually happens, how to fix it, and how to prevent it.

The entries are data (library/causes.json). Code looks them up by the key a finding or observation carries (a floor
id or a playbook key). A draft entry is general knowledge, never "library", until the file's status is "verified";
the reasoning step must label causes accordingly. Nothing here measures anything or writes fix steps: the fix actions
are catalog action ids, rendered for the person's setup by remediation.render_actions.
"""
import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).with_name("library") / "causes.json"


@lru_cache(maxsize=1)
def load():
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def source_label():
    """How a cause from this file must be labelled until Tyler has verified it."""
    return "library" if load().get("status") == "verified" else "general knowledge"


def entry_for(key):
    """The entry whose applies_to includes this floor id or playbook key, or None."""
    return next((e for e in load()["entries"] if key in e["applies_to"]), None)


def lookup(keys):
    """Entries for several keys, each once, in order."""
    out = []
    for k in keys:
        e = entry_for(k)
        if e and e not in out:
            out.append(e)
    return out
