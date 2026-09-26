"""Command line: mixcheck path/to/mix.wav [--json report.json]"""
import argparse
import json
import sys

from .analyze import analyze_file
from .catalog import DAWS, PACKAGES
from .style import TARGETS

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
        print(f"  Style match           {sm['percent']}% to {sm['name']}")
        for d in sm["dims"]:
            where = "in range" if d["status"] == "in" else f"{d['off_by']:.1f} {'below' if d['status'] == 'low' else 'above'}"
            print(f"    {d['name']:<18}{d['value']:>6.1f} {d['unit']:<7} target {d['low']:g} to {d['high']:g}  ({where})")
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mixcheck", description="Technical QC for mixes and masters.")
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
    parser.add_argument("--no-fixes", action="store_true", help="Hide fix suggestions in the summary")
    args = parser.parse_args(argv)

    packages = [p.strip() for p in args.plugins.split(",") if p.strip()]
    unknown = [p for p in packages if p not in PACKAGES]
    if unknown:
        parser.error(f"unknown plugin package(s): {', '.join(unknown)}. Choose from: {', '.join(sorted(PACKAGES))}")
    try:
        report = analyze_file(args.file, setup={"daw": args.daw, "packages": packages},
                              stage=args.stage, target=args.style)
    except Exception as exc:  # show a clean message rather than a traceback
        print(f"mixcheck: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=2)
    if args.print_json:
        print(json.dumps(report, indent=2))
    else:
        print_summary(report, show_fixes=not args.no_fixes)
        if args.json:
            print(f"  Full report written to {args.json}\n")
