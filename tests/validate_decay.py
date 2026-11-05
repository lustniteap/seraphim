"""Validation table for the decay measurement: known reverb in, estimate out.

The "note" source decays slowly *by itself*, with no reverb at all. The measurement cannot tell that from a room (the
sound and the room look the same after the sound stops), so for that source it will read a tail that isn't reverb.
That is a limit of the method, and the reasoning layer has to know it: when the audio model hears plucked or held
instruments, a long tail may be theirs.

    python tests/validate_decay.py

Reports, for sources with a known decay time (and for dry ones), what the measurement said, how far off it was, and
how confident it was. Beds of steady sound at two levels stand in for a dense mix. Dry and masked cases should come
back as no measurable tail or "couldn't tell", not as a confident number.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from decay_synth import FS, sounds, with_bed, with_reverb  # noqa: E402
from mixcheck.decay import measure_decay  # noqa: E402

RT60S = [0.3, 0.6, 1.0, 1.6, 2.5]
KINDS = ["word", "hit", "note"]
BEDS = [("none", None), ("light -40 dB", -40.0), ("dense -15 dB", -15.0)]


def run(rt60s=RT60S, kinds=KINDS, beds=BEDS, seeds=(0,)):
    rows = []
    for kind in kinds:
        for bed_name, bed_db in beds:
            for rt in [None, *rt60s]:
                for seed in seeds:
                    x = with_reverb(sounds(kind, seed=seed), rt, seed=seed)
                    if bed_db is not None:
                        x = with_bed(x, bed_db, seed=seed + 7)
                    r = measure_decay(np.column_stack([x, x]), FS)
                    o = r["overall"]
                    rows.append({"kind": kind, "bed": bed_name, "truth": rt, "status": o["status"],
                                 "est": o.get("t60_s"), "conf": o["confidence"], "tail": o.get("no_measurable_tail"),
                                 "events": max((b["events"] for b in r["bands"].values()), default=0)})
    return rows


def table(rows):
    lines = [f"{'source':<6} {'bed':<13} {'true T60':>8}  {'measured':>9} {'error':>7} {'conf':>5} {'events':>6}  result"]
    for r in rows:
        truth = "dry" if r["truth"] is None else f"{r['truth']:.1f} s"
        if r["status"] != "estimated":
            meas, err, res = "-", "-", "couldn't tell"
        elif r["tail"]:
            meas, err, res = "< 0.15 s", "-", "no measurable tail" if r["truth"] is None else "MISSED TAIL"
        else:
            meas = f"{r['est']:.2f} s"
            if r["truth"] is None:
                err, res = "-", "FALSE TAIL (the source rings by itself)" if r["kind"] == "note" else "FALSE TAIL"
            else:
                e = (r["est"] - r["truth"]) / r["truth"] * 100
                err, res = f"{e:+.0f}%", "" if r["kind"] != "note" else "upper limit holds" if r["est"] >= 0.85 * r["truth"] else "BELOW TRUE"
        lines.append(f"{r['kind']:<6} {r['bed']:<13} {truth:>8}  {meas:>9} {err:>7} {r['conf']:>5.2f} {r['events']:>6}  {res}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(table(run()))
