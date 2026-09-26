"""Evaluate engineer's notes: run them on every eval case, grade them, and compare prompt versions.

    python evals/notes_eval.py run --fake oracle        # test the harness: should pass (no key, no cost)
    python evals/notes_eval.py run --fake null          # test the harness: coverage should fail
    python evals/notes_eval.py run                      # real notes with Claude (asks before spending)
    python evals/notes_eval.py run --judge              # ...plus the LLM judge
    python evals/notes_eval.py run --variant v1         # after changing the prompt: a new variant
    python evals/notes_eval.py summary                  # scores per variant, failures with reasons
    python evals/notes_eval.py regrade                  # re-score saved notes after a check changes (free)
    python evals/notes_eval.py label                    # grade some notes yourself...
    python evals/notes_eval.py agreement                # ...and see how often the judge agrees with you

Cases: every report in evals/reports (real bounces) and evals/synthetic (known problems), each
judged three ways (scenarios.py). Results go to evals/runs/notes/<variant>/: results.jsonl (one row
per case and rep, as each finishes), traces/ (the full input, notes and verdicts), errors.jsonl
(calls that failed; never scored), summary.md. Variants are named baseline, v1, v2...; say what
changed in <variant>/change.md.
"""
import argparse
import json
import math
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals import graders  # noqa: E402
from evals.judge import CRITERIA, DEFAULT_JUDGE, judge  # noqa: E402
from evals.scenarios import cases_for  # noqa: E402
from mixcheck import notes  # noqa: E402

EVALS = Path(__file__).parent
SOURCES = {"real": EVALS / "reports", "synthetic": EVALS / "synthetic"}
RUNS = EVALS / "runs"
DET_METRICS = ["ids_valid", "covers_critical", "covers_warnings", "numbers_grounded",
               "tools_owned", "stage_appropriate", "no_invented_problems"]
# $/million tokens (input, output), first-party API. Cache reads bill at 0.1x input.
PRICES = {"claude-opus-5": (5, 25), "claude-opus-5-5": (4, 20), "claude-sonnet-5": (2, 10), "claude-haiku-4-5": (1, 5)}


# ---------------------------------------------------------------- cases

def load_cases(only=None):
    out = []
    for source, folder in SOURCES.items():
        for path in sorted(folder.glob("*.json")):
            report = json.loads(path.read_text())
            for case_id, scenario, r in cases_for(path.stem, report):
                if only and only not in case_id:
                    continue
                out.append({"id": case_id, "report": r,
                            "tags": [source, scenario, r["stage"]["value"]]})
    return out


# ---------------------------------------------------------------- running

def cost(model, usage):
    if not usage or model not in PRICES:
        return 0.0
    pin, pout = PRICES[model]
    cached = usage.get("cache_read_input_tokens") or 0
    return ((usage.get("input_tokens", 0) - cached) * pin + cached * pin * 0.1
            + usage.get("output_tokens", 0) * pout) / 1e6


def run_case(case, rep, client, model, judge_client, judge_model):
    """One (case, rep): notes, deterministic checks, optional judge. Returns (row, trace)."""
    t0 = time.monotonic()
    result = notes.write_notes(case["report"], client=client, model_id=model)
    latency = time.monotonic() - t0
    inp = result["input"]
    grade, details = graders.grade(result, inp, case["report"]["setup"])
    row = {
        "prompt_id": case["id"], "rep": rep, "tags": case["tags"],
        "prompt": f"{case['id']}: {len(inp['findings'])} findings, {inp['stage']}, {inp['setup']}",
        "status": "truncated" if result["stop_reason"] == "max_tokens" else "ok",
        "stop_reason": result["stop_reason"], "model": model, "served_model": result["model"],
        "prompt_version": result["prompt_version"], "usage": result["usage"],
        "cost_usd": round(cost(model, result["usage"]), 5), "latency_s": round(latency, 2),
        "words": graders.length(result["notes"]), "issues": result["issues"],
        "grade": {k: v for k, v in grade.items() if v is not None}, "details": details,
    }
    trace = {"input": inp, "notes": result["notes"], "issues": result["issues"], "checks": details}
    if judge_client is not None:
        jscore, jreasons, jusage, jmodel = judge(judge_client, inp, result["notes"], judge_model)
        row["grade"].update({f"judge_{k}": v for k, v in jscore.items() if v is not None})
        row.update(judge_model=jmodel, judge_usage=jusage, judge_cost_usd=round(cost(judge_model, jusage), 5))
        trace["judge"] = jreasons
    return row, trace


def cmd_run(args):
    cases = load_cases(args.only)
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        sys.exit("No cases. Add reports to evals/reports, or run evals/make_synthetic.py.")
    flow = RUNS / (f"notes-fake-{args.fake}" if args.fake else "notes")
    out = flow / args.variant
    (out / "traces").mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    done = set()
    if results.exists():
        done = {(r["prompt_id"], r["rep"]) for r in map(json.loads, results.read_text().splitlines())}
    todo = [(c, rep) for c in cases for rep in range(args.reps) if (c["id"], rep) not in done]
    print(f"{len(cases)} cases x {args.reps} rep(s): {len(todo)} to run, {len(done)} already done -> {out}")
    if not todo:
        return summarize(flow)

    if args.fake:
        from evals.fakes import FakeClient
        client, model, judge_client = FakeClient(args.fake), f"fake-{args.fake}", None
    else:
        ok, why = notes.available()
        if not ok:
            sys.exit(why)
        import anthropic
        client = anthropic.Anthropic(timeout=300, max_retries=4)
        model = args.model or notes.model()
        judge_client = client if args.judge else None
        calls = len(todo) * (2 if args.judge else 1)
        print(f"About to make {calls} API calls: notes with {model}"
              + (f", judged by {args.judge_model}" if args.judge else "") + ".")
        if not args.yes and input("Go ahead? [y/N] ").strip().lower() != "y":
            sys.exit("Nothing run.")
    (out / "run.json").write_text(json.dumps({
        "model": model, "prompt_version": notes.PROMPT_VERSION, "judge_model": args.judge_model if judge_client else None,
        "reps": args.reps, "started": time.strftime("%Y-%m-%d %H:%M")}, indent=2))

    lock = threading.Lock()
    with ThreadPoolExecutor(args.jobs) as pool:
        futures = {pool.submit(run_case, c, rep, client, model, judge_client, args.judge_model): (c, rep) for c, rep in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            c, rep = futures[fut]
            try:
                row, trace = fut.result()
            except Exception as exc:  # a failed call is plumbing, not a model score
                with lock, open(out / "errors.jsonl", "a") as fh:
                    fh.write(json.dumps({"prompt_id": c["id"], "rep": rep, "error": type(exc).__name__,
                                         "message": str(exc)[:500], "at": time.strftime("%H:%M:%S")}) + "\n")
                print(f"  [{i}/{len(todo)}] {c['id']} rep {rep}: ERROR {type(exc).__name__}: {str(exc)[:120]}")
                continue
            with lock:
                (out / "traces" / f"{c['id']}_rep{rep}.json").write_text(json.dumps(trace, indent=1, ensure_ascii=False))
                with open(results, "a") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            failed = [k for k, v in row["grade"].items() if v < 1]
            print(f"  [{i}/{len(todo)}] {c['id']} rep {rep}: " + (f"fails {', '.join(failed)}" if failed else "all pass"))
    summarize(flow)


# ---------------------------------------------------------------- reporting

def wilson(passes, n, z=1.96):
    """95% interval for a pass rate; honest with small n, unlike +/- sqrt(p(1-p)/n)."""
    if not n:
        return 0.0, 0.0
    p = passes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def load_rows(variant_dir):
    path = variant_dir / "results.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def summarize(flow):
    variants = sorted((d for d in flow.iterdir() if d.is_dir() and (d.name == "baseline" or d.name[1:].isdigit())),
                      key=lambda d: (d.name != "baseline", int(d.name[1:]) if d.name != "baseline" else 0))
    data = {v.name: load_rows(v) for v in variants}
    metrics = DET_METRICS + [f"judge_{c}" for c in CRITERIA]
    metrics = [m for m in metrics if any(m in r["grade"] for rows in data.values() for r in rows)]
    lines = [f"# Engineer's notes eval: {flow.name}", ""]
    for name, rows in data.items():
        run = json.loads((flow / name / "run.json").read_text()) if (flow / name / "run.json").exists() else {}
        # An error only counts while that (case, rep) has no result: a later successful run supersedes it.
        done = {(r["prompt_id"], r["rep"]) for r in rows}
        err_path = flow / name / "errors.jsonl"
        err_rows = [json.loads(line) for line in err_path.read_text().splitlines()] if err_path.exists() else []
        errors = len({(e["prompt_id"], e["rep"]) for e in err_rows} - done)
        ok = [r for r in rows if r["status"] == "ok"]
        spend = sum(r.get("cost_usd", 0) + r.get("judge_cost_usd", 0) for r in rows)
        change = (flow / name / "change.md")
        lines.append(f"**{name}**: {run.get('model', '?')}, prompt {run.get('prompt_version', '?')}, "
                     f"{len(ok)} ok / {len(rows) - len(ok)} truncated / {errors} unresolved errors, ${spend:.2f}"
                     + (f"; median {median(r['latency_s'] for r in ok):.1f} s, {median(r['words'] for r in ok):.0f} words" if ok else "")
                     + (f". {change.read_text().strip().splitlines()[0]}" if change.exists() else ""))
    lines += ["", "| metric | " + " | ".join(data) + " |", "|---|" + "---|" * len(data)]
    for m in metrics:
        cells = []
        for rows in data.values():
            vals = [r["grade"][m] for r in rows if r["status"] == "ok" and m in r["grade"]]
            if not vals:
                cells.append("–")
                continue
            lo, hi = wilson(sum(vals), len(vals))
            cells.append(f"{100 * sum(vals) / len(vals):.0f}% ({100 * lo:.0f}–{100 * hi:.0f}, n={len(vals)})")
        lines.append(f"| {m} | " + " | ".join(cells) + " |")

    last, rows = next(reversed(data.items()), (None, []))
    fails = [(r, m) for r in rows for m, v in r["grade"].items() if v < 1]
    if fails:
        lines += ["", f"## Failures in {last}", ""]
        for r, m in sorted(fails, key=lambda x: (x[1], x[0]["prompt_id"]))[:60]:
            detail = r["details"].get(m)
            if detail is None and m.startswith("judge_"):
                trace = flow / last / "traces" / f"{r['prompt_id']}_rep{r['rep']}.json"
                detail = json.loads(trace.read_text()).get("judge", {}).get(m[6:], "") if trace.exists() else ""
            lines.append(f"- **{m}** · {r['prompt_id']}: {detail}")
    text = "\n".join(lines) + "\n"
    (flow / "summary.md").write_text(text)
    print("\n" + text)


def cmd_summary(args):
    summarize(RUNS / (f"notes-fake-{args.fake}" if args.fake else "notes"))


def cmd_regrade(args):
    """Re-score saved notes with the current checks, without calling Claude (free). Use after a check changes:
    stored grades are from the checks as they were when the notes were written."""
    flow = RUNS / (f"notes-fake-{args.fake}" if args.fake else "notes")
    setups = {c["id"]: c["report"]["setup"] for c in load_cases()}
    for vdir in sorted(d for d in flow.iterdir() if d.is_dir() and (d / "results.jsonl").exists()):
        rows, changed = load_rows(vdir), 0
        for r in rows:
            trace_path = vdir / "traces" / f"{r['prompt_id']}_rep{r['rep']}.json"
            if not trace_path.exists() or r["prompt_id"] not in setups:
                continue
            trace = json.loads(trace_path.read_text())
            grade, details = graders.grade({"notes": trace["notes"], "issues": trace["issues"]},
                                           trace["input"], setups[r["prompt_id"]])
            new = {**{k: v for k, v in r["grade"].items() if k.startswith("judge_")},
                   **{k: v for k, v in grade.items() if v is not None}}
            if new != r["grade"]:
                changed += 1
                print(f"  {vdir.name} {r['prompt_id']}: " + ", ".join(
                    f"{k} {r['grade'].get(k)} -> {new.get(k)}" for k in sorted(set(new) | set(r["grade"]))
                    if new.get(k) != r["grade"].get(k)))
            r["grade"], r["details"] = new, details
            trace["checks"] = details
            trace_path.write_text(json.dumps(trace, indent=1, ensure_ascii=False))
        (vdir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        print(f"{vdir.name}: {changed} of {len(rows)} rows changed")
    summarize(flow)


# ---------------------------------------------------------------- human labels

def cmd_label(args):
    """Grade notes yourself on the judge's criteria, to check the judge agrees with you."""
    out = RUNS / "notes" / args.variant
    rows = load_rows(out)
    labels_path = out / "labels.jsonl"
    labelled = {json.loads(line)["prompt_id"] for line in labels_path.read_text().splitlines()} if labels_path.exists() else set()
    todo = [r for r in rows if r["prompt_id"] not in labelled and r["rep"] == 0]
    random.Random(7).shuffle(todo)
    print(f"{len(labelled)} labelled so far. For each criterion type p (pass), f (fail), n (n/a); Enter skips; q quits.\n")
    rubric = {line.split(":")[0].strip("- "): line.split(":", 1)[1].strip()
              for line in (EVALS / "prompts" / "judge_notes.md").read_text().splitlines() if line.startswith("- ")}
    for r in todo[:args.n]:
        trace = json.loads((out / "traces" / f"{r['prompt_id']}_rep0.json").read_text())
        inp, n = trace["input"], trace["notes"]
        print("=" * 78, f"\n{r['prompt_id']}  ({inp['stage']}, {inp['setup']})\nFindings:")
        for f in inp["findings"]:
            print(f"  {f['id']} [{f['severity']}] {f['measured']}")
        print(f"\nNOTES\n{notes.format_notes({'notes': n, 'input': inp})}\n")
        labels = {}
        for c in CRITERIA:
            ans = input(f"  {c} ({rubric.get(c, '')[:70]}...) [p/f/n]: ").strip().lower()
            if ans == "q":
                return
            if ans in ("p", "f", "n"):
                labels[c] = {"p": 1.0, "f": 0.0, "n": None}[ans]
        with open(labels_path, "a") as fh:
            fh.write(json.dumps({"prompt_id": r["prompt_id"], "labels": labels}) + "\n")


def cmd_agreement(args):
    out = RUNS / "notes" / args.variant
    labels = {json.loads(line)["prompt_id"]: json.loads(line)["labels"]
              for line in (out / "labels.jsonl").read_text().splitlines()}
    rows = {r["prompt_id"]: r for r in load_rows(out) if r["rep"] == 0}
    print(f"{len(labels)} cases labelled by you\n")
    print(f"{'criterion':20} {'agree':>7}  {'n':>3}  judge said pass/you said fail, and the reverse")
    for c in CRITERIA:
        pairs = [(lab[c], rows[pid]["grade"].get(f"judge_{c}")) for pid, lab in labels.items()
                 if c in lab and pid in rows and f"judge_{c}" in rows[pid]["grade"] and lab[c] is not None]
        if not pairs:
            print(f"{c:20} {'–':>7}")
            continue
        agree = sum(h == j for h, j in pairs)
        lenient = sum(h == 0 and j == 1 for h, j in pairs)
        strict = sum(h == 1 and j == 0 for h, j in pairs)
        print(f"{c:20} {100 * agree / len(pairs):6.0f}%  {len(pairs):3}  {lenient} too lenient, {strict} too strict")


def main():
    p = argparse.ArgumentParser(prog="notes_eval", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="write and grade notes for every case")
    r.add_argument("--variant", default="baseline", help="baseline, v1, v2... (one per prompt version)")
    r.add_argument("--reps", type=int, default=1, help="runs per case, to measure run-to-run variation")
    r.add_argument("--model", help=f"model writing the notes (default {notes.DEFAULT_MODEL})")
    r.add_argument("--judge", action="store_true", help="also grade with the LLM judge")
    r.add_argument("--judge-model", default=DEFAULT_JUDGE)
    r.add_argument("--fake", choices=["oracle", "null", "sloppy"], help="stand-in writer, to test the harness for free")
    r.add_argument("--only", help="only cases whose id contains this")
    r.add_argument("--limit", type=int, help="only the first N cases (a pilot)")
    r.add_argument("--jobs", type=int, default=4, help="cases at once")
    r.add_argument("--yes", action="store_true", help="don't ask before spending")
    s = sub.add_parser("summary", help="scores per variant")
    s.add_argument("--fake", choices=["oracle", "null", "sloppy"])
    rg = sub.add_parser("regrade", help="re-score saved notes with the current checks (free)")
    rg.add_argument("--fake", choices=["oracle", "null", "sloppy"])
    lab = sub.add_parser("label", help="grade notes yourself")
    lab.add_argument("--variant", default="baseline")
    lab.add_argument("-n", type=int, default=15, help="how many cases this session")
    a = sub.add_parser("agreement", help="how often the judge agrees with your labels")
    a.add_argument("--variant", default="baseline")
    args = p.parse_args()
    {"run": cmd_run, "summary": cmd_summary, "regrade": cmd_regrade, "label": cmd_label,
     "agreement": cmd_agreement}[args.cmd](args)


if __name__ == "__main__":
    main()
