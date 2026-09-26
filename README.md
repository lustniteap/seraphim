# MixCheck

Automated technical QC for mixes and masters. Point it at a bounce and it measures
what a mastering engineer checks before signing off, then flags problems with timestamps.

**Phase 1 (this version):** the analysis engine: measurements plus rule-based findings, output as JSON.
**Phase 2:** an LLM turns the JSON into plain-English notes, written like a mastering engineer.
**Phase 3:** web interface (done), a bounce-folder watcher, and later a JUCE plugin (AU/AAX).

## What it measures

| Area | Measurements |
|---|---|
| Loudness (ITU-R BS.1770-4 / EBU R128) | Integrated LUFS, max momentary and short-term, loudness range (LRA), per-second timeline |
| Peaks | Sample peak, true peak (4x oversampled), clipping runs with timestamps, DC offset |
| Dynamics | Peak-to-loudness ratio (PLR) |
| Stereo | L/R correlation, low-end (<150 Hz) correlation, mono fold-down loss, side/mid ratio, balance, time ranges with negative correlation |
| Tonal balance | Share of energy in sub / low / low-mid / high-mid / high bands, content above 16 kHz |
| Edges | Head and tail silence, abrupt endings, quietest passage |
| Streaming | Gain each platform's loudness normalization would apply |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

## Web interface

On a Mac, double-click `MixCheck.command` in Finder. The first run sets up Python packages
(about a minute); after that it opens straight to the page. Keep the Terminal window it opens
while you use MixCheck, and close it to quit. Launching it again while it's running just reopens the page.

Or from a terminal:

```bash
pip install -e ".[web]"
mixcheck-web
```

A browser tab opens at http://127.0.0.1:8000. Drag a bounce onto the page (or choose a file) and you get:

- a loudness timeline across the whole track, with phase problems and clipping marked where they happen
- meter readouts for integrated loudness, true peak, loudness range, PLR, correlation and mono loss
- a verdict and checklist of findings, with fix steps written for your DAW and plugins
- streaming normalization, stereo details and tonal balance

On first launch it asks which DAW and plugins you use; change it any time from the top of the page.
It also guesses whether the file is a mix or a master, and you can switch with one click.
The server only listens on 127.0.0.1, so it isn't reachable from other machines, and uploads are
deleted as soon as they're analyzed.

API: `POST /api/analyze` with a multipart `file` field (plus optional `setup` JSON and `stage`) returns
the JSON report; `POST /api/fixes` with `{flags, setup, stage}` rebuilds fixes without re-analyzing;
`GET /api/info` returns the version and setup options.

## Command line

```bash
mixcheck my_mix.wav                          # summary in the terminal
mixcheck my_mix.wav --json reports/mix.json  # also save the full report
mixcheck my_mix.wav --print-json             # JSON to stdout (for piping)
```

## Validation

The measurements are checked against signals with known answers:

```bash
python tests/test_measurements.py
```

This includes the ITU-R BS.1770-4 reference filter coefficients at 48 kHz, the EBU Tech 3341
sine test (a -23 dBFS stereo sine must read -23.0 LUFS), inter-sample peak detection, clipping,
polarity inversion, and the expected 3 dB mono loss of uncorrelated noise.

## Design

```
audio file ──► analysis engine ──► JSON report (schema v1.0) ──► terminal summary (cli.py)
                                                            ├──► web UI (web/server.py + static/index.html)
                                                            └──► AI report (Phase 2), plugin (later)
```

The JSON report is the contract between layers. When the engine is ported to C++ for a plugin,
the report layer stays the same.

## Technical score and style match

MixCheck keeps two kinds of "good" apart.

**Technical score (1.0–10.0, red → yellow → green)** counts only errors that are wrong in any genre:
peaks and clipping, phase and mono problems, and file/edge problems. It starts at 10 and loses points
per finding, scaled by how bad the measurement is, in capped areas so one kind of problem can't sink
the whole score. It also shows the score after fixing everything but notes. Rules: `mixcheck/score.py`.

**Style match (%)** compares loudness, punch (PLR) and contrast (LRA) with what the user is going for:
Trap / hip-hop, EDM, Pop, Rock / metal, R&B / soul, Acoustic / jazz, Lo-fi, or Film / classical.
A −6 LUFS master is right for trap and wrong for jazz, so these never cost technical points. For a mix,
loudness isn't compared (mastering sets it) and punch is judged against looser ranges. Lo-fi doesn't
flag a dull top end. Findings like "Louder than your style" come with fix steps for the user's tools.
The ranges in `mixcheck/style.py` are starting points from common practice; tune them against real
releases. Tone (bass/treble balance) isn't judged by genre: that comes with reference tracks.

```bash
mixcheck my_master.wav --style trap_hiphop
```

## Fix suggestions for each user's setup

Fixes are built in two layers so they stay specific without being rewritten for every studio:

- `mixcheck/remediation.py` says what fixes each finding, as tool-neutral **actions**
  (`limit_true_peak`, `mono_low_end`, `clip_gain`...), separately for a **mix** and a **master**.
  Clipping in a mix headed for mastering is fixed with gain staging, not a limiter.
- `mixcheck/catalog.py` lists DAWs, plugin packages and tools, and says how each tool performs
  each action in its own words ("Put Pro-L 2 last on the master, turn on True Peak Limiting...").

For each action the best tool the user owns is chosen; their other tools for the same job go
under "More options", and anyone without a matching tool gets generic wording. Adding a plugin
is one entry in `TOOLS`. Covered now: Pro Tools, Logic Pro, Ableton Live and FL Studio stock tools,
Waves Essential plus S1 Imager/Shuffler, PAZ and WLM Plus, FabFilter, and iZotope Ozone/Insight.

From the command line:

```bash
mixcheck my_mix.wav --daw logic --plugins fabfilter,izotope_ozone --stage mix
```

`--stage auto` (the default) guesses from loudness. Use `--no-fixes` to hide the steps.
Timestamps are measured from the start of the bounced file, so they line up with the
session timeline when the bounce starts at the session start.

## Tuning

Thresholds for the findings live in `THRESHOLDS` in `mixcheck/analyze.py`, and platform loudness
targets in `STREAMING_TARGETS`. Platforms change their normalization, so verify those values against
their current documentation.

## Limitations

- Mono and stereo files only (no surround yet).
- Mono files are measured per BS.1770 as a single channel.
- Without `soundfile` installed, only WAV files can be read.
- MP3 is accepted for quick checks, but use a WAV/AIFF/FLAC bounce for final QC: the encoder
  changes true peak and tonal balance, and its padding shifts timestamps by a few tens of ms.
