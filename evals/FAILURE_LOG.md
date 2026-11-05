# Engineer's notes: failure log

Each entry is one way the notes went wrong, found by the eval or by reading them, and what fixed it.
Scores come from `python evals/notes_eval.py summary`; each prompt change is a new variant (`baseline`,
`v1`, `v2`...) run on the same cases, so the before/after numbers are comparable.

| # | Found in | Symptom | Metric | Root cause | Fix | Before → after |
|---|---|---|---|---|---|---|
| 1 | baseline (notes-v1) | Describes how the track sounds ("solid-sounding master", listen for "the grit and pumping that was there before") | judge_faithful 78% | The prompt says to use only the analysis, but never says the model can't hear the file, so it fills in plausible sound | notes-v2: "You can't hear the file" | pending v1 run |
| 2 | baseline (notes-v1) | Calls an unflagged measurement a problem: song01 as a master is "quiet at -17.11 LUFS, worth a look" with no loudness finding and no style target | judge_faithful, judge_stage_appropriate | Nothing says a measurement without a finding isn't a problem; the model applies its own loudness norms | notes-v2: "Only the findings are problems" | pending v1 run |
| 3 | baseline (notes-v1) | Every list filled to the maximum: 3-4 listen-for items and 3 strengths even on a clean report; the same number in headline, summary and priority | judge_concise 85% | The prompt asked for "two to four" and "up to three", which the model treated as targets | notes-v2: 1-3 tied to priorities, at most 2 strengths, each number once | pending v1 run |

## Fixes to the eval itself

Bugs in the checks are as costly as bugs in the notes: they point prompt changes the wrong way. These were
found by running stand-in writers (`--fake oracle|null|sloppy`) through the whole harness before any paid run.

1. **Invented priorities on a clean report passed `no_invented_problems`.** The sloppy writer points a priority at
   a finding that doesn't exist (F99). `notes.check()` drops such priorities before the user sees them, and the
   check read the notes after that clean-up, so it saw none. The user was protected, but the eval missed that the
   model invented a problem. Fix: the check also counts priorities `check()` dropped. Sloppy on the clean master:
   100% → 0%; oracle stays 100%.
2. **"0.14 dB" matched a −0.1 dB measurement.** The number check allowed ±0.05 for every quote, so a two-decimal
   number could match a different one-decimal measurement. Fix: tolerance follows the quoted precision
   (±0.005 for two decimals, ±0.5 for whole numbers, so honest rounding still passes). Numbers are also matched
   by unit, so "14 LUFS" can't be justified by an unrelated "14 dB".

3. **"808s" was read as 808 seconds.** Found in the first real pilot (`song01__trap_target`, notes-v1): the only
   failure was `numbers_grounded` on notes that said to let "the 808s" carry the low end, the drum machine, not a
   duration. The number pattern accepted a bare "s" straight after a number as seconds. Fix: a bare "s" only
   counts after a space ("30 s"). Pilot: numbers_grounded 83% → 100% on the same saved notes (`regrade`, no new
   calls); the oracle and sloppy stand-ins score as before. Lesson: read every failure before trusting a score;
   the model's first "mistake" was the grader's.

4. **A 0:40 song's "whole 40 seconds" counted as invented.** Found in the baseline (`clean_master__trap_target`,
   `polarity_mix__other_stage`): the report gives durations and times as m:ss ("0:40"), and the check only
   accepted seconds written as "40 s". Fix: every m:ss time in the report also counts as that many seconds.
   Baseline numbers_grounded 93% → 100% by `regrade`: both failures were the grader's.

## Judge disagreements to settle with hand labels

- **`polarity_mix__other_stage`, judge_faithful and judge_groups_causes both failed.** The notes say one side's flipped
  polarity is "one problem showing up in four ways; fix the polarity first and the rest should follow". That is
  correct: the whole song is inverted on one side, which causes the negative correlation, the thin mono low end and
  the mono loss. The judge failed it because the report lists them as separate findings with separate fixes. If hand
  labels agree the judge is too strict here, the rubric needs "causes that follow from how audio works are fine".

## Entry template

### N. Short name of the failure

- **Found:** variant, which cases (ids from `summary.md`), and how (a check, the judge, or reading the notes).
- **Symptom:** what the notes said, quoted from a trace, next to what the report says.
- **Root cause:** why the model did it: what in the prompt, the input or the schema allowed or encouraged it.
- **Fix:** the change (prompt wording, input shape, schema, or a code check), and the variant that carries it.
- **Result:** the metric before and after, with intervals, plus anything that got worse.
