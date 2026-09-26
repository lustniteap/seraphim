# MixCheck

Automated technical QC for mixes and masters. Point it at a bounce and it measures
what a mastering engineer checks before signing off, then flags problems with timestamps.

**Phase 1 (this version):** the analysis engine: measurements plus rule-based findings, output as JSON.
**Phase 2:** an LLM turns the JSON into plain-English notes, written like a mastering engineer (started: `--notes`).
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
- a comparison with up to three reference songs, if you add them (see below)
- streaming normalization, stereo details and tonal balance

On first launch it asks which DAW and plugins you use; change it any time from the top of the page.
It also guesses whether the file is a mix or a master, and you can switch with one click.
The server only listens on 127.0.0.1, so it isn't reachable from other machines, and uploads are
deleted as soon as they're analyzed.

API: `POST /api/analyze` with a multipart `file` field (plus optional `setup` JSON, `stage`, `target` and
`references` JSON) returns the JSON report; `POST /api/fixes` with `{flags, setup, stage, target, measures,
profile, references}` rebuilds findings and fixes without re-analyzing; `POST /api/reference` with a `file`
returns a reference profile; `GET`/`PUT /api/reference-sets` and `DELETE /api/reference-sets/{name}` list,
save and delete reference sets; `GET /api/info` returns the version and setup options.

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
audio file ──► analysis engine ──► JSON report (schema v1.2) ──► terminal summary (cli.py)
                     ▲                                      ├──► web UI (web/server.py + static/index.html)
reference songs ──► profiles (reference.py)                 └──► AI report (Phase 2), plugin (later)
                     └─ saved as reference sets (refsets.py)
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
The built-in ranges in `mixcheck/style.py` are starting points from common practice. Calibrating a
style with real releases (below) replaces them and adds tone targets.

```bash
mixcheck my_master.wav --style trap_hiphop
```

### Calibrating styles with real releases

`mixcheck-calibrate` measures released songs in each style and sets that style's ranges from them.
Put 10–20 songs per style in subfolders named after the styles (`trap`, `hip-hop`, `edm`, `pop`, `rock`,
`rnb`, `acoustic`, `jazz`, `lofi`, `film`, or the style ids), then:

```bash
mixcheck-calibrate ~/Music/refs --dry-run    # measure and show the new ranges without saving
mixcheck-calibrate ~/Music/refs              # save them
mixcheck-calibrate --style edm=~/Music/club  # add or redo one style
mixcheck-calibrate --show                    # the ranges in use now, and where they came from
mixcheck-calibrate --reset                   # back to the built-in ranges
```

- Songs are measured on your computer the same way a bounce is: loudness, punch (PLR), contrast (LRA),
  and tone in five bands on the loudest sections at matched volume. Audio is never copied or kept.
- Each range is the middle of the songs (15th to 85th percentile), widened to a minimum width
  (2 LU loudness, 2 dB punch, 3 LU contrast, 3 dB per tone band) and rounded outward to 0.5.
- A style needs at least 5 usable songs (`--min-songs` to change it); songs under 30 s are skipped.
  Styles you don't calibrate keep their current ranges.
- The report shows old and new ranges side by side, and names songs that fall outside the new ranges on
  two or more measures, in case they're in the wrong folder.
- Calibrated styles are also judged on **tone**: "5.7 dB lighter below 100 Hz than typical for Trap /
  hip-hop", with an EQ step for your tools. Lo-fi still isn't flagged for a dark top end.
- Results go to `~/.mixcheck/style_targets.json` (or `$MIXCHECK_HOME`) and apply straight away in the web
  page and the command line. Measurements are cached, so re-running after adding songs is quick.

## Reference tracks

Drop in 1–3 released songs you want to sound like, and MixCheck compares them with your bounce
across **loudness, punch, contrast, tone and width**. Findings and fixes then read relative to them:
"3.3 dB lighter below 100 Hz than your reference", fixed with "In Pro-Q on the master, add a low shelf
over the lows (below 100 Hz) and raise it about 3.5 dB".

How the comparison stays fair (`mixcheck/reference.py`):

- **Loudest sections.** Each song is measured where its short-term loudness is within 3 LU of its
  near-loudest level: the chorus or drop, where people actually compare songs. A quiet intro or
  breakdown doesn't skew the result.
- **Matched volume.** Tone is each band's level relative to the song's own loudness, so a quieter
  bounce isn't called "lighter" just for being quieter. Punch (peak over the loud sections), contrast
  (loudness range) and width (side vs mid) don't depend on level either. Only loudness itself does.
- **Several references.** Values are compared with the references' average; anywhere within their
  spread, plus a tolerance, counts as a match. The reference match (%) averages the five dimensions.
- **Mix or master.** A mix isn't compared on loudness, and it's expected to keep 2–6 dB more punch
  than the finished masters it's compared with.

Tone uses five bands: lows (below 100 Hz), low mids (100–300 Hz), mids (300 Hz–2 kHz), presence
(2–6 kHz) and highs (above 6 kHz). Like style, reference findings never cost technical points.

Only a small profile of numbers is kept for each reference, never the audio, so a **reference set** can
be saved under a name and reused. Sets live in `~/.mixcheck/reference_sets.json` (or `$MIXCHECK_HOME`)
and are shared between the web page and the command line. On the page, add songs with the button or
by dropping them on the Reference tracks panel; the set you're using is remembered for the next bounce.

```bash
mixcheck my_mix.wav --ref ref1.wav --ref ref2.flac --save-ref-set "Club refs"
mixcheck my_mix.wav --ref-set "Club refs"
```

## Engineer's notes (optional, AI-written)

With `--notes`, Claude turns the report into short notes like a mastering engineer would write: the headline,
what to fix first and why, which findings share a cause, and what to listen for afterwards.

```bash
pip install -e ".[ai]"                 # the only part of MixCheck that needs the anthropic package
export ANTHROPIC_API_KEY=...           # or: ant auth login
mixcheck my_mix.wav --notes
```

In the web page, the same notes come from the **Write engineer's notes** button under the verdict. It shows
only when the `ai` extra is installed; start MixCheck from a Terminal window where `ANTHROPIC_API_KEY` is set
(or put the key in `~/.zprofile`). Changing the stage, style, references or setup marks the notes as out of date.

How it's kept honest (`mixcheck/notes.py`, prompt in `mixcheck/prompts/notes.md`):

- The engine stays the source of truth. Claude gets a trimmed copy of the report: numbers, findings and the
  fix steps already chosen for your tools, each with an id (F1, F1.1...). No audio and no file name are sent.
- The notes come back in a fixed structure (Pydantic, via structured outputs) and point at findings and steps
  by id instead of inventing fixes. Ids that don't exist are dropped and recorded as issues, and a critical
  finding the notes skip is flagged too.
- The prompt is versioned (`PROMPT_VERSION`) so changes can be measured against evaluations.
- Model `claude-opus-5` with adaptive thinking at medium effort (`MIXCHECK_AI_MODEL` to change it), with the
  API's refusal fallback turned on. `MIXCHECK_AI=off` disables notes everywhere. Without the package or a key,
  MixCheck prints the normal report and a one-line reason.

## Evaluation reports

`evals/reports/` holds JSON reports from real bounces (numbers only, no audio): the inputs the notes are
evaluated on. Before committing new ones, strip song titles:

```bash
mixcheck bounce.wav --daw pro_tools --plugins waves_essential --json evals/reports/NAME.json
python evals/anonymize.py     # NAME.json -> song01.json, titles replaced inside too
```

Which song is which stays in `~/.mixcheck/eval-song-names.txt` on your computer.

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
