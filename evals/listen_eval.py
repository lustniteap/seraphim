"""Test the listener (mixcheck/listen.py) on your own labelled songs: does the audio model get the style right?

The songs are the calibration folders, so the labels are the ones you already made:

    refs/hiphop/drill/*.mp3  ->  hiphop_rap.drill

    python evals/listen_eval.py ~/Music/refs --fake            # test the harness: no key, no cost, nothing sent
    python evals/listen_eval.py ~/Music/refs --limit 3         # a few songs per style first (asks before sending)
    python evals/listen_eval.py ~/Music/refs                   # all of them
    python evals/listen_eval.py ~/Music/refs --model NAME      # another model id
    python evals/listen_eval.py ~/Music/refs --show            # print the saved summary again, for free

It sends each song's audio (16 kHz mono) to the provider with your own key (GEMINI_API_KEY). It asks first and says what
is sent. Results are saved per song in evals/runs/listen/<variant>/, so a rerun only sends new songs. It reports:
style accuracy (parent and sub-genre), whether confident answers are more accurate, which styles get confused with which,
how often the reply failed the contract checks (including quoting a number), time and cost.
"""
import argparse
import json
import random
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mixcheck import calibrate, listen  # noqa: E402
from mixcheck.style import SUBGENRES, TARGETS  # noqa: E402

RUNS = Path(__file__).parent / "runs" / "listen"
CONFIDENT = 0.7


def parent_of(sid):
    return SUBGENRES[sid]["parent"] if sid in SUBGENRES else sid


def _key(path):
    p = Path(path)
    return f"{p.name}|{p.stat().st_size}"


def load_done(folder):
    done = {}
    f = folder / "results.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("ok"):          # a failed song is tried again on the next run
                    done[row["key"]] = row
    return done


def pick(groups, limit, seed):
    rng = random.Random(seed)
    items = []
    for sid, paths in sorted(groups.items()):
        paths = list(paths)
        if limit and len(paths) > limit:
            paths = rng.sample(paths, limit)
        items += [(sid, p) for p in paths]
    return items


def score(rows):
    """Summary numbers from result rows ({truth, ok, listen, usage, reason ...})."""
    ok = [r for r in rows if r["ok"]]
    out = {"songs": len(rows), "listened": len(ok), "failed": len(rows) - len(ok)}
    out["quoted_a_number"] = sum(1 for r in rows if not r["ok"] and "measured quantity" in r.get("reason", ""))
    if not ok:
        return out
    pred = lambda r: r["listen"]["style"]["id"]  # noqa: E731
    answered = [r for r in ok if pred(r)]
    out["no_answer"] = len(ok) - len(answered)
    out["parent_correct"] = sum(1 for r in answered if parent_of(pred(r)) == parent_of(r["truth"]))
    subs = [r for r in answered if r["truth"] in SUBGENRES]
    out["sub_total"] = len(subs)
    out["sub_correct"] = sum(1 for r in subs if pred(r) == r["truth"])
    out["parent_only_answers"] = sum(1 for r in subs if pred(r) in TARGETS)
    out["in_alternatives"] = sum(1 for r in subs if pred(r) != r["truth"] and r["truth"] in r["listen"]["style"]["alternatives"])
    hi = [r for r in subs if r["listen"]["style"]["confidence"] >= CONFIDENT]
    lo = [r for r in subs if r["listen"]["style"]["confidence"] < CONFIDENT]
    out["confident"] = (len(hi), sum(1 for r in hi if pred(r) == r["truth"]))
    out["unsure"] = (len(lo), sum(1 for r in lo if pred(r) == r["truth"]))
    out["seconds"] = round(sum(r.get("seconds", 0) for r in ok) / len(ok), 1)
    out["cost"] = sum(listen.estimate_cost(r["usage"]["sent_s"]) for r in ok)
    out["sections"] = round(sum(len(r["listen"]["sections"]) for r in ok) / len(ok), 1)
    out["retried"] = sum(1 for r in ok if r.get("attempts", 1) > 1)
    conf = defaultdict(Counter)
    for r in subs:
        conf[r["truth"]][pred(r)] += 1
    out["confusion"] = {t: dict(c) for t, c in conf.items()}
    return out


def pct(a, b):
    return "n/a" if not b else f"{100 * a / b:.0f}% ({a}/{b})"


def render(s, model):
    L = [f"# Listener test: {model}", "", f"Songs: {s['songs']}. Listened: {s['listened']}. Failed: {s['failed']}"
         f" (of which quoted a number: {s['quoted_a_number']}).", ""]
    if s["listened"]:
        L += ["| Measure | Result |", "|---|---|",
              f"| Parent style right | {pct(s['parent_correct'], s['listened'] - s['no_answer'])} |",
              f"| Sub-genre right | {pct(s['sub_correct'], s['sub_total'])} |",
              f"| Answered with the parent only | {pct(s['parent_only_answers'], s['sub_total'])} |",
              f"| Right sub-genre was its second guess | {s['in_alternatives']} |",
              f"| Accuracy when confident (>= {CONFIDENT}) | {pct(s['confident'][1], s['confident'][0])} |",
              f"| Accuracy when unsure (< {CONFIDENT}) | {pct(s['unsure'][1], s['unsure'][0])} |",
              f"| Said it could not tell | {s['no_answer']} |",
              f"| Replies needing a retry | {s['retried']} |",
              f"| Sections per song (average) | {s['sections']} |",
              f"| Seconds per song (average) | {s['seconds']} |",
              f"| Estimated cost for these songs | ${s['cost']:.2f} |", "",
              "## Which styles were confused (truth -> what the model said)", ""]
        for t, c in sorted(s["confusion"].items()):
            L.append(f"- **{t}**: " + ", ".join(f"{k} x{v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="the folder of style folders you calibrated from")
    ap.add_argument("--limit", type=int, default=0, help="at most this many songs per style (random, repeatable)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2, help="songs at a time (a free key needs 1 or 2)")
    ap.add_argument("--model", default=listen.DEFAULT_MODEL)
    ap.add_argument("--provider", choices=listen.PROVIDERS, default="gemini")
    ap.add_argument("--fake", action="store_true", help="a stand-in listener: tests the harness, sends nothing")
    ap.add_argument("--variant", default="baseline", help="name for this run; results are kept per variant")
    ap.add_argument("--show", action="store_true", help="print the saved summary and stop")
    ap.add_argument("--yes", action="store_true", help="do not ask before sending audio")
    a = ap.parse_args()
    provider = "fake" if a.fake else a.provider
    folder = RUNS / (f"fake-{a.variant}" if a.fake else a.variant)
    folder.mkdir(parents=True, exist_ok=True)
    if a.show:
        s = folder / "summary.md"
        print(s.read_text(encoding="utf-8") if s.exists() else "No saved summary for this variant yet.")
        return 0

    groups, unknown = calibrate.collect(a.root)
    if unknown:
        print(f"Skipped folders that are not a style: {', '.join(unknown)}")
    items = pick(groups, a.limit, a.seed)
    if not items:
        print("No songs found. Point this at the folder that holds your style folders.")
        return 1
    done = load_done(folder)
    todo = [(sid, p) for sid, p in items if _key(p) not in done]
    est = sum(listen.estimate_cost(min(listen.MAX_SECONDS, 240)) for _ in todo)
    print(f"{len(items)} songs across {len(groups)} styles; {len(todo)} not yet tested.")
    if todo and provider == "gemini":
        print(f"\nThis sends the audio of {len(todo)} song(s), reduced to 16 kHz mono, to Google's Gemini API ({a.model}) "
              f"using your GEMINI_API_KEY.\nNothing else is sent: no file names, no report. Rough cost: about ${est:.2f} "
              f"(an estimate from the published audio price; check it on Google's pricing page).")
        if not a.yes and input("Send them? [y/N] ").strip().lower() != "y":
            print("Stopped. Nothing was sent.")
            return 1

    lock = threading.Lock()

    def one(sid, path):
        res = listen.listen_to(path, provider=provider, model=a.model)
        return {"key": _key(path), "truth": sid, "song": Path(path).name, **res}

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool, open(folder / "results.jsonl", "a", encoding="utf-8") as out:
            futs = [pool.submit(one, sid, p) for sid, p in todo]
            for i, fut in enumerate(as_completed(futs), 1):
                row = fut.result()
                with lock:
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    done[row["key"]] = row
                    print(f"[{i}/{len(todo)}] {row['song'][:60]}: " +
                          (f"{row['listen']['style']['id']} ({row['listen']['style']['confidence']})" if row["ok"]
                           else f"failed: {row['reason'][:90]}"))
    rows = [done[_key(p)] for _, p in items if _key(p) in done]
    for r, (sid, _) in zip(rows, [i for i in items if _key(i[1]) in done]):
        r["truth"] = sid   # a song moved to another folder is judged by where it is now
    report = render(score(rows), a.model if not a.fake else "fake")
    (folder / "summary.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
