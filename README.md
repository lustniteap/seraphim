<p align="center"><img src="mixcheck/web/static/seraphim-mark.svg" alt="Seraphim" width="180"></p>

# Seraphim

*Give your mix wings.*

Automated technical QC for mixes and masters. Point it at a bounce and it measures
what a mastering engineer checks before signing off, then flags problems with timestamps
and tells you how to fix them with your own tools.

The look is a futuristic throne room, taken from the descriptions in Revelation 4, Ezekiel 1 and Isaiah 6,
in red, black and white only: a **sea of glass** (the floor under the light, a dark crystal grid with the
waveform reflected in it), **smoke filling the temple** (haze drifting behind the glass panels), **wheels
within wheels** set with points of light and **seven lamps of fire** while a bounce is checked (one lamp per
stage, lit as the server finishes it), and a halo around the score that closes at 10.

The name comes from the seraphim of Isaiah 6: six-winged "burning ones" around the throne, one of
whom purifies with a coal from the altar. That's the aim here: take a rough mix and refine it until
it's worthy. The mark is a seraph's six wings around a halo, drawn in the same red blades as before.

Seraphim was called MixCheck. The Python package, the `mixcheck` commands and `~/.mixcheck` keep
their names, so existing installs, scripts and saved settings keep working; `seraphim`,
`seraphim-web` and `seraphim-calibrate` are the same commands under the new name.

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
| Vocal (optional, estimated) | Compression (loud words vs the typical word, peak-to-average), mud, body, rumble, harsh 's' sounds, and vocal level against the beat, measured on the vocal split from the mix |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate (PowerShell: .venv\Scripts\Activate.ps1)
pip install -e .
```

## Web interface

On a Mac, double-click `Seraphim.command` in Finder. On a Windows PC, double-click `Seraphim.bat` in File
Explorer. The first run sets up Python packages (about a minute); after that it opens straight to the page.
Keep the window it opens while you use Seraphim, and close it to quit. Launching it again while it's running
just reopens the page.

**On Windows you need Python 3.9 or newer.** If `Seraphim.bat` doesn't find it, it opens the download page.
Install it from python.org and, on the installer's first screen, tick **Add python.exe to PATH**. Then
double-click `Seraphim.bat` again. Windows may show a SmartScreen or firewall prompt the first time; Seraphim
only listens on this computer, so there's nothing to allow beyond that.

Or from a terminal:

```bash
pip install -e ".[web]"
seraphim-web
```

A browser tab opens at http://127.0.0.1:8000. Drag a bounce onto the page (or choose a file) and you get:

- a loudness timeline across the whole track, with phase problems and clipping marked where they happen
- meter readouts for integrated loudness, true peak, loudness range, PLR, correlation and mono loss
- a checklist of findings (the hard technical facts) and observations (measurements against a style, a reference or the vocal, with no severity), each with fix steps written for your DAW and plugins
- a comparison with up to three reference songs, if you add them (see below)
- streaming normalization, stereo details and tonal balance

On first launch it asks which DAW and plugins you use; change it any time from the top of the page.
It also guesses whether the file is a mix or a master, and you can switch with one click.
The server only listens on 127.0.0.1, so it isn't reachable from other machines, and uploads are
deleted as soon as they're analyzed.

API: `POST /api/analyze` with a multipart `file` field (plus optional `setup` JSON, `stage`, `target` and
`references` JSON) returns the JSON report; with `progress=1` it streams newline-delimited JSON instead,
`{"stage": ...}` as each part finishes (loudness, peaks, stereo, tone, edges, style, references), then
`{"report": ...}` or `{"error": ...}`, which is what lights the page's seven lamps; `POST /api/fixes` with `{flags, setup, stage, target, measures,
profile, references, observations}` rebuilds the findings, observations and fixes without re-analyzing; `POST /api/reference` with a `file`
returns a reference profile; `GET`/`PUT /api/reference-sets` and `DELETE /api/reference-sets/{name}` list,
save and delete reference sets; `GET /api/info` returns the version and setup options.

## Command line

```bash
seraphim my_mix.wav                          # summary in the terminal
seraphim my_mix.wav --json reports/mix.json  # also save the full report
seraphim my_mix.wav --print-json             # JSON to stdout (for piping)
```

## Windows and Mac

Seraphim runs on Windows and macOS. The analysis, fixes, scores, references, styles and the page are the
same on both; only the start file differs. Linux isn't supported yet: it starts, but isn't tested there.

- **There is no plugin scan.** The user picks their DAW and plugins from a searchable list (see below), so
  nothing is installed, scanned or allowed in system settings. Logic Pro is Mac only, so the Windows setup
  screen doesn't offer it.
- **Building the plugin list.** `python3 tools/list_installed_plugins.py > my-plugins.json` is a one-off tool for
  whoever is building the list: it prints the names, vendors, formats and versions of the plugins installed on
  that computer (no file paths, nothing sent anywhere). Its Windows folder names are from how these programs
  normally install and haven't been checked on a real PC; the output says which folders it found.
- Text files are always read and written as UTF-8 (a test fails if new code forgets), and command-line
  output is switched to UTF-8, because Windows otherwise defaults to a legacy code page that can't show the
  minus sign or angle quotes this app uses.
- The tests run on Windows and macOS, on Python 3.9 and 3.13, on every push (`.github/workflows/tests.yml`).
  On Windows that includes running `Seraphim.bat`'s setup, starting the real server and analyzing an upload
  (`tests/smoke_server.py`). To run the tests yourself: `pip install -e ".[web,dev]"` then
  `python tests/test_measurements.py`.

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

## Checking the vocal (optional, estimated)

A mix with a raw vocal can pass every technical check: no clipping, no phase problems, clean edges. The
vocal's compression, mud and level are hidden under the beat in a stereo bounce. Turn on **Check the vocal
too** (web page) or pass `--split-vocal` (command line) and Seraphim splits the vocal from the beat with
the Demucs source-separation model, then measures the vocal on its own.

```bash
# One-time install (large download: PyTorch plus the model, a few GB; the model's weights, about 80 MB,
# download on first use). On a Mac, double-click "Install Vocal Splitting.command" instead.
pip install -e ".[web,separate]"

seraphim my_mix.wav --split-vocal
```

It runs on this computer, and the audio never leaves it. A few minutes per song on a laptop CPU.

**These are estimates.** The split leaves some of the beat in the vocal and takes some of the vocal's low
end and reverb, so results are more accurate with the acapella and the beat uploaded separately (planned).
Every vocal observation is marked "Estimate" and the numbers are shown on the page. The limits in
`mixcheck/vocal.py` are starting points, not yet calibrated against real releases; tune them against your own
bounces. The vocal estimates are observations, so they never cost technical points.

## Technical score and style match

Seraphim keeps two kinds of "good" apart.

**Technical score (1.0–10.0, red → yellow → green)** counts only errors that are wrong in any genre:
peaks and clipping, phase and mono problems, and file/edge problems. It starts at 10 and loses points
per finding, scaled by how bad the measurement is, in capped areas so one kind of problem can't sink
the whole score. It also shows the score after fixing everything but notes. Rules: `mixcheck/score.py`.
Its labels say only what was found ("No technical errors found", "Minor technical issues", and so on). A clean
score is not a verdict on the mix: a mix with no plugins on it can score 10. "Ready for Wings" can only come
from the reasoning step's verdict, and code checks the conditions first: a score of 9.0 or more, no open
diagnoses, and no floor finding at warning level or worse.

**Style match (%)** compares loudness, punch (PLR) and contrast (LRA) with what the user is going for:
Hip-hop / rap, EDM, Pop, Rock / metal, R&B / soul, Acoustic / jazz, Lo-fi, or Film / classical.
A −6 LUFS master is right for hip-hop and wrong for jazz, so these never cost technical points. For a mix,
loudness isn't compared (mastering sets it) and punch is judged against looser ranges. Lo-fi doesn't
flag a dull top end. Where a measure sits outside the style's range it becomes an **observation** ("Loudness is
-12.0 LUFS; the range for Drill is -9 to -6"), tagged to a stage of the signal chain and with fix steps for the
user's tools. An observation is not an error and carries no severity.
The built-in ranges in `mixcheck/style.py` are starting points from common practice. Calibrating a
style with real releases (below) replaces them and adds tone targets.

Each style has **sub-genres** (31 in all, such as Drill or Boom bap under Hip-hop / rap, or House under
EDM), picked from the same menu. A sub-genre is only listed where its loudness, punch, contrast or tone
should differ from its parent's. Until a sub-genre has ranges of its own it uses its parent's, and
the page says so. Every range also says where it came from: a built-in estimate, **rough** (measured from
fewer than 8 songs), **calibrated** (8 or more), or inherited from the parent style.

```bash
seraphim my_master.wav --style hiphop_rap
seraphim my_master.wav --style hiphop_rap.drill   # a sub-genre: parent.sub
```

The old id `trap_hiphop` still works everywhere (the command line, saved calibrations and the style the
page remembers); it is now `hiphop_rap`, and Trap is one of its sub-genres.

### Calibrating styles with real releases

`seraphim-calibrate` measures released songs in each style and sets that style's ranges from them.
Put 10–20 songs per style in subfolders named after the styles (`hip-hop`, `trap`, `edm`, `pop`, `rock`,
`rnb`, `acoustic`, `jazz`, `lofi`, `film`, or the style ids). A bare name such as `trap` or `jazz` means the
whole parent style. To calibrate a sub-genre, put a folder named for it inside its parent's
(`hip-hop/drill/`, `hip-hop/boom_bap/`) or use `--style hiphop_rap.drill=FOLDER`; songs directly in the
parent's folder calibrate the parent. Then:

```bash
seraphim-calibrate ~/Music/refs --dry-run    # measure and show the new ranges without saving
seraphim-calibrate ~/Music/refs              # save them
seraphim-calibrate --style edm=~/Music/club  # add or redo one style
seraphim-calibrate --show                    # the ranges in use now, and where they came from
seraphim-calibrate --reset                   # back to the built-in ranges
```

- Songs are measured on your computer the same way a bounce is: loudness, punch (PLR), contrast (LRA),
  and tone in five bands on the loudest sections at matched volume. Audio is never copied or kept.
- Each range is the middle of the songs (15th to 85th percentile), widened to a minimum width
  (2 LU loudness, 2 dB punch, 3 LU contrast, 3 dB per tone band) and rounded outward to 0.5.
- A style needs at least 5 usable songs (`--min-songs` to change it); songs under 30 s are skipped.
  Styles you don't calibrate keep their current ranges.
- The report shows old and new ranges side by side, and names songs that fall outside the new ranges on
  two or more measures, in case they're in the wrong folder.
- Calibrated styles are also judged on **tone**: "5.7 dB lighter below 100 Hz than typical for Hip-hop /
  rap", with an EQ step for your tools. Lo-fi still isn't flagged for a dark top end.
- Results go to `~/.mixcheck/style_targets.json` (or `$MIXCHECK_HOME`) and apply straight away in the web
  page and the command line. Measurements are cached, so re-running after adding songs is quick.

## Reference tracks

Drop in 1–3 released songs you want to sound like, and Seraphim compares them with your bounce
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
(2–6 kHz) and highs (above 6 kHz). Like style, reference differences are observations and never cost technical points.

Only a small profile of numbers is kept for each reference, never the audio, so a **reference set** can
be saved under a name and reused. Sets live in `~/.mixcheck/reference_sets.json` (or `$MIXCHECK_HOME`)
and are shared between the web page and the command line. On the page, add songs with the button or
by dropping them on the Reference tracks panel; the set you're using is remembered for the next bounce.

```bash
seraphim my_mix.wav --ref ref1.wav --ref ref2.flac --save-ref-set "Club refs"
seraphim my_mix.wav --ref-set "Club refs"
```

## Engineer's notes (optional, AI-written)

With `--notes`, Claude turns the report into short notes like a mastering engineer would write: the headline,
what to fix first and why, which findings share a cause, and what to listen for afterwards.

```bash
pip install -e ".[ai]"                 # the only part of Seraphim that needs the anthropic package
export ANTHROPIC_API_KEY=...           # or: ant auth login
seraphim my_mix.wav --notes
```

In the web page, the same notes come from the **Write engineer's notes** button under the verdict. It shows
only when the `ai` extra is installed; start Seraphim from a Terminal window where `ANTHROPIC_API_KEY` is set
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
  Seraphim prints the normal report and a one-line reason.

## Evaluating the notes

`evals/` measures how good the engineer's notes are, so prompt changes are decided by numbers rather than by
reading a couple of outputs.

**Cases.** Every report in `evals/reports/` (real bounces, numbers only) and `evals/synthetic/` (bounces built
to trigger known problems, from `evals/make_synthetic.py`), each judged three ways (`evals/scenarios.py`): as
recorded, as the other stage with a different toolset, and against a style target.

**Checks** (`evals/graders.py`, free and exact):

| check | passes when |
|---|---|
| `ids_valid` | the notes only point at findings and fix steps that exist |
| `covers_critical` / `covers_warnings` | every critical / warning finding is in some priority |
| `numbers_grounded` | every number-with-unit quoted appears in the report with that unit (honest rounding allowed) |
| `tools_owned` | every plugin or brand named is one the user owns |
| `stage_appropriate` | a mix isn't told to push its loudness or limiting |
| `no_invented_problems` | a clean report gets no priorities |

**Judge** (`evals/judge.py`, optional, `--judge`): a different model grades priority order, whether each
priority explains its impact, grouping of shared causes, specificity, stage fit, faithfulness and concision,
with a fixed rubric and structured output. `label` and `agreement` check it against your own grades.

```bash
python evals/notes_eval.py run --fake oracle   # harness self-test: should pass (no key, no cost)
python evals/notes_eval.py run --fake null     # harness self-test: coverage should fail
python evals/notes_eval.py run --limit 6       # pilot with Claude (asks before spending)
python evals/notes_eval.py run --judge         # the full baseline
python evals/notes_eval.py summary             # scores with 95% intervals, and every failure with its reason
```

Results land in `evals/runs/notes/<variant>/` (per-case rows, full traces, errors kept apart from scores);
each prompt change is a new `--variant` (v1, v2...), and `evals/FAILURE_LOG.md` records what failed, why,
and what fixed it.

**Ratings from the web page.** Under each set of engineer's notes, a thumbs up or down asks "Were these notes
useful?". On a thumbs down, optional reasons say what was wrong, in plain words that map to the judge's
criteria (made something up → `faithful`, wrong thing first → `priority_order`, too long → `concise`, and so on),
so a rating with reasons doubles as a hand label. Pressing the same thumb again takes the rating back.

- Ratings stay on this computer, in `~/.mixcheck/notes_feedback.jsonl`, next to the measurements the notes were
  written from. Nothing is sent anywhere, and there's no free-text box, which is the one place a song title
  could slip in.
- **Export my ratings** (under the thumbs) downloads `feedback-<name>.jsonl`: the rating, the reasons, the notes
  and the measurements they came from, the day (not the time), and never audio or a file name. Put the file in
  `evals/feedback/`; one file per person, so nobody's files collide.
- `python evals/notes_eval.py feedback` reads those files: how often notes were useful per prompt version (with
  a 95% interval) and which mistakes people named. `--local` adds this computer's own ratings.

These are opinions on real bounces, so they show what people find useful and which mistakes they notice. They
don't replace the hand labels that check the judge.

**Adding real bounces.** Save reports, then strip song titles before committing:

```bash
seraphim bounce.wav --daw pro_tools --plugins waves_essential --json evals/reports/NAME.json
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
these Waves plugins (L2, F6, Renaissance EQ and Compressor, S1 Stereo Imager and Shuffler, PAZ Analyzer,
WLM Plus), FabFilter, and iZotope Ozone/Insight.

**Setup screen.** The user picks a DAW, then searches a list of plugins and chooses the ones they own; their
choices appear as chips they can remove. There is no scan: a list the person picks from needs no system
permissions, costs no computation, can't fail halfway, and is as reliable about what they own as a scan would be
(installed isn't licensed). The list is `PACKAGES` (plugins Seraphim writes fix steps for) plus `LISTED` (plugins
people can pick that have no steps yet, so the steps stay generic until they're added; marked "general steps
only"). A plugin that isn't listed can be reported with "I don't see mine"; the name is kept in
`~/.mixcheck/plugin_requests.jsonl` on that computer, as the backlog for what to add next. The person can add
**Waves Essential** or **Waves Ultimate** in one step, which chooses the plugins it includes (from Waves' own
plugin list, `WAVES_TIERS` in `catalog.py`), then removes what they don't have. S1 Shuffler isn't in either
bundle, so it's chosen alone. The old `waves_essential` id still works and stands for L2, F6 and the two
Renaissance plugins, so saved setups and scripts keep working.

From the command line:

```bash
seraphim my_mix.wav --daw logic --plugins fabfilter,izotope_ozone --stage mix
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
