# Engineer's notes eval: notes

**baseline**: claude-opus-5, prompt notes-v1, 6 ok / 0 truncated / 6 errors, $0.14; median 13.4 s, 346 words

| metric | baseline |
|---|---|
| ids_valid | 100% (61–100, n=6) |
| numbers_grounded | 83% (44–97, n=6) |
| tools_owned | 100% (61–100, n=6) |
| stage_appropriate | 100% (51–100, n=4) |

## Failures in baseline

- **numbers_grounded** · song01__trap_target: not in the report: 808s
