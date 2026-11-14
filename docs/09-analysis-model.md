# Analysis model: groundwork (as of 2026-11-13)

Planning document. Nothing here is built yet beyond what's marked existing. Follows from Tyler's 2026-11-13 test
of Gemini for audio analysis (results were poor) and his decision to build Seraphim's own analysis model.
Team: 4 engineers, each with their own computer and repo access.

## What the analysis model is for

It does an engineer's first listen on a bounce: it reads each frequency band on its own, then reads the bands
together, then names the individual issues. Its output goes to the reasoning model (the AI mix agent in
06-ai-architecture.md), which explains the cause and the fix. The analysis model never gives advice. It reports
what is in the audio, with evidence and confidence.

## Why a general audio LLM failed

Gemini-style models turn audio into a summary that's good for "what is this song" and bad for "how many dB at
250 Hz, and when". They aren't calibrated to dB, LUFS or Hz, they can't report timestamps reliably, and they make
up plausible-sounding problems. That breaks the rule in 06: **code decides what's true**.

## The model is three layers, not one network

Training one network from scratch on raw audio would need hundreds of thousands of labeled mixes, and Seraphim
has none yet. So the model is built in layers. Each layer does what it's best at, and only the last one is trained.

| Layer | What it does | How it's built | Trust (see 06) |
|---|---|---|---|
| A. Measurement | Per-band and whole-mix numbers over time | Deterministic DSP (extends the existing engine) | Level 1: fact |
| B. Elements | Splits the bounce into vocals, drums, bass/808, other, and finds where each one sits | A source-separation model (see licensing), plus layer A run on each stem | Estimate, labeled as such |
| C. Perception | Detects issues that thresholds can't catch (mud, harshness, masking, vocal buried, over-compression) and rates how bad they are | Small trained classifiers on layer A (and later B) features | Probability with confidence; never overrides layer A |

The reasoning model only ever sees the structured output of A to C, never the audio.

### Layer A: measurement, band by band, then together

**Band plan (one shared definition, replacing the two current ones).** Today `bands.py` (5 tone bands, edges at
100/300/2k/6k Hz) and `spectrum.py` (5 bands, edges at 60/250/2k/6k Hz) disagree. Replace both with one
`bands.py` that has two resolutions:

- **Engineer bands (what users read):** sub 20–60, bass 60–120, low-mids 120–250, mud 250–500, box 500–1k,
  mids 1–2k, presence 2–4k, bite 4–6k, sibilance 6–10k, air 10–20k Hz. The current 5 tone bands stay as
  groupings of these, so style targets and references keep working.
- **Fine bands (what detectors use):** 1/3-octave (31 bands), plus a high-resolution spectrum for narrow
  resonances.

**Per band, on its own (each over time, in short windows of about 400 ms, plus a whole-song summary):**

| Measure | What it catches |
|---|---|
| Level relative to the song's loudness, and versus the sub-genre target and references | Too much or too little of a range |
| Band dynamics: crest factor and short-term loudness range | Over-compressed lows, uncontrolled low end, flat top end |
| Band stereo: correlation, side-to-mid ratio, balance | Wide or out-of-phase lows, lopsided highs |
| Narrow peaks: points sticking out above the smoothed spectrum (prominence, Q, how long they last) | Resonances, ringing, room modes, harsh tones |
| Transient versus sustained energy | Kick and snare punch versus wash |
| How the band moves over time (variance, sections where it jumps) | A vocal that gets harsh in the chorus, an 808 that swells |

**Together (relationships between bands):**

| Measure | What it catches |
|---|---|
| Spectral tilt (slope in dB per octave) versus target | Overall too dark or too bright |
| Ratios between neighboring bands (sub/bass, low-mid/mids, presence/mids, sibilance/presence) | Mud, honk, thin mids, harshness, sibilance |
| Spectral flatness and contrast | Dense wall of sound versus clear separation |
| Band-to-band level correlation over time | One element pumping others (sidechain, limiter) |
| Comparison to the whole mix's loudness and dynamics | Where the overall loudness actually comes from |

### Layer B: elements

A bounce has no stems, but most mix complaints are about elements ("vocal too low", "808 eats the kick").
Separating the bounce into 4 stems and running layer A on each one unlocks:

- Vocal level relative to the beat, over time
- Masking: where two stems compete in the same bands at the same time (vocal versus mids/presence, kick versus 808)
- Per-element sibilance, harshness and low-end correlation

Separation leaks, so every element measure is marked as an estimate. When the user uploads real stems, those
replace the separated ones (matches the "stems" row in 06's information-request table).

**Which separator:** see Licensing. Off-the-shelf pretrained separators are for internal experiments only until
a commercially clean option is chosen.

### Layer C: perception

Things a threshold can't decide well: is that 250 Hz bump "mud" or just a warm record? The perception layer
answers with a probability and a severity.

- **Inputs:** layer A features (per band, over time), later layer B features (per stem). No third-party
  pretrained audio embedding in the shipped model for now (see Licensing); revisit only for a commercially
  licensed one that beats the feature-only model on the test set.
- **Model:** gradient-boosted trees on the features first (fast, small data, explainable, trains on a laptop),
  then compare a small neural head. Only move to the bigger one if it wins on the test set.
- **Output per issue:** probability, severity (minor, worth fixing, must fix), the bands, the time ranges, the
  elements involved, and the features that drove it (so the reasoning model can cite evidence).

## Output contract: analysis report v2

The JSON report stays the contract between layers. v2 adds:

```json
{
  "bands": {"engineer": [{"id": "mud", "lo_hz": 250, "hi_hz": 500,
             "level_db_rel": -6.1, "target_delta_db": 2.4, "crest_db": 9.8, "lra_lu": 3.1,
             "correlation": 0.93, "side_mid_db": -18.0, "balance_db": 0.2,
             "transient_ratio": 0.12, "level_std_db": 1.4,
             "timeline": {"t_s": [0.0, 0.4], "level_db_rel": [-6.4, -6.0], "crest_db": [9.9, 9.6],
                          "transient_ratio": [0.1, 0.14], "correlation": [0.93, 0.92],
                          "side_mid_db": [-18.2, -17.9], "balance_db": [0.2, 0.1]}}],
           "fine": {"center_hz": [20, 25], "level_db_rel": [-21.1, -16.9],
                    "timeline": {"t_s": [0.0, 0.4], "level_db_rel": [[-22.8, -17.7], [-27.2, -15.7]]}}},
  "relations": {"tilt_db_per_oct": -4.2, "ratios": {"low_mids_to_mids_db": 3.1}, "flatness": 0.21},
  "resonances": [{"hz": 3150, "prominence_db": 7.5, "q": 9, "time_ranges_s": [[42.0, 61.5]], "element": "vocals"}],
  "elements": {"source": "separated|user_stems", "vocals": {"level_vs_beat_db": -3.0, "bands": "..."}},
  "masking": [{"a": "vocals", "b": "other", "band": "presence", "time_ranges_s": [[30, 58]], "overlap": 0.71}],
  "issues": [{"issue_id": "uuid", "category": "mud_low_mids", "probability": 0.82, "severity": "worth_fixing",
              "bands": ["mud", "low_mids"], "elements": ["other"], "time_ranges_s": [[0, 182]],
              "evidence": ["bands.engineer.mud.target_delta_db", "relations.ratios.low_mids_to_mids_db"],
              "detector_version": "perc-0.1"}]
}
```

Timelines are stored as columns: one list per measure with one entry per window (about 400 ms), which is
about a third of the size of one object per window. Silent windows are `null`. The fine bands' timeline is one
row of 31 levels per window. (The example is shortened to two windows and two fine bands.)

Issue categories reuse the `missed_issues.category` list in 08-feedback-data.md, so model output and human
labels use one vocabulary.

## Where it runs (decided 2026-11-13)

**Split by job: the product analyzes locally; the team shares data and training in AWS.**

| Job | Where | Why |
|---|---|---|
| Analyzing a user's bounce (layers A, B, C inference) | The user's computer, as today | Keeps the "audio never leaves your computer" promise; layer A and tree models are light. Measure layer B speed on a Mac before shipping it |
| Development and tests | Each engineer's computer | Same as now |
| Training data (licensed source audio, degraded clips, extracted features) | One shared S3 bucket, versioned, Identity Center access only | All 4 engineers train and test on the same data; laptops don't each hold hundreds of GB |
| Dataset versions | A manifest in the repo (file list + hashes + license per source) | Any result can be traced to exact data, and the license of every file is on record |
| Training | Laptops for tree models; on-demand AWS GPU (spot EC2 or a SageMaker training job) only when a neural model is tried, shut down after | No always-on cost |
| Trained models | Versioned in S3, pinned by version in the repo, bundled with the app | The app works offline; every result carries `detector_version` |

This fits 07 (AWS) and 08 (feedback bucket) without needing the hosted app. Hosting the analysis itself stays
a later decision.

## Licensing (decided 2026-11-13: commercially clean only)

Rule: **anything that ends up in the shipped model, or in data used to train it, must allow commercial use.**
Non-commercial (NC) or "research only" material may be used only for internal experiments that never feed a
shipped model, and is kept out of the shared training bucket. Not legal advice; get a lawyer's review before
public launch.

| Source | Status | Use |
|---|---|---|
| Seraphim's own DSP code (layer A) | Owned | Use |
| Own multitracks recorded by the team (for example at the studio), with written artist consent covering ML training | Owned with consent | Best source for vocals and real hip-hop mixes; get the consent form in place first |
| Slakh2100 | CC BY 4.0 (attribution) | Use; instrumental only, no vocals |
| SPDMX | Reported as CC BY 4.0 (released 2026) | Check the license file before use; likely instrumental |
| Synthetic test signals and synthesized stems | Owned | Use |
| MUSDB18 / MUSDB18-HQ | Educational, non-commercial | Do not use for shipped models |
| MedleyDB | CC BY-NC-SA 4.0 | Do not use for shipped models |
| MERT embedding models | CC BY-NC 4.0 | Do not use |
| Pretrained Demucs (HTDemucs) weights | Code is MIT; the weights' terms are disputed (some sources say MIT, others research-only/NC because of MUSDB training data) | Internal experiments only until confirmed in writing or replaced |
| Commercial releases (calibration songs) | Copyrighted | Numbers only, as today; never train on the audio |

**Layer B plan under this rule:** train Seraphim's own separator with the MIT Demucs code on clean data (own
multitracks for vocals, Slakh for instruments), or license a commercial separation SDK. Decide after measuring
how much the own-data separator needs.

## Training plan (next phase, outlined here so groundwork fits it)

1. **Synthetic degradation, the main source of labels.** Take clean, well-mixed multitracks and mixes from the
   allowed sources above, inject known problems at known strengths (boost 250–500 Hz, add a 3 kHz resonance,
   flip phase below 120 Hz, crush with a compressor, push the vocal down 4 dB, widen the lows, clip), and record
   what was done. Every clip comes labeled for free.
2. **Human labels.** The 4 engineers grade real bounces using the feedback records in 08 (agree, disagree,
   severity, missed issues). These correct what synthetic data gets wrong about what actually sounds bad, and
   engineer-to-engineer agreement sets the accuracy ceiling.
3. **Outcome labels.** Whether the next bounce fixed the flagged issue (outcome records in 08).

**Splits:** by song, never by clip, so the same song never appears in training and test.

## Measuring accuracy

| Layer | Metric | How |
|---|---|---|
| A | Error against known signals (dB, Hz, LUFS) | Extend `tests/test_measurements.py` with band, resonance and band-stereo test signals |
| B | Separation quality and per-stem level error | Mix known stems, separate, compare |
| C | Precision and recall per category, severity accuracy, calibration (does 0.8 mean right 80% of the time) | Held-out synthetic set and an engineer-labeled set, reported separately |
| C | Agreement with engineers versus engineer-to-engineer agreement | The ceiling; two engineers won't agree 100% either |
| End to end | Share of flagged issues improved on the next bounce | Outcome records |

Improving accuracy: tune each category's decision threshold on the engineer-labeled set; send low-confidence and
disagreed cases to engineers to label first (active learning); retrain when enough new labels arrive; version
every detector so results trace back to it (`detector_version`, as 08 requires).

## Groundwork build order

1. Unify `bands.py` and `spectrum.py` into the two-resolution band plan; keep the 5 tone bands as groupings.
2. Layer A per-band measures and band timelines; test signals for each.
3. Layer A relationships and resonance finder.
4. Report v2 schema, with the old fields kept so the current UI and notes still work.
5. Shared S3 training bucket and dataset manifest (with a license column); artist consent form for own multitracks.
6. Degradation generator (the synthetic-label factory) and a small validation set to prove it.
7. Layer C baseline: rules on layer A features first, as the bar a trained model must beat; then trees.
8. Layer B: own separator vs licensed SDK decision; per-stem measures and masking.
9. Then the training phase.

## Open decisions

- **Trust level for layer C.** This adds a learned, probabilistic source to 06's order of trust. Proposed: below
  measurements, above the model's general knowledge, always shown with confidence.
- **Layer B source:** own-trained separator or licensed SDK.
