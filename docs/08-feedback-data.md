# Feedback data: format, labels and storage (as of 2026-11-05)

Purpose: store the results of every analysis plus human feedback on them, so Seraphim's findings, targets and AI
diagnoses can be measured and improved. Planning document; nothing here is built yet.

## Principles

- **Never store audio.** Records hold numbers, findings, AI output and labels only.
- **Append-only.** Records are never edited. A correction is a new record with `supersedes` pointing at the old one.
- **Every record is versioned:** `schema_version`, plus `analyzer_version`, and for AI output `prompt_version`,
  `model` and `provider`, so each label can be traced to the exact code and prompt that produced the result.
- **Fixed label vocabularies** (enums below) so data can be counted and compared. Free text only as an extra.
- **Pseudonymous people:** a stable `labeler_id` and `user_id`, never names or emails.
- **No unreleased titles:** file names are stored as a hash (`file_hash`), not as text.
- **Units in field names:** `_lufs`, `_db`, `_lu`, `_s`, `_hz`.
- **Timestamps:** ISO 8601 in UTC. **IDs:** UUIDs.
- **Consent:** every record carries `consent` (`internal_test` for Tyler and test engineers; later `opt_in` for users).
- **Write locally first, sync to AWS second,** so the app works offline and nothing is lost if a sync fails.

## Record types

Three record types, linked by IDs.

### 1. analysis: what Seraphim measured and said

```json
{
  "record_type": "analysis",
  "schema_version": "1.0",
  "analysis_id": "uuid",
  "created_at": "2026-11-05T13:00:00Z",
  "analyzer_version": "x.y.z",
  "consent": "internal_test",
  "user_id": "pseudonymous id",
  "song_id": "uuid (same for every version of one song)",
  "version_number": 1,
  "file": {"file_hash": "sha256", "format": "wav", "sample_rate_hz": 48000, "duration_s": 182.4, "lossless": true},
  "context": {"stage": "mix|master", "stage_detected": "mix", "parent_style": "hiphop_rap",
              "sub_genre": "hiphop_rap.drill", "daw": "pro_tools", "plugins": ["waves_essential", "fabfilter"],
              "references": ["profile ids, numbers only"]},
  "measures": {"integrated_lufs": -8.4, "true_peak_dbtp": -0.3, "plr_db": 8.1, "lra_lu": 3.9,
               "body_contrast_lu": 3.6, "correlation": 0.82, "low_end_correlation": 0.83,
               "tone_db": {"lows": -1.8, "low_mids": -7.3, "mids": -10.8, "presence": -15.4, "highs": -14.4}},
  "findings": [{"finding_id": "true_peak_hot", "severity": "warning", "value": -0.3}],
  "score": {"technical": 8.4, "style_match_pct": 91},
  "ai": {"provider": "anthropic|bedrock", "model": "model id", "prompt_version": "notes-v3",
         "diagnoses": [{"diagnosis_id": "uuid", "title": "...", "finding_ids": ["..."],
                        "causes": [{"cause": "...", "confidence": "likely|possible"}],
                        "fix_step_ids": ["..."]}]}
}
```

`measures` holds the full report's numbers in practice; the example is shortened.

### 2. feedback: what a person thought of it

```json
{
  "record_type": "feedback",
  "schema_version": "1.0",
  "feedback_id": "uuid",
  "analysis_id": "uuid",
  "created_at": "2026-11-05T13:20:00Z",
  "consent": "internal_test",
  "labeler_id": "pseudonymous id",
  "labeler_role": "engineer|artist|producer",
  "labeler_experience": "pro|intermediate|beginner",
  "listening": "studio_monitors|headphones|car|laptop|phone",
  "sub_genre_confirmed": "hiphop_rap.drill",
  "findings": [{"finding_id": "true_peak_hot", "verdict": "agree|disagree|unsure",
                "severity_verdict": "right|too_high|too_low"}],
  "diagnoses": [{"diagnosis_id": "uuid",
                 "issue": "correct|partly|wrong",
                 "cause": "correct|partly|wrong|cant_tell",
                 "fix": "helpful|partly|not_helpful|not_tried",
                 "fix_applied": true}],
  "missed_issues": [{"category": "vocal_level", "note": "optional free text"}],
  "overall": 4,
  "note": "optional free text",
  "supersedes": null
}
```

### 3. outcome: what happened on the next bounce

Written automatically when a new version of the same song is analyzed.

```json
{
  "record_type": "outcome",
  "schema_version": "1.0",
  "outcome_id": "uuid",
  "song_id": "uuid",
  "from_analysis_id": "uuid (version n)",
  "to_analysis_id": "uuid (version n+1)",
  "created_at": "2026-11-05T15:00:00Z",
  "findings": [{"finding_id": "true_peak_hot", "status": "resolved|improved|unchanged|worse|new"}],
  "diagnoses": [{"diagnosis_id": "uuid", "status": "resolved|improved|unchanged|worse"}],
  "score_change": {"technical": 1.2, "style_match_pct": 6}
}
```

## Label vocabularies

| Field | Values |
|---|---|
| verdict | agree, disagree, unsure |
| severity_verdict | right, too_high, too_low |
| issue / cause | correct, partly, wrong (cause also: cant_tell) |
| fix | helpful, partly, not_helpful, not_tried |
| overall | 1 to 5 |
| labeler_role | engineer, artist, producer |
| labeler_experience | pro, intermediate, beginner |
| listening | studio_monitors, headphones, car, laptop, phone |
| missed_issues.category | vocal_level, vocal_harshness, sibilance, masking, mud_low_mids, sub_too_loud, sub_too_quiet, kick_808_clash, harsh_top, dull_top, too_wide, too_narrow, dynamics_overcompressed, dynamics_too_loose, reverb_delay, tuning_pitch, timing, noise_artifacts, distortion, arrangement, other |
| outcome status | resolved, improved, unchanged, worse, new |

Add a category only by adding it to this list, so data stays comparable.

## Storage

**Now (local):** append records to JSON Lines files in `~/.mixcheck/feedback/` (one file per record type per day).

**AWS (small, independent of the hosted app):**
- One S3 bucket, `seraphim-feedback-<account-id>` in us-west-2: **versioning on** (unlike the audio uploads bucket),
  encryption, block public access, `RemovalPolicy.RETAIN` in CDK.
- Layout: `v1/<record_type>/date=YYYY-MM-DD/<id>.json` (or daily `.jsonl` files).
- Sync with the AWS CLI using each person's Identity Center sign-in (no access keys). Collaborators get a permission
  set that can only write to `v1/` in this bucket and can't delete.
- Later: an AWS Glue table over the bucket and Amazon Athena to query it with SQL (pay per query, nothing to run).
- When the hosted app exists, its Lambdas write the same records to the same bucket. DynamoDB holds the live app data;
  this bucket stays the long-term dataset.

## How the data improves accuracy

| Use | From |
|---|---|
| Precision of each finding (how often engineers agree) and threshold tuning | feedback.findings |
| Diagnosis quality (issue, cause, fix) per prompt version and model | feedback.diagnoses + analysis.ai |
| Ground truth for the evals/ harness (engineer labels) | feedback |
| What Seraphim misses, and what to add next | feedback.missed_issues |
| Whether advice works | outcome |
| Sub-genre targets and labels | analysis.context + feedback.sub_genre_confirmed |
| Explanation library gaps | missed_issues and low "cause" ratings |
