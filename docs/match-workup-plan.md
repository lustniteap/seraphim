# Match work-up: plan (draft 1, 2026-11-05)

For Tyler's approval. **No code is written until this is approved.** It covers the "chain estimation with an ongoing
session" prompt, after the gap review of 2026-11-05. "Session" is not used here: it is reserved for Pro Tools Session
Info, so the ongoing object is called a **match work-up**.

## 1. What it does, and the framing

A person wants their mix to sound like one to three reference songs. Seraphim already measures the gap
(`mixcheck/reference.py`). The work-up goes further: it proposes a **change to the person's own chain** that closes the
measured gap, tests it by rendering it on their own audio and re-measuring with the same engine, and says how much
to trust it.

- The reference measurements are given.
- The person's own chain is known only from what they tell us (typed readings, later screenshots).
- The output is the **change** between the two, never "the reference's chain". A different song's processing cannot
  be recovered, and nothing here claims to.
- Every estimate carries a confidence, and the wording follows it (section 7).

## 2. Phases

| Phase | Contents | New dependency | Size |
|---|---|---|---|
| **1a** | `ChainHypothesis`; the `eq_match` estimator; a renderer interface with our own EQ renderer; the closed loop; the validation harness | none (scipy is already used) | L |
| **1b** | The work-up store inside version memory; the new endpoints; the information-request loop with typed readings only; a loading-page stage | none | M |
| **2** | The reverb measurement tool and the `reverb` stage; Pedalboard as an optional renderer for reverb | Pedalboard, optional (GPLv3; licence parked until before launch) | L |
| **3** | Vocal stages from stems: `vocal_compression`, `deesser`; the source-separation choice | to be chosen | L |
| **4** | Screenshots: opt-in, vision model, parsed values confirmed by the person | a vision model | M to L |

Phase 1a's `eq_match` works on full mixes. `vocal_compression` is out of Phase 1 because a reference song is only
ever a finished master, so there is no reference vocal to estimate from.

## 3. Modules (all new, under `mixcheck/chain/`)

| Module | Role |
|---|---|
| `hypothesis.py` | `ChainHypothesis`, `Stage`, `Param`: ordered stages with ranges, a point estimate, a confidence in [0, 1], the evidence, a description, and the source of each value |
| `spectrum.py` | A roughly third-octave long-term spectrum on the loud sections at matched volume, reusing `reference.loud_mask` |
| `estimators/eq_match.py` | The correction curve from the person's spectrum to the references' zone, with a confidence per band; the other stages are stubs returning `not estimated` |
| `render/base.py` | A `Renderer` interface: `render(audio, stage_params) -> audio` |
| `render/scipy_eq.py` | Our own EQ renderer (designed filters, no new dependency) |
| `loop.py` | Closed loop: render, re-measure with `measure_profile`, compare with `reference.compare`, report the remaining gap |
| `wording.py` | Confidence to wording; the verifier calls it |
| `workup.py` | The store (inside version memory) and the ranking of information requests |

One small additive change outside the module: the reference profile gains a finer spectrum field, and
`PROFILE_VERSION` goes to 2. Saved reference sets keep working for the five-band comparison, but `eq_match` needs the
finer field, so people re-add their references (audio is never kept).

## 4. The closed loop

1. Estimate the correction from the person's spectrum to the references' zone.
2. Render it on the person's audio. Corrections are bounded (at most 6 dB per band, as the code already caps).
3. Re-measure with the existing engine and compute the remaining gap.
4. Repeat a small bounded number of times (draft: at most 4). Stop when the gap stops improving.
5. **Floors on every candidate:** no overs, and a −1.0 dBTP ceiling on a master. A candidate that breaks a floor is
   rejected.
6. Report the gap before and after. Closing a measured gap does not prove it sounds better, so the wording says
   "check by ear".

## 5. Data shapes

### `ChainHypothesis`

```json
{
  "version": 1,
  "stages": [
    {
      "id": "eq_match",
      "stage_no": 3,
      "scope": "master",
      "status": "estimated",
      "params": {"curve": [{"hz": 120, "db": -2.0, "range": [-3.0, -1.0], "confidence": 0.7}]},
      "confidence": 0.7,
      "evidence": ["tone lows: person -1.4 dB, references -3.4 to -2.8"],
      "description": "..."
    },
    {"id": "vocal_compression", "status": "not_estimated"}
  ],
  "gap_before": {}, "gap_after": {}, "iterations": 2,
  "estimator_versions": {"eq_match": "1"}
}
```

`stage_no` is the stage in the ten-stage chain map: `eq_match` is 3, `vocal_compression` 4, `deesser` 5, `reverb` 7,
`width` 9, `limiter` 10. `scope` is `vocal`, `mix` or `master`.

### Work-up

```json
{
  "workup_id": "...", "song_id": "...", "version_id": "...",
  "references": ["profile-id", "..."],
  "known": [{"stage": "eq_match", "param": "high_shelf_hz", "value": 8000,
             "source": "typed", "trust": 1.0, "at": "..."}],
  "requests": [{"id": "...", "tier": "typed", "asked": "...", "stage": "...", "would_narrow": "..."}],
  "answers": [],
  "hypotheses": [],
  "audio": {"retained": true, "expires": "..."}
}
```

It holds numbers and user-typed or user-read values only. No audio and no screenshots are stored after parsing.
Values the person typed are facts about the person's chain, and each carries its source and a trust weight.

## 6. Endpoints

All new and additive. `/api/analyze` and `/api/fixes` are unchanged.

| Endpoint | Does |
|---|---|
| `POST /api/workups` | Start a work-up from a report, the references and the audio handle |
| `GET /api/workups/{id}` | Read it |
| `POST /api/workups/{id}/answers` | Record a typed reading |
| `POST /api/workups/{id}/run` | Run the closed loop with what is known now |
| `DELETE /api/workups/{id}` | Delete the record and the retained audio |

**Audio retention:** the audio stays on the person's computer for the life of the work-up, with a visible delete
button and an expiry. Nothing leaves the machine in Phase 1.

## 7. Confidence and wording

- Above a high threshold: "likely". In the middle: "possibly". Below a low threshold: "couldn't tell", with no
  setting shown. **[thresholds to set from the validation results]**
- The mapping lives in code (`wording.py`) and the verifier enforces it. The model cannot upgrade it.
- Numbers in a step come from the hypothesis, so the number check passes.

## 8. Information requests

Each estimator reports which missing input would narrow its uncertainty most. Code ranks the requests by cost
(typed reading, then screenshot, then stem), at most two at a time. The reasoning model words them. A typed reading
pins that parameter and removes it from the search; a stem, in Phase 3, improves the vocal stages.

## 9. Validation (required before anything is shown)

A harness under `tests/` that applies known chains to known sources and records, per stage:

- the parameter error of the estimate
- the output error after re-measurement
- whether confidence is calibrated (a confidence of 0.8 should be right about 80% of the time)

It must include the realistic case: **the reference is a different song** from the person's audio. It must include
some real multitrack material in addition to synthetic signals (open datasets exist; licences to be checked). The
output is a table. A stage is not shown to users until its table exists and meets thresholds Tyler approves.
**[pass thresholds to agree]**

## 10. The reverb measurement tool

**Built (step 1 of the build order): `mixcheck/decay.py`.** Standalone and tested; it is not yet wired into the
analysis or the work-up, which comes in phase 2. Validation table: `python tests/validate_decay.py`.

`measure_decay`, a read-only tool the reasoning model can call. Code finds places where sound ends (phrase ends,
section breaks, hit tails) and measures how fast the level falls afterwards, per band.

- **Inputs:** time ranges (candidates may come from the audio model or from code), and the bands.
- **Outputs:** decay slope in dB per second per band, tail length, an estimated decay time, the number of events used,
  and a confidence.
- **Validated** by the harness: known reverb is applied to dry sources and the tool must recover it.
- **What the first validation showed.** On sources that stop abruptly (a voice-like tone, a drum-like hit) the
  reading was within about 15% of the true decay time across 0.3 to 2.5 s, and dry sources read as "no measurable
  tail". With a dense steady bed 15 dB under the peaks it said "couldn't tell" every time, as designed. A full
  4-minute file takes about 2 seconds.
- **The result is an upper limit, not a reading of the room.** The room can't be slower than the fall observed, but a
  source that rings by itself (a plucked or held note) can make the fall look slower. A ringing note with no room read
  1.2 s with high confidence. Nothing in the decay alone tells the two apart, so the confidence says how well the fall
  was measured, not whose it is. The audio model's description of what is playing is what tells the reasoning layer
  which case this is.
- **Honest limits:** in a dense full mix a vocal reverb is largely masked, so "couldn't tell" will be common. Pre-delay
  and wet-to-dry balance are only reported with a vocal stem or a typed reading. These results are on synthetic
  sources; real material, ideally a vocal stem with reverb settings you know, is the next check.
- **The reasoning model's role:** rank hypotheses from the weak signals and the audio model's description, choose what
  to ask or measure, and explain the result. It never supplies the numbers.

Rendering a reverb hypothesis for the closed loop uses Pedalboard as an optional renderer behind the interface.

## 11. Fit with the rest of the work

- The ownership table is unchanged: code measures, the audio model gives context, the reasoning model interprets.
- The work-up store is part of version memory, not a second store.
- It needs the refactor steps first (observations and stage ids), per the earlier decision.
- A reference sets the target. The sub-genre ranges act as a sanity check ("your reference is brighter than typical
  for this style"). **[Tyler to confirm]**

## 12. Open items

1. The confidence thresholds for the wording (from the validation results).
2. The validation pass thresholds.
3. Which real multitrack material, and its licence.
4. The separation model (Phase 3) and the vision model (Phase 4).
5. Whether a reference or a sub-genre wins when they disagree (draft: the reference).
