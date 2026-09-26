"""Replace song titles in eval reports with song01, song02, ... before they're committed.

    python evals/anonymize.py            # every report in evals/reports
    python evals/anonymize.py FOLDER     # another folder

Each report's file is renamed (40nites-Facecard-....json -> song01.json) and every place
the title appears inside it is replaced: file.name, profile.name, and the names of any
reference songs. Which song is which is written to ~/.mixcheck/eval-song-names.txt on this
computer only, never inside the repo. Reports that are already anonymized are left alone,
so it's safe to run again after adding more.
"""
import json
import re
import sys
from pathlib import Path

ANON = re.compile(r"^song\d+$")
MAPPING = Path.home() / ".mixcheck" / "eval-song-names.txt"


def scrub(report, new_name):
    """Replace every title in one report, in place. Returns the titles that were removed."""
    old = []
    f = report.get("file") or {}
    if f.get("name"):
        old.append(f["name"])
        f["name"] = f"{new_name}.wav"
    if report.get("profile"):
        report["profile"]["name"] = f"{new_name}.wav"
    for i, ref in enumerate((report.get("reference") or {}).get("references") or [], 1):
        if ref.get("name"):
            old.append(ref["name"])
            ref["name"] = f"Reference {i}"
    return old


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "reports"
    reports = sorted(folder.glob("*.json"))
    if not reports:
        sys.exit(f"No reports in {folder}")
    done = [p for p in reports if ANON.match(p.stem)]
    todo = [p for p in reports if not ANON.match(p.stem)]
    next_n = max((int(p.stem[4:]) for p in done), default=0) + 1

    MAPPING.parent.mkdir(parents=True, exist_ok=True)
    with open(MAPPING, "a") as log:
        for path in todo:
            new = f"song{next_n:02d}"
            next_n += 1
            report = json.loads(path.read_text())
            titles = scrub(report, new)
            text = json.dumps(report, indent=2)
            # Belt and braces: the old title must not survive anywhere in the file.
            # Short stems like "mix" are ordinary words in every report, so only distinctive ones count.
            leftovers = [t for t in titles if t in text or (len(Path(t).stem.strip()) >= 6 and Path(t).stem.strip() in text)]
            if leftovers:
                sys.exit(f"{path.name}: a title still appears inside the report ({leftovers[0]}); nothing changed.")
            (folder / f"{new}.json").write_text(text)
            path.unlink()
            log.write(f"{new}\t{titles[0] if titles else path.name}\n")
            print(f"{path.name} -> {new}.json")
    print(f"\n{len(todo)} report(s) anonymized, {len(done)} already were. "
          f"Which song is which: {MAPPING} (on this computer only).")


if __name__ == "__main__":
    main()
