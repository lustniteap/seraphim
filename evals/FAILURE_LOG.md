# Engineer's notes: failure log

Each entry is one way the notes went wrong, found by the eval or by reading them, and what fixed it.
Scores come from `python evals/notes_eval.py summary`; each prompt change is a new variant (`baseline`,
`v1`, `v2`...) run on the same cases, so the before/after numbers are comparable.

| # | Found in | Symptom | Metric | Root cause | Fix | Before → after |
|---|---|---|---|---|---|---|
| | | | | | | |

## Entry template

### N. Short name of the failure

- **Found:** variant, which cases (ids from `summary.md`), and how (a check, the judge, or reading the notes).
- **Symptom:** what the notes said, quoted from a trace, next to what the report says.
- **Root cause:** why the model did it: what in the prompt, the input or the schema allowed or encouraged it.
- **Fix:** the change (prompt wording, input shape, schema, or a code check), and the variant that carries it.
- **Result:** the metric before and after, with intervals, plus anything that got worse.
