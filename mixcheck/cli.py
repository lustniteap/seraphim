"""Command line: mixcheck path/to/mix.wav [--json report.json]"""
import argparse
import json
import sys

from . import refsets
from .analyze import analyze_file
from .catalog import DAWS, PACKAGES
from .reference import MAX_REFERENCES, profile_file
from .style import TARGETS
from .util import utf8_console

ICONS = {"critical": "[!!]", "warning": "[! ]", "info": "[i ]"}


def fmt(value, unit="", spec="{:.1f}"):
    return "n/a" if value is None else spec.format(value) + unit


def print_summary(r, show_fixes=True):
    f, lo, pk = r["file"], r["loudness"], r["peaks"]
    print(f"\n{f['name']}  |  {f['sample_rate_hz']} Hz, {f['channels']} ch, {f['duration_s']:.1f} s\n")
    sc = r["score"]
    print(f"  Technical score       {sc['value']:.1f} / 10  ({sc['label']})")
    if sc["if_fixed"] > sc["value"]:
        print(f"  After fixing issues   {sc['if_fixed']:.1f} / 10")
    if r["style"]:
        sm = r["style"]
        source = f"ranges from {sm['songs']} songs you measured" if sm.get("songs") else "built-in ranges"
        print(f"  Style match           {sm['percent']}% to {sm['name']}  ({source})")
        for d in sm["dims"]:
            if d["id"] == "tone":
                print("    Tone at matched volume, against typical for the style:")
                rows = sm["tone"]
            else:
                rows = [d]
            for row in rows:
                where = "in range" if row["status"] == "in" else \
                    f"{row['off_by']:.1f} {'below' if row['status'] == 'low' else 'above'}"
                indent, unit = ("      ", "dB") if d["id"] == "tone" else ("    ", row["unit"])
                print(f"{indent}{row['name']:<{22 - len(indent)}}{row['value']:>6.1f} {unit:<7} "
                      f"target {row['low']:g} to {row['high']:g}  ({where})")
    if r.get("reference"):
        print_reference(r["reference"])
    print()
    print(f"  Integrated loudness   {fmt(lo['integrated_lufs'], ' LUFS')}")
    print(f"  Loudness range        {fmt(lo['loudness_range_lu'], ' LU')}")
    print(f"  Max short-term        {fmt(lo['max_short_term_lufs'], ' LUFS')}")
    print(f"  True peak             {fmt(pk['true_peak_max_dbtp'], ' dBTP', '{:+.2f}')}")
    print(f"  PLR                   {fmt(r['dynamics']['plr_db'], ' dB')}")
    if r["stereo"]:
        st = r["stereo"]
        print(f"  Correlation           {fmt(st['correlation'], '', '{:.2f}')}"
              f"  (below {st['low_end_cutoff_hz']} Hz: {fmt(st['low_end_correlation'], '', '{:.2f}')})")
        print(f"  Mono fold-down loss   {fmt(st['mono_loudness_loss_db'], ' dB')}")
    if r["streaming"]:
        print("\n  Streaming normalization (gain the platform would apply):")
        for name, s in r["streaming"].items():
            print(f"    {name:<14}{s['gain_db']:+.1f} dB")

    st = r["stage"]
    print(f"\n  Checked as a {st['value']}"
          f"{' (detected: ' + st['reason'] + ')' if st['value'] == st['detected'] else ' (you chose this)'}")
    print(f"  Fixes written for: {r['setup']['label']}")

    if r.get("vocal"):
        print_vocal(r["vocal"])

    print("\n  Findings:")
    if not r["flags"]:
        print("    No technical issues found.")
    for fl in r["flags"]:
        print(f"    {ICONS[fl['severity']]} {fl['message']}")
        if show_fixes:
            for step in fl["fix"]["steps"]:
                print(f"         -> {step['text']}")
            if fl["fix"]["more"]:
                print(f"            ({len(fl['fix']['more'])} more option(s) in the JSON report or web page)")
    print()
    print("  Timestamps are measured from the start of the bounced file.\n")


def print_vocal(v):
    print("\n  Vocal (split from the mix; estimates)")
    if not v.get("found"):
        print(f"    {v['reason']}")
        return
    rows = [("Loud words vs typical", v.get("range_db"), "dB"), ("Peaks over average", v.get("crest_db"), "dB"),
            ("Mud, 200-500 Hz", v.get("mud_db"), "dB vs mids"), ("Body, 100-250 Hz", v.get("body_db"), "dB vs mids"),
            ("Rumble, below 80 Hz", v.get("rumble_db"), "dB vs mids"), ("Sibilance, 5-9 kHz", v.get("sibilance_db"), "dB vs mids"),
            ("Vocal vs beat", v.get("vocal_to_beat_db"), "dB")]
    for name, value, unit in rows:
        if value is not None:
            print(f"    {name:<22}{value:>7.1f} {unit}")
    print(f"    {v['disclaimer']}")


def print_reference(ref):
    names = ", ".join(x["name"] for x in ref["references"])
    print(f"  Reference match       {ref['percent']}% to {names}")
    for d in ref["dims"]:
        if d["id"] == "tone":
            continue
        where = "in line" if d["status"] == "in" else f"{d['diff']:+.1f} {d['unit']} vs reference"
        print(f"    {d['name']:<18}{d['value']:>6.1f} {d['unit']:<5} reference {d['ref']:.1f}  ({where})")
    if ref["tone"]:
        print("    Tone at matched volume, against the reference:")
    for b in ref["tone"]:
        print(f"      {b['name']:<16}{b['diff']:>+6.1f} dB  ({'in line' if b['status'] == 'in' else 'off'})")
    if "loudness" in ref["skipped"]:
        print("    (Loudness isn't compared for a mix; mastering sets it.)")


def load_references(args, parser):
    """Profiles from --ref files and/or a saved --ref-set, in that order."""
    refs = []
    if args.ref_set:
        try:
            refs += refsets.get_set(args.ref_set)["references"]
        except (KeyError, ValueError) as exc:
            names = ", ".join(s["name"] for s in refsets.list_sets()) or "none saved yet"
            parser.error(f"{exc.args[0]} Saved sets: {names}.")
    for path in args.ref or []:
        try:
            refs.append(profile_file(path))
        except Exception as exc:
            print(f"mixcheck: reference {path}: {exc}", file=sys.stderr)
            sys.exit(1)
    if len(refs) > MAX_REFERENCES:
        parser.error(f"use up to {MAX_REFERENCES} reference songs (got {len(refs)})")
    if args.save_ref_set:
        if not refs:
            parser.error("--save-ref-set needs --ref files to save")
        try:
            refsets.save_set(args.save_ref_set, refs)
        except (ValueError, OSError) as exc:
            parser.error(f"couldn't save the reference set: {exc}")
    return refs


def main(argv=None):
    utf8_console()
    parser = argparse.ArgumentParser(prog="seraphim", description="Seraphim: technical QC for mixes and masters.")
    parser.add_argument("file", help="Audio file (WAV; AIFF/FLAC/MP3 with soundfile installed)")
    parser.add_argument("--json", metavar="PATH", help="Write the full report to a JSON file")
    parser.add_argument("--print-json", action="store_true", help="Print JSON instead of the summary")
    parser.add_argument("--daw", default="other", choices=sorted(DAWS),
                        help="Your DAW, so fixes use its stock tools")
    parser.add_argument("--plugins", default="",
                        help="Plugin packages you own, comma-separated: " + ", ".join(sorted(PACKAGES)))
    parser.add_argument("--stage", default="auto", choices=["auto", "mix", "master"],
                        help="Is this a mix or a master? (default: guess from loudness)")
    parser.add_argument("--style", default=None, choices=sorted(TARGETS),
                        help="What you're going for, so loudness, punch and contrast are judged against that style")
    parser.add_argument("--ref", action="append", metavar="FILE",
                        help=f"A song you want to sound like (repeat for up to {MAX_REFERENCES})")
    parser.add_argument("--ref-set", metavar="NAME", help="Compare with a saved reference set")
    parser.add_argument("--save-ref-set", metavar="NAME", help="Save the --ref songs as a reference set for later")
    parser.add_argument("--split-vocal", action="store_true",
                        help="Split the vocal out of the mix and check it (slow; needs the optional 'separate' install). "
                             "The result is an estimate.")
    parser.add_argument("--no-fixes", action="store_true", help="Hide fix suggestions in the summary")
    parser.add_argument("--notes", action="store_true",
                        help="Also write engineer's notes with Claude (optional; sends the measurements, not the audio)")
    args = parser.parse_args(argv)

    packages = [p.strip() for p in args.plugins.split(",") if p.strip()]
    unknown = [p for p in packages if p not in PACKAGES]
    if unknown:
        parser.error(f"unknown plugin package(s): {', '.join(unknown)}. Choose from: {', '.join(sorted(PACKAGES))}")
    references = load_references(args, parser)
    try:
        report = analyze_file(args.file, setup={"daw": args.daw, "packages": packages},
                              stage=args.stage, target=args.style, references=references,
                              split_vocal=args.split_vocal)
    except Exception as exc:  # show a clean message rather than a traceback
        print(f"mixcheck: {exc}", file=sys.stderr)
        sys.exit(1)

    notes = None
    if args.notes:
        from .notes import NotesUnavailable, write_notes
        try:
            notes = write_notes(report)
            report["notes"] = {k: v for k, v in notes.items() if k != "input"}
        except NotesUnavailable as exc:  # the report is still useful without them
            print(f"mixcheck: no engineer's notes: {exc}", file=sys.stderr)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    if args.print_json:
        print(json.dumps(report, indent=2))
    else:
        print_summary(report, show_fixes=not args.no_fixes)
        if notes:
            from .notes import format_notes
            print("  Engineer's notes (written by Claude from the measurements above)\n")
            print("\n".join("  " + line for line in format_notes(notes).splitlines()))
            print()
        if args.json:
            print(f"  Full report written to {args.json}\n")
