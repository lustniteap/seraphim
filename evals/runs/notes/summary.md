# Engineer's notes eval: notes

**baseline**: claude-opus-5, prompt notes-v1, 27 ok / 0 truncated / 0 unresolved errors, $0.94; median 11.7 s, 324 words

| metric | baseline |
|---|---|
| ids_valid | 100% (88–100, n=27) |
| covers_critical | 100% (76–100, n=12) |
| covers_warnings | 100% (82–100, n=17) |
| numbers_grounded | 93% (77–98, n=27) |
| tools_owned | 100% (88–100, n=27) |
| stage_appropriate | 100% (80–100, n=15) |
| no_invented_problems | 100% (34–100, n=2) |
| judge_priority_order | 100% (83–100, n=19) |
| judge_explains_impact | 100% (87–100, n=25) |
| judge_groups_causes | 95% (77–99, n=21) |
| judge_specific | 100% (88–100, n=27) |
| judge_stage_appropriate | 93% (77–98, n=27) |
| judge_faithful | 78% (59–89, n=27) |
| judge_concise | 85% (68–94, n=27) |

## Failures in baseline

- **judge_concise** · clean_master__trap_target: The headline, summary, single priority, and three listen-for bullets repeat the same loudness point multiple times, adding length without new information for a report with only one info-level finding.
- **judge_concise** · light_lows_master__trap_target: There is redundant repetition of the same three numbers (dBTP, LUFS, PLR) across headline, summary, and priority 'why', padding length without adding new information.
- **judge_concise** · song01__other_stage: Given the report is a clean 10/10 with only two info-level findings, the notes add extensive extra material (headline critique, three listen_for items, three strengths) beyond what's needed.
- **judge_concise** · wide_bass_mix__other_stage: The notes add extensive extra sections (listen_for with four items, strengths with three) beyond what the two findings require, adding length without new substance.
- **judge_faithful** · light_lows_master__as_recorded: The listen_for line about 'the grit and pumping that was there before — it should clean up' invents an audible artifact not stated anywhere in the report's measurements or findings.
- **judge_faithful** · light_lows_master__trap_target: The notes claim the true peak overs 'show up worst' after MP3/AAC encoding as an established fact beyond what the report states (report only says 'expect distortion... after lossy encoding' generically, not a comparative claim), and the headline/summary overstate 'clipping hard' which isn't a term used or clearly supported by the report.
- **judge_faithful** · polarity_mix__as_recorded: The notes claim 'if not, the bass has its own width problem' and imply mono loss issue is separate/could be independent from polarity, but F2 in the report explicitly attributes the low-end issue to the same overall correlation problem (-0.78), and the report doesn't support a claim of a second independent bass width problem beyond what's already covered by F1/F4.
- **judge_faithful** · polarity_mix__other_stage: The claim that 'the low end and centre content will largely disappear' and that fixing polarity means 'the rest should follow' for F2 overstate what the report supports, since F2 is a distinct finding needing its own fix, not an automatic side-effect of the polarity correction.
- **judge_faithful** · song01__other_stage: The claim that the track is 'quiet at -17.11 LUFS...worth a look before release' is not supported by any finding in the report, which lists only F1 and F2 as informational issues and gives a 10/10 release-ready score.
- **judge_faithful** · wide_bass_mix__as_recorded: The claim 'Mastering will push the low end harder, and anything phasey down there gets worse, not better' is an added assumption not supported by the report, which says nothing about mastering intensifying phase issues.
- **judge_groups_causes** · polarity_mix__other_stage: The notes claim F1, F4, F3, and F2 are 'one problem showing up in four ways' and that fixing polarity means 'the rest should follow,' but the report treats F2 (wide low end from stereo widening on bass/kick) as a separate finding with its own distinct fix (mono-ing via Side EQ), not a guaranteed consequence of the polarity flip.
- **judge_stage_appropriate** · light_lows_master__trap_target: The report stage is 'master', so loudness should be judged against release standards, but the notes call the file 'clipping hard' and treat loudness as 'the problem' in headline/summary as if it's simply wrong rather than a stage-appropriate release consideration; also true peak over full scale is real but framing conflates limiter drive as strictly bad without noting it's a release-ready master needing peak-safety, not headroom for mastering elsewhere.
- **judge_stage_appropriate** · song01__other_stage: For a master stage, the report explicitly scored the loudness/measurements as 10/10 release-ready with no loudness finding, yet the notes headline calls -17.11 LUFS 'quiet' and 'worth a look before release', introducing an unsupported loudness critique.
- **numbers_grounded** · clean_master__trap_target: not in the report: 40 seconds
- **numbers_grounded** · polarity_mix__other_stage: not in the report: 40 seconds
