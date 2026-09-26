"""mixcheck-calibrate: set each style's target ranges from real releases.

Point it at a folder with one subfolder per style, holding released songs in that
style (10–20 each is plenty):

    songs/
      trap/   edm/   pop/   rock/   rnb/   acoustic/   lofi/   film/

Every song is measured on this computer the same way MixCheck measures a bounce:
integrated loudness, punch (PLR), contrast (loudness range), and tone in five bands
on the loudest sections at matched volume. Each style's range becomes the middle of
its songs (15th to 85th percentile), widened to a minimum width so a few very
similar songs can't make the target razor-thin. Styles with too few songs keep the
ranges they have.

Results go to ~/.mixcheck/style_targets.json (or $MIXCHECK_HOME), which style.py
reads, so the web page and command line use them straight away. Measurements are
cached by path, size and modification time, so re-running after adding a few songs
only measures the new ones. Audio is never copied or kept.
"""
import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from .audio_io import load_audio
from .bands import BAND_IDS, BANDS
from .loudness import measure_loudness
from .peaks import true_peak
from .reference import measure_profile
from .style import TARGETS, calibration_path, targets
from .util import db, mixcheck_home

AUDIO_SUFFIXES = {".wav", ".wave", ".aif", ".aiff", ".flac", ".mp3"}
MIN_SONGS = 5
MIN_SECONDS = 30.0
PERCENTILES = (15, 85)
# Narrowest a range may be, so a tight cluster of songs doesn't flag everything else.
MIN_WIDTH = {"lufs": 2.0, "plr": 2.0, "lra": 3.0, "tone": 3.0}
DIM_NAMES = {"lufs": ("Loudness", "LUFS"), "plr": ("Punch", "dB PLR"), "lra": ("Contrast", "LU")}
CACHE_VERSION = 1


# ---------------------------------------------------------------- measuring

def measure_song(path):
    """The numbers a style range is built from, for one released song."""
    x, fs = load_audio(path)
    if x.shape[1] > 2:
        raise ValueError(f"{x.shape[1]}-channel files aren't supported (mono or stereo only)")
    if len(x) / fs < MIN_SECONDS:
        raise ValueError(f"shorter than {MIN_SECONDS:g} s; use full songs")
    loud = measure_loudness(x, fs)
    lufs = loud["integrated_lufs"]
    if lufs is None or not math.isfinite(lufs):
        raise ValueError("silent")
    peak = max(true_peak(x[:, ch]) for ch in range(x.shape[1]))
    return {
        "lufs": round(lufs, 2),
        "plr": round(float(db(peak)) - lufs, 2),
        "lra": loud["loudness_range_lu"],
        "tone": measure_profile(x, fs)["tone_db"],
    }


def _measure_job(path):
    try:
        return path, measure_song(path), None
    except Exception as exc:  # one bad file shouldn't stop the run
        return path, None, str(exc) or exc.__class__.__name__


def cache_path():
    return mixcheck_home() / "calibration_cache.json"


def _load_json(path, default):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def measure_all(paths, jobs=None, progress=print):
    """{path: measurement or None}, plus {path: error}. Reuses the cache where the file is unchanged."""
    cache = _load_json(cache_path(), {})
    if cache.get("version") != CACHE_VERSION:
        cache = {"version": CACHE_VERSION, "songs": {}}
    songs = cache["songs"]
    results, errors, todo = {}, {}, []
    for p in paths:
        st = p.stat()
        hit = songs.get(str(p))
        if hit and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime_ns:
            results[p] = hit["m"]
        else:
            todo.append(p)
    if results:
        progress(f"  {len(results)} song(s) unchanged since last time; using their saved measurements.")

    if todo:
        progress(f"  Measuring {len(todo)} song(s)…")
        jobs = max(1, min(jobs or (os.cpu_count() or 2) - 1, len(todo)))
        pool = ProcessPoolExecutor(jobs) if jobs > 1 else None
        done = (f.result() for f in as_completed([pool.submit(_measure_job, p) for p in todo])) if pool \
            else map(_measure_job, todo)
        try:
            for i, (p, m, err) in enumerate(done, 1):
                if err:
                    errors[p] = err
                    progress(f"  [{i}/{len(todo)}] skipped {p.name}: {err}")
                    continue
                results[p] = m
                st = p.stat()
                songs[str(p)] = {"size": st.st_size, "mtime": st.st_mtime_ns, "m": m}
                progress(f"  [{i}/{len(todo)}] {p.name}")
        finally:
            if pool:
                pool.shutdown()
        try:
            _write_json(cache_path(), cache)
        except OSError:
            pass  # the cache only saves time
    return results, errors


# ---------------------------------------------------------------- ranges

def spread(values, min_width):
    """The middle of the values, at least min_width wide, rounded outward to 0.5."""
    values = [v for v in values if v is not None]
    lo, hi = (float(v) for v in np.percentile(values, PERCENTILES))
    if hi - lo < min_width:
        mid = (lo + hi) / 2
        lo, hi = mid - min_width / 2, mid + min_width / 2
    return [math.floor(lo * 2) / 2, math.ceil(hi * 2) / 2]


def style_ranges(measurements, min_songs=MIN_SONGS):
    """A style's calibrated ranges from its songs' measurements."""
    out = {dim: spread([m[dim] for m in measurements], MIN_WIDTH[dim]) for dim in ("lufs", "plr", "lra")}
    tone = {}
    for bid in BAND_IDS:
        vals = [(m.get("tone") or {}).get(bid) for m in measurements]
        vals = [v for v in vals if v is not None]
        if len(vals) >= min_songs:
            tone[bid] = spread(vals, MIN_WIDTH["tone"])
    out["tone"] = tone
    return out


def outliers(named, rg):
    """Songs outside the new range on two or more measures: maybe in the wrong folder."""
    out = []
    for name, m in named:
        misses = [DIM_NAMES[d][0].lower() for d in ("lufs", "plr", "lra")
                  if m[d] is not None and not rg[d][0] <= m[d] <= rg[d][1]]
        misses += [BANDS[b][3].lower() for b, (lo, hi) in rg["tone"].items()
                   if (m.get("tone") or {}).get(b) is not None and not lo <= m["tone"][b] <= hi]
        if len(misses) >= 2:
            out.append((name, misses))
    return out


# ---------------------------------------------------------------- folders

def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def aliases():
    """Folder names that mean each style: its id, its name, and each part of the name."""
    out = {}
    for sid, t in TARGETS.items():
        for key in [sid, t["name"], *re.split(r"/| and ", t["name"])]:
            if _norm(key):
                out[_norm(key)] = sid
    out["hiphop"], out["rap"], out["dance"], out["house"] = "trap_hiphop", "trap_hiphop", "edm", "edm"
    out["metal"], out["jazz"], out["classical"], out["soundtrack"] = "rock", "acoustic", "film", "film"
    return out


def style_for(folder_name):
    return aliases().get(_norm(folder_name))


def find_songs(folder):
    return sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in AUDIO_SUFFIXES and p.is_file())


def collect(root=None, pairs=()):
    """{style id: [song paths]} from a root folder of style subfolders and/or STYLE=FOLDER pairs."""
    groups, unknown = {}, []
    if root:
        for sub in sorted(p for p in Path(root).iterdir() if p.is_dir()):
            sid = style_for(sub.name)
            if sid is None:
                unknown.append(sub.name)
                continue
            groups.setdefault(sid, []).extend(find_songs(sub))
    for pair in pairs:
        key, _, folder = pair.partition("=")
        sid = key if key in TARGETS else style_for(key)
        if sid is None or not folder:
            raise ValueError(f"--style takes STYLE=FOLDER with a style from: {', '.join(TARGETS)}")
        groups.setdefault(sid, []).extend(find_songs(folder))
    for sid in groups:
        groups[sid] = sorted({p.resolve() for p in groups[sid]})
    return groups, unknown


# ---------------------------------------------------------------- reporting

def _fmt(r):
    return "not set" if r is None else f"{r[0]:g} to {r[1]:g}"


def print_style_report(sid, n, old, new, odd, out=print):
    name = TARGETS[sid]["name"]
    out(f"\n{name}: {n} song(s)")
    for dim, (label, unit) in DIM_NAMES.items():
        mark = "" if list(old[dim]) == new[dim] else "   (changed)"
        out(f"  {label:<10} {_fmt(old[dim]):>16} {unit:<7} -> {_fmt(new[dim])} {unit}{mark}")
    if new["tone"]:
        out("  Tone at matched volume (dB relative to loudness; new, not guessed before):")
        for bid, rg in new["tone"].items():
            out(f"    {BANDS[bid][3]:<10} {_fmt(rg)}")
    for song, misses in odd:
        out(f"  Check {song}: outside the new range for {', '.join(misses)}. Is it in the right folder?")


def show(out=print):
    """Print the ranges in use now and where they came from."""
    cal = targets()
    out(f"Style ranges in use (calibration file: {calibration_path()})")
    for sid, t in cal.items():
        source = f"measured from {t['songs']} songs" if t.get("songs") else "built-in starting points"
        out(f"\n{t['name']}  ({source})")
        for dim, (label, unit) in DIM_NAMES.items():
            out(f"  {label:<10} {_fmt(t[dim])} {unit}")
        for bid, rg in (t.get("tone") or {}).items():
            out(f"  {BANDS[bid][3]:<10} {_fmt(rg)} dB (tone)")


# ---------------------------------------------------------------- main

def calibrate(groups, min_songs=MIN_SONGS, jobs=None, dry_run=False, out=print):
    """Measure the songs, build ranges, and (unless dry_run) save them. Returns the new styles."""
    current = targets()
    saved = _load_json(calibration_path(), {})
    styles = saved.get("styles") if isinstance(saved.get("styles"), dict) else {}
    new_styles = {}
    for sid, paths in groups.items():
        name = TARGETS[sid]["name"]
        out(f"\n{name}: {len(paths)} file(s) in {', '.join(sorted({str(p.parent) for p in paths})) or '(none)'}")
        results, _ = measure_all(paths, jobs, progress=out) if paths else ({}, {})
        if len(results) < min_songs:
            out(f"  Only {len(results)} usable song(s); {min_songs} or more are needed, so {name} keeps its current ranges.")
            continue
        ms = [results[p] for p in paths if p in results]
        rg = style_ranges(ms, min_songs)
        print_style_report(sid, len(ms), current[sid], rg,
                           outliers([(p.name, results[p]) for p in paths if p in results], rg), out)
        new_styles[sid] = {"songs": len(ms), **rg, "calibrated_at": time.strftime("%Y-%m-%d")}

    if not new_styles:
        out("\nNothing to save.")
        return {}
    if dry_run:
        out("\nDry run: nothing saved.")
        return new_styles
    styles.update(new_styles)
    _write_json(calibration_path(), {"version": 1, "styles": styles})
    out(f"\nSaved to {calibration_path()}. Seraphim uses these ranges from now on "
        f"(run `seraphim-calibrate --reset` to go back to the built-in ones).")
    return new_styles


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="seraphim-calibrate",
        description="Set each style's target ranges by measuring released songs in that style.",
        epilog="Folder names can be a style id or name, e.g. trap, hip-hop, edm, pop, rock, rnb, "
               "acoustic, jazz, lofi, film. Songs are measured on this computer and never copied.")
    parser.add_argument("folder", nargs="?", help="A folder with one subfolder of songs per style")
    parser.add_argument("--style", action="append", default=[], metavar="STYLE=FOLDER",
                        help="Add a folder for one style (repeatable), e.g. --style trap_hiphop=~/refs/trap")
    parser.add_argument("--min-songs", type=int, default=MIN_SONGS,
                        help=f"Fewest songs needed to calibrate a style (default {MIN_SONGS})")
    parser.add_argument("--jobs", type=int, help="Songs to measure at once (default: CPU cores minus one)")
    parser.add_argument("--dry-run", action="store_true", help="Show the new ranges without saving them")
    parser.add_argument("--show", action="store_true", help="Print the ranges in use now and exit")
    parser.add_argument("--reset", action="store_true", help="Delete the calibration and use the built-in ranges")
    args = parser.parse_args(argv)

    if args.show:
        show()
        return
    if args.reset:
        try:
            calibration_path().unlink()
            print(f"Removed {calibration_path()}. Seraphim is back to its built-in ranges.")
        except FileNotFoundError:
            print("There was no calibration to remove; Seraphim is using its built-in ranges.")
        return
    if not args.folder and not args.style:
        parser.error("give a folder of style subfolders, or --style STYLE=FOLDER")
    if args.folder and not Path(args.folder).is_dir():
        parser.error(f"{args.folder} isn't a folder")
    try:
        groups, unknown = collect(args.folder, args.style)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    for name in unknown:
        print(f"Skipping folder {name!r}: it doesn't match a style ({', '.join(TARGETS)}).", file=sys.stderr)
    if not groups:
        parser.error("no style folders found")
    calibrate(groups, max(1, args.min_songs), args.jobs, args.dry_run)


if __name__ == "__main__":
    main()
