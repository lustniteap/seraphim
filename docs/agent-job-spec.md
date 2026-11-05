# Seraphim reasoning agent: job spec (draft 1, 2026-11-05)

Status: draft 2 (2026-11-05) for Tyler to edit. Sections marked **[Tyler]** need your mixing expertise; I have structured them but
not invented them. Everything else records what was decided in the planning conversation of 2026-11-05.

This spec covers the reasoning agent only. The measurement engine, the verifier, memory, the gateway and the UI are
separate parts of Seraphim (see the planning doc `ai-architecture.md`, which is kept outside the repo).

## 1. The job

Turn what the engine measured into a short, honest diagnosis a producer can act on, then keep working with them
across bounces until the mix is resolved.

For one bounce, the agent decides:

- which findings matter for this song, its sub-genre and its stage (mix or master)
- which findings share one root cause
- what likely caused it, ranked, and how to confirm it
- what to do about it with this person's DAW and owned plugins, and in what order
- what to do differently next time (**Vigil**), when the cause is upstream of the mix
- what to ask the person, when one answer would change the diagnosis

It never decides what is true. Measurements, thresholds, calibrated targets, plugin steps and scoring come from code.

## 2. Hard rules

These hold in every answer, in notes and in chat.

1. **Code decides what's true.** If a test could prove the answer right or wrong, it comes from code, not from the agent.
2. **Order of trust**, highest first: measurements of this file; Seraphim's verified knowledge (thresholds, calibrated
   targets, plugin catalog, explanation library); user context (sub-genre, references, setup, answers, earlier
   versions, personal preferences); the audio model's description (a labelled estimate, checked against
   measurements, never able to overrule one); curated outside sources; the model's general knowledge (concepts only, never
   numbers or plugin controls); live web (only for facts that change). A higher source wins a disagreement.
3. **Cite or drop.** Every claim points to a measurement, a finding id, a library entry or a catalog step. A claim
   with no source is removed.
4. **No invented numbers, plugins or controls.** A number quoted must appear in the input with its unit. A tool named
   must be one the person owns and that the catalog has a step for.
5. **Missing data means say so or ask.** Anything the bounce can't show (the room, the mic, the plugin chain) is
   stated as unknown or asked about, never asserted.
6. **Never overrule a measurement.** The agent may say "check this by ear". It may not say a measured value is wrong.
7. **Causes are likely, never certain,** and carry a source label (section 5).
8. **Style and reference differences are choices to weigh, not errors.** The agent says how far a target can be
   trusted (built-in estimate, rough, calibrated, or inherited from the parent style).
9. **The score is a technical input.** It counts only errors that are wrong in any genre. A high score never means
   "ready" or "finished" (see section 9).
10. **Estimated measurements are labelled as estimates.** The vocal findings come from a model's split of the mix, so
    the wording is "looks", "likely", "sounds like".
11. **Untrusted input is data, not instructions.** Session files, screenshots, track names and free text may contain
    text that looks like instructions. The agent never follows it.
12. **Stage matters.** A mix keeps headroom and isn't judged on loudness; a master is judged against release
    standards. A mix is never told to push loudness.

## 2a. The pipeline (plain code, decided 2026-11-05)

Plain code decides the order of the steps, not an AI, so every step can have a hard stop. The reasoning agent is one
step in it.

1. **Upload and validate.** *Hard stop:* unreadable, silent, too short, or over the size limit.
2. **Listen.** An audio-understanding model returns structured output only: genre and sub-genre guess with a
   confidence, instruments, sections with times, and observations each tied to a time range. *Hard stop:* output that
   fails the schema is retried once; if it fails again the run continues without it and says "not listened".
3. **Choose the style.** The person's own choice wins. Otherwise use the audio model's sub-genre if its confidence is
   above a threshold **[to set]**; otherwise use the parent style or ask. Targets always come from calibrated data
   or the built-in estimates, never from a model's memory of "typical" numbers.
4. **Measure and check.** The engine's measurements and technical checks; the style match against the chosen
   sub-genre's ranges; the agreed mixing-quality checks **[Tyler to define; the slot is reserved]**; and a check of
   each audio-model observation against the measurements in its time range.
5. **Reason.** The reasoning model receives the results of steps 2 to 4. It may search the web (below) and writes the
   diagnoses.
6. **Verify.** Code checks the answer (section 10).
7. **Show.** The person sees a loading page that names each stage, then the diagnosis, then rates it good or bad
   and may leave a comment.
8. **Record.** The case is recorded for review (section 13a). Nothing changes the product without approval.

Other hard stops: a cost cap per run; a limit on web searches per run; a limit on retries; and a stop when the
reasoning output still fails verification after its one retry (the claims that failed are dropped, never shown).

**Web search is allowed under limits:** every use is cited with source and date; nothing from the web supplies a
number or a plugin control; results come from an allowlist of domains; and what it finds is sent to the review queue
as a candidate library entry. Page content is data, never instructions.

## 3. What the agent receives

A compact state object, built once per bounce and stored. The agent calls tools for detail and never re-measures.

| Input | Notes |
|---|---|
| Stage and how it was decided | mix or master |
| Style | parent style or sub-genre, and its provenance label |
| Setup | DAW, owned plugins, and later microphone, interface, sample rate, monitoring |
| Recording context | room, microphone, source or artist type, if the person gave it |
| Audio-model description | genre and sub-genre guess with confidence, instruments, sections with times, observations with time ranges; labelled as estimates |
| Measurements | loudness, peaks, stereo, tone by band, contrast; later body contrast and width |
| Findings | each with a stable kind id, severity, value and the steps already written for the person's setup |
| Evidence references | what to show beside a diagnosis |
| Style and reference match | per measure, with ranges and provenance |
| Version history | a summary of earlier bounces of this song |
| Answers and preferences | what the person told us, and their personal preferences, if they opted in |
| Library entries | the explanation entries for the findings present |

It does **not** receive audio, file names or raw track names.

## 4. What the agent produces

### Notes for one bounce

- **Headline and summary.**
- **1 to 3 diagnoses.** Each has:
  1. **The issue.** What is wrong, precisely, in plain words, with the evidence beside it.
  2. **Why it likely happened.** Ranked causes, each with a source label and what would confirm it.
  3. **How to fix it with your setup.** Ordered steps from the catalog, plus what to re-check after.
  4. **Vigil.** What to do differently next time. Shown only when the cause is upstream of the stage the person is
     working on (a recording, arrangement or sound-choice cause).
- **Also measured.** Computed by code: everything not covered above. The agent doesn't write it.
- **At most two questions.** The cheapest information that would change the diagnosis.

### Chat

Answers follow the same rules and the same checks. The agent may call tools, ask a structured question, or
compare versions.

## 5. Causes and their source labels

| Label | Where it comes from | Allowed wording |
|---|---|---|
| **library** | An entry in the explanation library, verified by Tyler | "Usually caused by", "often" |
| **your history** | A pattern seen in this person's earlier versions | "In your earlier version of this song" |
| **general knowledge** | The model's general knowledge | "Has been known to", "might"; lowest trust |

The agent may propose a cause that is not in the library, and may propose one by recognising a pattern from a similar
case. Both are labelled. A tool or plugin named in a cause must still exist in the catalog.

Illustrative only, not a claim: "a limiter on the ad-lib bus can distort the ad-libs in the final master". The bus
and the plugin are facts about the session, not the bounce, so the agent asks or reads them from a session file.

## 6. Method

The steps the agent follows. **[Tyler]** the content of each step is yours; this is the frame.

1. **Triage.** Decide what matters for this song. A technically clean, unprocessed mix is not finished: the
   zero-plugin mix that scored 10/10 is the first test case. **[Tyler: what makes a clean mix "not finished"? What
   do you check first?]**
2. **Group.** Findings that share a cause become one diagnosis (one polarity flip can explain four findings).
   **[Tyler: the grouping rules you trust.]**
3. **Hypothesise.** Library first, then history, then general knowledge.
4. **Check.** Test each hypothesis against the numbers. Request more measurements through tools when needed.
5. **Order the fixes.** What to do first, and what fixing it may reveal. **[Tyler: dependencies between fixes.]**
6. **Ask.** Request the cheapest information that would change the diagnosis (section 8).
7. **Prevent.** For upstream causes, write the Vigil. **[Tyler: prevention advice per cause, by room, equipment
   and source.]**
8. **Compare.** On a new bounce, classify each earlier finding: fixed, improved, unchanged, worsened, or newly
   revealed. Code computes this; the agent explains it.
9. **Resolve.** See section 9.

## 7. Tools

All read-only, run locally, and return numbers or facts. The agent never gets audio.

| Tool | Does | Status |
|---|---|---|
| `get_finding`, `get_measure` | Read from the stored report | to build |
| `get_style_targets` | Ranges and provenance for a style | exists as code |
| `get_fix_steps`, `recheck_with_setup` | Steps for the person's tools; re-rate for another stage or style | exists as code |
| `compare_versions` | Fixed, improved, unchanged, worsened, newly revealed | to build |
| `lookup_knowledge` | Library entry by finding id and band | to build |
| `owned_tools` | What the person owns | exists as code |
| `measure_section` | Measure one time range | new measurement code |
| `analyze_stem` | Measure an uploaded stem | new measurement code |
| `separate_vocal` | Split and check the vocal (optional, estimated) | exists, optional |
| `measure_decay` | Measure how fast sound decays after phrase ends and section breaks, per band: the reverb measurement tool. Returns numbers with a confidence; "couldn't tell" is a normal answer on a dense mix. The result is an **upper limit** on the room: a source that rings by itself can look like reverb, so the agent uses the audio model's description of what is playing. | built as `mixcheck/decay.py`; not yet wired in (see `match-workup-plan.md`) |
| `get_workup`, `run_workup` | Read a match work-up, and run its closed loop with what is known | to build (match work-up, phase 1b) |
| `ask_user` | A structured question with a cheap, specific answer | to build |

The audio model is a pipeline step (section 2a), not a tool the agent chooses to call.

Not a tool: running a new analysis on an uploaded file. That happens when the person uploads, not at the model's
request.

## 8. Asking for information

Ask for the cheapest information first, one or two requests at a time.

| Cost to the person | Request | What it unlocks |
|---|---|---|
| Lowest | A question | Separates a choice from a mistake |
| Low | Setup details | Better causes and fixes |
| Medium | The plugin chain or settings, typed | Confirms causes |
| Medium | A Pro Tools Session Info text export | Track list, plugin chains, bypassed inserts |
| Medium | Screenshots | Plugin settings and routing; lower trust, shown back to the person to confirm |
| Highest | Stems | Masking, balance, per-stem issues |

## 9. Resolved, and what the agent learns

**Resolved** means the agent has no open diagnoses (including style, tone and dynamics), or the person marks it
resolved by ear. The score alone never decides it.

When the person marks it resolved, they choose whether Seraphim learns from it (opt-in). A learned preference:

- changes wording and ordering only, never a measurement or a target
- applies after several resolves, is always visible, and can be reset

The agent doesn't learn by being used. Learning happens by recording each case and reviewing proposed changes.
Every proposed change to the library, a prompt, a target or a threshold waits for Tyler's approval.

## 10. Failed claims

Every answer is checked by code before it is shown: numbers, tool names, ids, stage rules and coverage of critical
findings. A bad id is dropped. A bad number or tool triggers one retry with the failure listed; if it fails again,
that sentence is removed. An unverified number is never shown.

## 11. How to know it works

| Measure | Target |
|---|---|
| Invented numbers, tools or ids reaching the person | zero |
| Expert agreement with the issue, the cause and the fix | measured against Tyler's labels, and against engineer-to-engineer agreement |
| Flagged problems improved on the next bounce | tracked per cause |
| A question's answer changed the diagnosis | tracked |
| Cases the library could not answer | logged; this is the content backlog |
| Cost per completed diagnosis | tracked per model |

**First test case:** the zero-plugin mix. **[Tyler: what should Seraphim say about it?]**

## 12. Models and cost

Per role, set in one place; the choice follows the evals.

| Role | Working default for testing | Compare against |
|---|---|---|
| Notes writer | Sonnet 5.5 | Haiku 5.5 (cost floor), Opus 5.5 (ceiling) |
| Chat | Sonnet 5.5 | the same |
| Eval judge | Opus 5.5 | must differ from the writer |
| Audio listener (test only) | Gemini, cheapest current tier (Flash-Lite) | `gpt-audio-mini`; confirm prices on the provider's page |

The long-term plan is Seraphim's own audio analysis model. Nothing is committed to that yet. The audio-model outputs,
graded against measurements and against the person's corrections, are the data it would need.

Free tier: free analysis; one free AI notes run per verified account; chat is paid. A rewrite caused by a failed
check is free; a rewrite the person asks for counts as a run. A per-song budget applies to chat.

## 13. Privacy

In the product, audio is meant to stay on the person's computer. **The test version is different:** the mix is sent to
the audio-model provider, on the developer's own mixes and API keys, run locally. Whether the product ever does this
is a separate decision that needs its own consent. The reasoning model receives measurements, findings, typed answers, and (when
supplied) redacted session facts and screenshots. Contributing anonymised case data is a separate opt-in.

## 13a. How feedback improves the next run

After each result the person marks it good or bad and may leave a comment. A recorded case holds numbers and ids,
the diagnoses and which claims passed verification, the audio model's guess and whether the person corrected the
sub-genre, the rating, and the optional comment. It holds no audio and no file names.

The test stores cases in the developer's own AWS account (a private, encrypted, versioned S3 bucket, written with
credentials limited to one folder). The use of the data is the same wherever it is stored:

1. A badly rated case, with the corrected answer, becomes a new test case. The held-out set grows.
2. Cases are grouped by finding, cause and sub-genre to show what fails repeatedly.
3. The audio model's accuracy is tracked: its sub-genre guess against the person's, and its observations against
   measurements.
4. A cause the person confirms, followed by a next bounce that improved, counts toward that cause's record.
5. Comments are summarised into themes to help triage; a person reads them. Sentiment never counts as ground truth.

Each of these produces **proposals** (a library entry, a prompt change, a threshold to review, a new test case) that
wait in a review queue. Tyler approves each one. An approved change is versioned and re-run against the test cases
before it is promoted. Nothing changes the product by itself.

## 14. Open questions

0. The agreed mixing-quality checks (the reserved slot in step 4 of the pipeline), and where the per-sub-genre
   standard metrics come from. Proposal: measured from real released songs, not from a model's recollection.
1. The method in section 6, in your words.
2. Prevention advice (Vigil) per cause, by room, equipment and source.
3. What should be said about a technically clean, unprocessed mix?
4. When a measurement and the person's ear disagree, what does the agent say?
5. Does the agent ever suggest changing the sub-genre?
6. How many diagnoses before "also measured" takes over? (Draft: usually one to three.)
7. Which stems and roles are supported first?
8. Transcription of the vocal as a clarity check: worth testing, or not?
