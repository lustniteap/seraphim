# Seraphim contracts: who owns what, and what is handed over (draft 1, 2026-11-05)

Step 0 of the build order. The code rewrite implements this document, so it is written first. It replaces the earlier
ownership table. Where it differs from `agent-job-spec.md`, this one wins and the job spec is updated to match.

## 1. One owner per fact

| Responsibility | Owner | May the system propose changes? | Approval |
|---|---|---|---|
| Measurements (loudness, peaks, stereo, tone, contrast, decay, section measurements) | Code | No | Engineering, with tests |
| **Floors**: hard technical findings tied to a standard | Code | No | Tyler, with a standard cited |
| Workflow order, hard stops, retries, versioning, updates, failure handling | Code | No | Engineering |
| Compliance: consent, retention, deletion, access | Code | No | Tyler (and counsel) |
| Verifier: numbers, tools, ids, ownership, confidence wording | Code | Failures are logged | Engineering |
| Fix step text per DAW and plugin | Catalog (data) | Candidates from failures | Tyler |
| Style ranges and their provenance | Calibration (data) | Yes, from real releases | Tyler |
| Genre, sub-genre, instruments, sections and their labels, vocal type, qualities no measure covers | Audio model | Prompt and schema changes | Tyler |
| Significance and severity in context, readiness, causes, fix order, Vigil, questions | Reasoning model | Prompt and library changes | Tyler |
| Reading failures and proposing improvements | Reasoning model | Yes: that is its job | Tyler |

**Never crossed:** the audio model supplies no measured quantity and no "typical" numbers; the reasoning model supplies
no new facts, numbers, plugins or controls and cannot overrule a measurement or a floor; the engine makes no genre
judgement.

## 2. The floors

The 13 technical findings the score is built on. They are exact and have a standard.

- **True peak:** above −1.0 dBTP on a master is a warning (delivery specs). Above 0 dBTP is critical at any stage. On a
  mix the −1.0 note is informational, because mastering sets the final ceiling.
- Clipping, negative correlation (polarity), mono loss, wide low end, phase sections, left/right imbalance, DC offset,
  a silent file, abrupt ending, and long silence at the head or tail (the last two are notes).

The technical score counts only the floors. A "ready" verdict is the reasoning model's, and code blocks the label
"ready" unless there are no open diagnoses. Until then the label reads "No technical errors found".

Everything contextual (the style and reference findings, the `vocal_` findings) becomes an **observation**: a
measurement, the range it is compared with, the deviation, how far the range can be trusted (its provenance), and the
chain stage. An observation carries no verdict.

## 3. The chain map

Every observation, cause, fix and Vigil is tagged to a stage, so it connects to the plugin the person is using.

| No. | Stage | Checked | Plugin it connects to |
|---|---|---|---|
| 1 | Gain staging | Clipping, peaks, headroom, DC (floor) | Gain, trim, clip gain |
| 2 | Cleanup | Rumble below 80 Hz | High-pass in an EQ |
| 3 | Tone EQ | Mud, body, presence | EQ |
| 4 | Dynamics | Crest, loudness range | Compressor |
| 5 | De-essing | Sibilance | De-esser |
| 6 | Colour | Saturation, distortion character | Saturator |
| 7 | Space | Reverb and delay; the decay measurement | Reverb, delay |
| 8 | Level and balance | Vocal against the beat | Fader, bus |
| 9 | Stereo and phase | Polarity (floor), width | Imager, utility |
| 10 | Master bus | True-peak ceiling (floor), limiting, loudness | Limiter |

Each observation also has a `scope`: vocal, mix or master. Stages 2 to 5 and 8 are estimates unless the person supplies
a vocal stem.

## 4. The handoff: one case file, separate blocks

The reasoning model receives one case file made of blocks. Each block has one owner. A validator rejects a block that
uses another owner's field names or contains a quantity it does not own.

| Block | Owner | Holds |
|---|---|---|
| `source` | Code | id, duration, sample rate, channels (no file name) |
| `listen` | Audio model | genre and sub-genre guess with a confidence, instruments, sections with times and labels, vocal type, qualities no measure covers (labelled "heard, unverified") |
| `context` | Code | the chosen style and how it was chosen |
| `engine` | Code | measurements, floors, observations, section measurements, decay results, chain hypotheses |
| `user` | The person | setup, recording context, typed readings, preferences if opted in |
| `knowledge` | Data | library entries and catalog steps for what is present |
| `research` | Code | web results: source, date, domain; never a number or a control |
| `history` | Code | earlier versions of this song |

How the blocks meet:

- Audio supplies the **where**, the engine the **how much**: the audio model labels a section and the engine measures it.
- Audio supplies the **key**, the engine the **numbers**: the sub-genre selects the style ranges.
- If audio context and a measurement seem to disagree, both stay and a `disagreement` flag goes to the reasoning model.

## 5. Precedence

- **Style choice:** the person's own choice, then their reference songs, then the audio model's guess (if confident
  enough), then the parent style.
- **Reference against sub-genre:** the reference sets the target; the sub-genre ranges are a sanity check
  ("your reference is brighter than typical for this style").

## 6. Order of the work

0. This document.
1. The reverb measurement tool, standalone, tested against exactly known decay times.
2. The refactor to these contracts: first the relabel and the verdict gate, then observations, floors, action ids.
3. Tyler's method and cases, alongside everything else: the think-aloud on the zero-plugin mix, the library entries,
   the agreed mixing-quality checks.
4. The audio-understanding step: the experiment on the refactored logic.
5. The match work-up, phase 1a then 1b.
6. The reasoning layer: verifier, gateway, notes input and diagnosis format, then the system prompt tuned against
   Tyler's cases.
7. The full workflow test on Tyler's own mixes: plain-code pipeline with hard stops, loading page, case record and
   feedback, then AWS and the review queue.
8. Later: version memory, chat, resolved and preferences, accounts and the free-run gate, consent and compliance,
   hosting, pooled learning, and an own audio model.

## 7. Decisions log

- 2026-11-05: floors are the 13 technical findings; true peak −1.0 dBTP on a master.
- 2026-11-05: contextual findings become observations; the reasoning model judges them.
- 2026-11-05: the model picks action ids from the catalog; code renders the steps for the person's setup.
- 2026-11-05: the audio model gives context only; plain code sets the order and the hard stops.
- 2026-11-05: web search is allowed under limits; the audio test runs on Tyler's own mixes and keys.
- 2026-11-05: the output of a match work-up is the change to the person's chain, tested by re-rendering.
- 2026-11-05: "resolved" means no open diagnoses, or the person marks it; the score alone never decides.
- 2026-11-05: "Vigil" names the prevention section of a diagnosis.
