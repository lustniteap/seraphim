"""Command line: mixcheck path/to/mix.wav [--json report.json]"""
import argparse
import json
import sys

from .analyze import analyze_file
from .remediation import DEFAULT_PROFILE, EXTRA_PLUGINS, PROFILES

ICONS = {"critical": "[!!]", "warning": "[! ]", "info": "[i ]"}


def fmt(value, unit="", spec="{:.1f}"):
    return "n/a" if value is None else spec.format(value) + unit


def print_summary(r, show_fixes=True):
    f, lo, pk = r["file"], r["loudness"], r["peaks"]
    print(f"\n{f['name']}  |  {f['sample_rate_hz']} Hz, {f['channels']} ch, {f['duration_s']:.1f} s\n")
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

    print("\n  Findings:")
    if not r["flags"]:
        print("    No technical issues found.")
    for fl in r["flags"]:
        print(f"    {ICONS[fl['severity']]} {fl['message']}")
        if show_fixes:
            for step in fl.get("remediation", []):
                print(f"         -> {step}")
    print()
    print("  Timestamps are measured from the start of the bounced file.\n")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mixcheck", description="Technical QC for mixes and masters.")
    parser.add_argument("file", help="Audio file (WAV; AIFF/FLAC/MP3 with soundfile installed)")
    parser.add_argument("--json", metavar="PATH", help="Write the full report to a JSON file")
    parser.add_argument("--print-json", action="store_true", help="Print JSON instead of the summary")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, choices=sorted(PROFILES),
                        help="Studio setup the fix suggestions are written for")
    parser.add_argument("--plugins", default="",
                        help='Extra plugins you own beyond Waves Essential, comma-separated, '
                             'e.g. "S1 Stereo Imager,PAZ Analyzer"')
    parser.add_argument("--no-fixes", action="store_true", help="Hide fix suggestions in the summary")
    args = parser.parse_args(argv)

    extras = set(EXTRA_PLUGINS) | {p.strip() for p in args.plugins.split(",") if p.strip()}
    try:
        report = analyze_file(args.file, profile=args.profile, extras=extras)
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
