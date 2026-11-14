"""Build a small labeled validation set and score a detector against it (docs/09, steps 6-7).

Every synthetic song is rendered clean and once with each degradation at a random strength. Each
clip is analyzed, the detector names its issues, and those are compared with what was done:

  recall     of the clips given a problem, how many the detector named
  precision  of the clips where the detector named a category, how many really had it
  clean      clean clips where the detector named anything (false alarms)

    python -m training.evaluate --songs 12

This scores the rules baseline (mixcheck/perception.py) on synthetic songs only. It proves the
generator and sets the bar for a trained model; it says nothing yet about real mixes.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mixcheck.analyze import analyze_file  # noqa: E402
from mixcheck.perception import DETECTOR_VERSION, detect_issues  # noqa: E402
from training.degrade import GENERATOR_VERSION, KINDS, degrade  # noqa: E402
from training.manifest import split_by_song  # noqa: E402
from training.synth import LICENSE, song  # noqa: E402


def clips(song_seeds, seconds=20.0):
    """(audio, fs, label) for every song, clean and with each degradation."""
    for seed in song_seeds:
        stems, fs = song(seed, seconds)
        for i, kind in enumerate([None, *KINDS]):
            mix, label = degrade(stems, fs, kind, seed=1000 * seed + i)
            yield mix, fs, {**label, "song_id": f"synth-{seed:04d}", "source": "synthetic", "license": LICENSE}


def run(song_seeds, detector=detect_issues, seconds=20.0, keep=None):
    """Analyze every clip. Returns rows of {label, detected: [categories], issues}."""
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, (mix, fs, label) in enumerate(clips(song_seeds, seconds)):
            path = Path(tmp) / f"clip{n}.wav"
            sf.write(path, mix, fs, subtype="FLOAT")
            report = analyze_file(path)
            issues = detector(report)
            rows.append({"label": label, "detected": sorted({i["category"] for i in issues}), "issues": issues})
            if keep is not None:
                keep.append(report)
    return rows


def score(rows):
    """Per-category recall and precision, and the false-alarm count on clean clips."""
    cats = sorted({r["label"]["category"] for r in rows if r["label"]["category"]}
                  | {c for r in rows for c in r["detected"]})
    table = {}
    for c in cats:
        has = [r for r in rows if r["label"]["category"] == c]
        said = [r for r in rows if c in r["detected"]]
        hit = sum(c in r["detected"] for r in has)
        table[c] = {"clips": len(has), "found": hit, "recall": round(hit / len(has), 2) if has else None,
                    "named": len(said),
                    "precision": round(sum(r["label"]["category"] == c for r in said) / len(said), 2) if said else None}
    clean = [r for r in rows if r["label"]["category"] is None]
    return {"categories": table, "clean_clips": len(clean), "clean_with_issues": sum(bool(r["detected"]) for r in clean)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score the rules baseline on synthetic degraded clips.")
    ap.add_argument("--songs", type=int, default=12)
    ap.add_argument("--out", help="write the per-clip labels and detections here as JSON Lines")
    args = ap.parse_args(argv)
    seeds = list(range(1, args.songs + 1))
    rows = run(seeds)
    result = score(rows)
    split = split_by_song(r["label"]["song_id"] for r in rows)
    print(f"{len(rows)} clips from {len(seeds)} synthetic songs ({len(split['train'])} train, {len(split['test'])} test); "
          f"generator {GENERATOR_VERSION}, detector {DETECTOR_VERSION}\n")
    print(f"{'category':26} {'clips':>5} {'found':>5} {'recall':>7} {'named':>6} {'precision':>10}")
    for c, v in result["categories"].items():
        fmt = lambda x: "-" if x is None else f"{x:.2f}"
        print(f"{c:26} {v['clips']:5} {v['found']:5} {fmt(v['recall']):>7} {v['named']:6} {fmt(v['precision']):>10}")
    print(f"\nclean clips with any issue named: {result['clean_with_issues']} of {result['clean_clips']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"label": r["label"], "detected": r["detected"]}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
