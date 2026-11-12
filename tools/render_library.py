"""Write docs/library-draft.md from mixcheck/library/causes.json, for review and mark-up.

    python3 tools/render_library.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mixcheck import library  # noqa: E402
from mixcheck.observations import CHAIN  # noqa: E402

data = library.load()
out = ["# Explanation library: draft for review", "",
       f"Status: **{data['status']}**. {data['note']}", "",
       "Mark each entry: keep, change (write the change), or drop. Add what is missing.", ""]
for no in sorted(CHAIN):
    entries = [e for e in data["entries"] if e["stage_no"] == no]
    if not entries:
        continue
    out += [f"## Stage {no}: {CHAIN[no]}", ""]
    for e in entries:
        out += [f"### {e['id']}  (`{'`, `'.join(e['applies_to'])}`; scope {e['scope']})", "",
                f"**Issue.** {e['issue']}", "", "**Why it likely happened** (most usual first):"]
        for c in e["causes"]:
            up = " *(upstream)*" if c["upstream"] else ""
            ask = f" Ask: {c['ask']}" if c.get("ask") else ""
            out.append(f"- [{c['likelihood']}] {c['cause']}{up}{ask}")
        out += ["", f"**Fix actions.** {', '.join(e['fix_actions'])}"]
        if e["vigil"]:
            out += ["", "**Vigil (next time).**"] + [f"- {v}" for v in e["vigil"]]
        out += ["", f"**Check.** {e['check']}", "", "Your verdict: keep / change / drop", ""]
(ROOT / "docs" / "library-draft.md").write_text("\n".join(out), encoding="utf-8")
print(f"wrote docs/library-draft.md ({len(data['entries'])} entries)")
