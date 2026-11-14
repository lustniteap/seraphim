"""The dataset manifest: every training file, its hash and its license (docs/09, "Where it runs").

The manifest lives in the repo; the audio lives in the shared bucket. Any result can then be traced
to exact data, and the license of every file is on record. The licensing rule of docs/09 is
enforced here: only sources that allow commercial use may be in the manifest.

    python -m training.manifest build <folder> --source own_multitracks --out training/manifest.json
    python -m training.manifest check training/manifest.json

A folder is one song: split_by_song() keeps every clip of a song on the same side of the split.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

MANIFEST_VERSION = 1
AUDIO = {".wav", ".aif", ".aiff", ".flac"}

# source id -> (license, may it train a shipped model?, note). From the table in docs/09.
SOURCES = {
    "own_multitracks": ("owned-with-consent", True, "Recorded by the team; needs the signed artist consent form."),
    "synthetic": ("owned-synthetic", True, "Test signals and synthesized stems (training/synth.py)."),
    "slakh2100": ("CC-BY-4.0", True, "Attribution required. Instrumental only."),
    "spdmx": ("CC-BY-4.0", True, "Check the license file in the download before use."),
    "musdb18": ("non-commercial", False, "Educational, non-commercial."),
    "medleydb": ("CC-BY-NC-SA-4.0", False, "Non-commercial."),
    "commercial_release": ("copyrighted", False, "Numbers only (calibration); never train on the audio."),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(folder, source, consent_ref=None):
    """Manifest entries for every audio file under folder. The first folder level is the song."""
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r}. Add it to SOURCES with its license first.")
    license_, allowed, _ = SOURCES[source]
    if not allowed:
        raise ValueError(f"{source} ({license_}) does not allow commercial use, so it can't go in the manifest.")
    if source == "own_multitracks" and not consent_ref:
        raise ValueError("Own multitracks need consent_ref: the id of the signed consent form covering them.")
    folder = Path(folder)
    files = []
    for path in sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO):
        rel = path.relative_to(folder)
        files.append({
            "path": rel.as_posix(), "song_id": rel.parts[0] if len(rel.parts) > 1 else rel.stem,
            "sha256": sha256(path), "bytes": path.stat().st_size,
            "source": source, "license": license_, **({"consent_ref": consent_ref} if consent_ref else {}),
        })
    return {"manifest_version": MANIFEST_VERSION, "files": files}


def check(manifest, folder=None):
    """Problems with a manifest, as a list of sentences (empty when it is fine).
    With folder, also checks that each file is there and still has the recorded hash."""
    problems, seen = [], set()
    for f in manifest.get("files", []):
        name = f.get("path", "?")
        source = SOURCES.get(f.get("source"))
        if source is None:
            problems.append(f"{name}: unknown source {f.get('source')!r}.")
        elif not source[1]:
            problems.append(f"{name}: {f['source']} ({source[0]}) does not allow commercial use.")
        elif f.get("license") != source[0]:
            problems.append(f"{name}: license {f.get('license')!r} doesn't match {f['source']} ({source[0]}).")
        if f.get("source") == "own_multitracks" and not f.get("consent_ref"):
            problems.append(f"{name}: own multitrack without a consent form reference.")
        if not f.get("song_id") or len(f.get("sha256", "")) != 64:
            problems.append(f"{name}: needs a song_id and a sha256.")
        if name in seen:
            problems.append(f"{name}: listed twice.")
        seen.add(name)
        if folder is not None:
            path = Path(folder) / name
            if not path.is_file():
                problems.append(f"{name}: missing from {folder}.")
            elif sha256(path) != f.get("sha256"):
                problems.append(f"{name}: the file has changed since the manifest was written.")
    return problems


def split_by_song(song_ids, test_share=0.2):
    """{"train": [...], "test": [...]} of song ids. By song, never by clip (docs/09), and decided by
    a hash of the id, so a song stays on its side when the dataset grows."""
    out = {"train": [], "test": []}
    for sid in sorted(set(song_ids)):
        bucket = int(hashlib.sha256(str(sid).encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        out["test" if bucket < test_share else "train"].append(sid)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build or check the training dataset manifest.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("folder")
    b.add_argument("--source", required=True, choices=sorted(SOURCES))
    b.add_argument("--consent-ref")
    b.add_argument("--out", default="training/manifest.json")
    c = sub.add_parser("check")
    c.add_argument("manifest")
    c.add_argument("--folder")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        manifest = build(args.folder, args.source, args.consent_ref)
        Path(args.out).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print(f"{len(manifest['files'])} files written to {args.out}")
        return 0
    problems = check(json.loads(Path(args.manifest).read_text(encoding="utf-8")), args.folder)
    print("\n".join(problems) or "The manifest is fine.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
