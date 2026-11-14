# AI architecture: how Seraphim diagnoses a mix (as of 2026-11-05)

Product direction from Tyler, 2026-11-05. Planning document; nothing here is built yet beyond what's marked existing.

## The value of Seraphim

Measuring and flagging mix issues is the foundation, not the product. The product is AI reasoning that decides
**precisely what the issue is, why or how it likely happened, and how to fix it with this user's DAW and plugins**,
then keeps working with the user across revisions until the mix is resolved, the way an engineer would in a session.

## Division of labor

**Code decides what's true. The AI decides what matters, why, and how to say it.**
Test: if a test can prove the answer right, it's code. If two good engineers could disagree, it's AI, grounded in code.

| Code (deterministic) | AI mix agent |
|---|---|
| Measurements (loudness, peaks, stereo, tone, edges, body contrast) | Which findings matter for this song, sub-genre and stage |
| Thresholds, findings, style and reference match | Root cause: grouping several findings into one problem |
| Calibrated sub-genre targets | Likely causes (ranked, with confidence) |
| Plugin catalog: exact steps per DAW and tool | Priority and order of fixes; what fixing one may reveal |
| Verify step: numbers, IDs, owned tools | Explanation in the user's terms; deciding what to ask next |

The AI may not overrule a measurement or invent a number, plugin or control name. When something can't be measured
from what's been uploaded, it says what to listen for or asks; it never states it as fact.

## Order of trust

When sources disagree, the higher one wins:
1. Measurements of this file (and of any stems the user provided)
2. Seraphim's verified knowledge: thresholds, calibrated targets, plugin catalog, explanation library
3. User context: sub-genre, references, DAW/plugins, setup, preferences, answers, earlier versions of this song
4. Curated outside sources in the knowledge base (with source and date)
5. The model's general knowledge (concepts only; never numbers or plugin controls)
6. Live web, only for facts that change (platform targets, plugin updates), preferably reviewed into the knowledge base

Rules: **cite or drop** (every claim points to a measurement, finding ID or knowledge entry); **propose, then verify**
(code checks the answer before it's shown); **missing data means say so or ask**.

## The notes: three sections per diagnosis

The AI notes become the main output. They group findings into **diagnoses** (one problem can cause several findings)
and show only what matters: usually 1-3 diagnoses, the rest under a collapsed "also measured".

Each diagnosis has three sections, plus the evidence that supports it:

1. **The issue.** What's wrong, precisely, in plain words. Evidence beside it: the one or two charts and numbers that
   prove it (for example, tone vs the sub-genre's range, low-end correlation over time, loudness timeline with the
   section marked). No chart appears unless a diagnosis points to it.
2. **Why it happened.** Likely causes, ranked and labeled as likely, not certain, since a bounce can't show the session.
   Each ends with what would confirm it ("upload the 808 stem", "what's on your mix bus?"). That's the bridge to chat.
3. **How to fix it with your setup.** Ordered steps from the catalog for the user's DAW and owned plugins, plus what to
   re-check after (fixing one thing can expose another).

## The resolution loop

A mix is rarely fixed in one pass. After the notes, Seraphim opens a chat tied to this song:

```
bounce v1 → diagnoses → user applies fixes / answers questions → bounce v2
   → compare versions: fixed, improved, unchanged, newly revealed → updated diagnoses → ... → resolved
```

- **Version memory** per song (numbers and findings only, never audio) makes the comparison possible and shows progress.
- **Resolved** = no critical diagnoses left, and the user is happy with the style or reference match. (Definition to confirm.)
- The loop also gives the best accuracy signal Seraphim has: whether the next bounce actually improved what was flagged.

## Asking for more information

The agent asks for the **cheapest information that would change its diagnosis**, one or two requests at a time:

| Cost to user | Request | What it unlocks | Needs |
|---|---|---|---|
| Lowest | A question (intent, preference, "is the vocal meant to sit back?") | Separates choice from mistake | Chat |
| Low | Setup: DAW, plugins (exists), mic, interface, sample rate, monitoring | Better causes and fixes | Setup profile |
| Medium | Vocal chain, plugin settings, mix bus chain | Confirms causes | Chat + catalog |
| Medium | Pro Tools Session Info text export (and later Ableton/Reaper files) | Track list, plugin chains, bypassed inserts | Session parser (test fixture exists) |
| Medium | Session or plugin screenshots | Plugin settings, routing | Vision model; lower trust, verify against catalog |
| Highest | Stems (vocals, 808, drums, beat) | Masking, level balance, per-stem issues | Engine on stems + new masking measures |

Session data stays optional and offered in context (the earlier "pro" decision); bounce-only remains the default.

## Knowledge base, internal first

Build in this order before relying on outside material:
1. Measurement engine (exists)
2. Rules and thresholds (exists)
3. Calibrated sub-genre targets (in progress; see 05-style-taxonomy.md)
4. Plugin catalog (exists, 46 tools)
5. **Explanation library**: per finding ID, written by Tyler: why it matters, what to listen for, common causes by
   sub-genre, what to ask to confirm. Feeds sections 2 and 3 of the notes.
6. Worked examples: cases where a fix worked on the next bounce
7. Outside sources, only for gaps the above can't fill

Entries are structured: ID, content, source, verified by, date, applies to (DAW, plugin/version, stage, sub-genre).
Direct lookup by ID before vector search; add retrieval when there's a real document collection.
Log every question the knowledge base couldn't answer; that log is the content backlog.

## Efficiency

Code runs once per bounce and results are stored. The AI gets a compact state object (stage, sub-genre, setup,
key measurements, findings with IDs, version history summary), calls tools for details, and never re-measures.

## Suggested build order

1. Style work in 05-style-taxonomy.md (targets the diagnoses depend on)
2. Explanation library for the most common findings (writing, no code)
3. Notes v3: diagnoses with the three sections and linked evidence charts; extend the existing eval checks
4. Version memory and the bounce-to-bounce comparison
5. Chat tied to a song: questions and setup profile first
6. Session text export parser (Pro Tools first)
7. Screenshots, then stems with masking measures

## What to measure

- Grounding: claims citing a measurement or entry; invented IDs, numbers or plugins (target zero)
- Diagnosis quality: engineer agreement with the issue, cause and fix (vs engineer-to-engineer agreement)
- Loop: share of flagged problems improved on the next bounce; bounces to resolution
- Asking: how often a requested piece of information changed the diagnosis
- Knowledge gaps: unanswered-question log volume over time
