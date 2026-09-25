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
- findings with Pro Tools/Waves fix steps
- streaming normalization, stereo details and tonal balance

Use "Plugins I own beyond Waves Essential" in the top corner to unlock tips for extra plugins.
The server only listens on 127.0.0.1, so it isn't reachable from other machines, and uploads are
deleted as soon as they're analyzed.

API: `POST /api/analyze` with a multipart `file` field returns the JSON report; `GET /api/info`
returns version, profile and the optional plugin list.

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

## Fix suggestions (Pro Tools + Waves Essential)

Every finding comes with fix steps written for Pro Tools and the Waves Essential plan, using
Pro Tools stock tools (Trim, EQ3, Pro Limiter, AudioSuite) and Essential plugins (L2, Renaissance
series, F6, SSL E-Channel, PuigTec, H-Delay, Kramer Master Tape).

Tips for plugins that may not be in Essential only appear if you say you own them:

```bash
mixcheck my_mix.wav --plugins "S1 Stereo Imager,PAZ Analyzer,WLM Plus"
```

Or set `EXTRA_PLUGINS` in `mixcheck/remediation.py` once. Use `--no-fixes` to hide the steps.
Timestamps are measured from the start of the bounced file, so they line up with the
Pro Tools timeline when the bounce starts at the session start.

The steps live in `mixcheck/remediation.py`, keyed by finding id, so a Logic Pro profile
can be added later alongside the Pro Tools one.

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
