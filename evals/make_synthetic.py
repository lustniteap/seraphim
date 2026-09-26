"""Build synthetic eval reports with known problems (deterministic; no real music needed).

    python evals/make_synthetic.py        # writes evals/synthetic/*.json

Each bounce is generated to trigger specific findings, so the answer is known: notes on the
polarity-flipped mix must cover the polarity problem, notes on the clean master must not invent
one. They complement the real-bounce reports in evals/reports, which are realistic but messy.
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mixcheck.analyze import analyze_file  # noqa: E402
from mixcheck.reference import measure_profile  # noqa: E402

FS = 44100
OUT = Path(__file__).parent / "synthetic"
SETUP = {"daw": "pro_tools", "packages": ["waves_essential"]}


def song(seed, seconds=40, level_db=-18.0, width=0.35, bass_db=0.0):
    """Noise shaped roughly like a song: a pink-ish spectrum, quieter verses, louder choruses, a fade."""
    rng = np.random.default_rng(seed)
    n = FS * seconds
    mid, side = rng.standard_normal(n), width * rng.standard_normal(n)
    x = np.column_stack([mid + side, mid - side])
    spec, f = np.fft.rfft(x, axis=0), np.fft.rfftfreq(n, 1 / FS)
    spec /= np.sqrt(np.maximum(f, 20.0))[:, None]  # pink-ish
    spec[f < 20] = 0  # no DC or subsonic rumble, which would trigger findings of their own
    spec[(f >= 20) & (f < 100)] *= 10 ** (bass_db / 20)
    x = np.fft.irfft(spec, n=n, axis=0)
    sections = np.repeat([0.5, 1.0, 0.55, 1.0, 0.6, 1.0], int(np.ceil(n / 6)))[:n]
    x *= np.convolve(sections, np.ones(FS) / FS, mode="same")[:, None]  # smooth section changes
    x *= np.minimum(1.0, np.linspace(40, 0, n))[:, None]  # fade out over the last 2.5%
    return x * 10 ** (level_db / 20) / np.sqrt(np.mean(x ** 2))


def limit(x, ceiling_db=-1.5, drive_db=0.0):
    """A crude limiter: soft saturation to a ceiling, for loud masters."""
    c = 10 ** (ceiling_db / 20)
    return np.tanh(x * 10 ** (drive_db / 20) / c) * c


def cases():
    ref = measure_profile(limit(song(90, level_db=-10), drive_db=6), FS, "Reference 1")
    yield "clean_master", limit(song(1, level_db=-14), drive_db=0), "master", None
    yield "clipped_master", np.clip(song(2, level_db=-7), -1, 1), "master", None
    flipped = song(3)
    flipped[:, 1] *= -1
    yield "polarity_mix", flipped, "mix", None
    wide = song(4)
    rng = np.random.default_rng(40)
    lows = np.fft.irfft(np.fft.rfft(rng.standard_normal((len(wide), 2)), axis=0)
                        * (np.fft.rfftfreq(len(wide), 1 / FS) < 120)[:, None], n=len(wide), axis=0)
    lows[:, 1] *= -1  # bass that cancels in mono
    yield "wide_bass_mix", wide + lows * 0.6 * np.sqrt(np.mean(wide ** 2)) / np.sqrt(np.mean(lows ** 2)), "mix", None
    yield "limited_mix", limit(song(5, level_db=-8), drive_db=8), "mix", None
    cut = song(6)
    cut = cut[: int(len(cut) * 0.9)]  # stops mid-chorus, before the fade
    yield "cutoff_mix", cut, "mix", None
    yield "light_lows_master", limit(song(7, level_db=-10, bass_db=-5), drive_db=6), "master", [ref]


def main():
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, audio, stage, refs in cases():
            path = Path(tmp) / f"{name}.wav"
            sf.write(path, audio, FS, subtype="PCM_24")
            report = analyze_file(path, setup=SETUP, stage=stage, references=refs)
            (OUT / f"{name}.json").write_text(json.dumps(report, indent=2))
            print(f"{name:20} {stage:6} " + ", ".join(f"{f['id']}({f['severity'][0]})" for f in report["flags"]))


if __name__ == "__main__":
    main()
