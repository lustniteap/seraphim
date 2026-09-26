# Engineer's notes: failure log

Each entry is one way the notes went wrong, found by the eval or by reading them, and what fixed it.
Scores come from `python evals/notes_eval.py summary`; each prompt change is a new variant (`baseline`,
`v1`, `v2`...) run on the same cases, so the before/after numbers are comparable.

| # | Found in | Symptom | Metric | Root cause | Fix | Before → after |
|---|---|---|---|---|---|---|
| | | | | | | |

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

## Entry template

### N. Short name of the failure

- **Found:** variant, which cases (ids from `summary.md`), and how (a check, the judge, or reading the notes).
- **Symptom:** what the notes said, quoted from a trace, next to what the report says.
- **Root cause:** why the model did it: what in the prompt, the input or the schema allowed or encouraged it.
- **Fix:** the change (prompt wording, input shape, schema, or a code check), and the variant that carries it.
- **Result:** the metric before and after, with intervals, plus anything that got worse.
