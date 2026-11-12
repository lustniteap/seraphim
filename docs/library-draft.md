# Explanation library: draft for review

Status: **draft**. Drafted from general mixing knowledge. Every entry is unverified until Tyler approves it; until then the source label for anything taken from here is 'general knowledge', never 'library'. Causes are ranked, most usual first. 'upstream' means the cause happened at recording or an earlier mix stage, so it gets a Vigil (prevention) line. 'ask' is the one question that would tell the causes apart. 'fix_actions' are ids from catalog.ACTIONS; code writes the steps for the person's own setup.

Mark each entry: keep, change (write the change), or drop. Add what is missing.

## Stage 1: Gain staging

### clipping  (`clipping`; scope mix)

**Issue.** Runs of samples hit full scale and are flattened, which sounds as crackle or harshness.

**Why it likely happened** (most usual first):
- [common] A track or bus is driven too hot into the master, so the master bus clips before any limiter. *(upstream)* Ask: Does the master fader meter go red at those times?
- [common] Recorded too hot, so the take itself is clipped at the converter. *(upstream)*
- [possible] A limiter or saturator with the ceiling at 0 dB is clipping the output.
- [possible] The bounce was normalised or gained up after the mix.

**Fix actions.** clip_gain, master_headroom, limit_true_peak

**Vigil (next time).**
- Record with peaks around -18 to -10 dBFS; there is no benefit to recording hot at 24-bit.
- Leave the master bus peaking around -6 dBFS while mixing.

**Check.** No runs of clipped samples.

Your verdict: keep / change / drop

### dc_offset  (`dc_offset`; scope mix)

**Issue.** The waveform sits off centre, which wastes headroom and can cause clicks at edits.

**Why it likely happened** (most usual first):
- [common] A synth, sample or plugin outputs a constant offset. *(upstream)*
- [rare] A cheap or faulty input stage in the recording chain. *(upstream)*

**Fix actions.** remove_dc, highpass_vocal

**Vigil (next time).**
- Put a high-pass filter at about 20 to 30 Hz on every source that does not need sub-bass.

**Check.** DC offset below the warning level.

Your verdict: keep / change / drop

## Stage 2: Cleanup

### vocal_rumble  (`vocal_rumble`; scope vocal)

**Issue.** There is low energy below the voice that adds weight without adding anything useful.

**Why it likely happened** (most usual first):
- [common] No high-pass filter on the vocal: handling noise, mic stand rumble, plosives or room noise get through.
- [possible] Proximity effect from singing very close to the microphone. *(upstream)* Ask: How far from the microphone were you?
- [possible] Air-conditioning or traffic noise in the recording space. *(upstream)*

**Fix actions.** highpass_vocal

**Vigil (next time).**
- Use a mic stand with a shock mount and a pop filter, and switch on the microphone's own high-pass filter if it has one.
- Turn off air conditioning and fans during takes.

**Check.** Little vocal energy below about 80 Hz.

Your verdict: keep / change / drop

## Stage 3: Tone EQ

### vocal_muddy  (`vocal_muddy`; scope vocal)

**Issue.** The vocal sounds boxy or cloudy around the low mids.

**Why it likely happened** (most usual first):
- [common] Proximity effect: close to a directional microphone boosts 150 to 300 Hz. *(upstream)* Ask: How close were you to the microphone, and is it a cardioid?
- [common] A small untreated room adds a boxy resonance. *(upstream)* Ask: Is the room treated, or were you in a small bare room?
- [possible] Stacked EQ boosts or a compressor that brings up the low mids.
- [possible] Other instruments occupy the same range and mask the vocal.

**Fix actions.** cut_vocal_mud, highpass_vocal, eq_cut_band

**Vigil (next time).**
- Record a little further from the microphone, or angle the voice slightly off axis.
- Hang a blanket or absorber behind the singer; treat the wall behind the microphone first.

**Check.** Low-mid vocal energy within the range for the style.

Your verdict: keep / change / drop

### vocal_thin  (`vocal_thin`; scope vocal)

**Issue.** The vocal lacks body and sounds thin.

**Why it likely happened** (most usual first):
- [common] The high-pass filter is set too high, cutting into the body of the voice. Ask: Where is the high-pass filter set?
- [common] Recorded far from the microphone or off axis, so the low end is missing. *(upstream)*
- [possible] Overcutting while chasing mud.

**Fix actions.** add_vocal_warmth, eq_boost_band

**Vigil (next time).**
- Keep a consistent distance (a hand width or two) from the microphone.

**Check.** Body-range vocal energy within the range for the style.

Your verdict: keep / change / drop

### no_air  (`no_air`; scope mix)

**Issue.** There is little energy in the top octave, so the mix sounds dull or closed.

**Why it likely happened** (most usual first):
- [common] The audio was a low-bitrate MP3 or other lossy file, which cuts the top end. *(upstream)* Ask: Was this exported from a lossy file or an MP3?
- [common] A low-pass filter or dark plugin chain on the master or in a sample.
- [possible] Dark source recordings with no top-end lift in the mix. *(upstream)*

**Fix actions.** find_lowpass, eq_boost_band

**Vigil (next time).**
- Always work from lossless files (WAV or AIFF) and keep the original recording takes.

**Check.** Top-octave energy within the range for the style.

Your verdict: keep / change / drop

### tone_off_balance  (`tone_more_than_target`, `tone_less_than_target`, `ref_tone_more`, `ref_tone_less`; scope mix)

**Issue.** One tone band is stronger or weaker than the usual range for the style.

**Why it likely happened** (most usual first):
- [common] Monitors or a room that misrepresent that band, so it was over- or under-corrected. *(upstream)* Ask: What do you mix on, and have you checked against a reference song?
- [possible] A boost or cut on the master or a bus that was never re-checked.
- [possible] An intentional creative choice. Ask: Was that on purpose?

**Fix actions.** eq_cut_band, eq_boost_band

**Vigil (next time).**
- Check the mix against a reference song at matched volume on a second set of speakers or headphones.

**Check.** Tone bands within the range for the style at matched volume.

Your verdict: keep / change / drop

## Stage 4: Dynamics

### vocal_uncompressed  (`vocal_uncompressed`; scope vocal)

**Issue.** The vocal's level varies a lot, so some words are lost and others jump out.

**Why it likely happened** (most usual first):
- [common] No compression, or a compressor with a threshold set too high to engage.
- [common] A naturally wide dynamic range from the performance and microphone distance. *(upstream)* Ask: Did your distance to the microphone change during the take?
- [possible] Volume automation is missing for the quietest and loudest words.

**Fix actions.** compress_vocal, volume_automation

**Vigil (next time).**
- Hold a steady distance from the microphone and step back slightly on loud lines.

**Check.** Vocal dynamic range within the range for the style.

Your verdict: keep / change / drop

### flat_dynamics  (`low_lra`, `less_contrast_than_target`, `ref_less_contrast`; scope mix)

**Issue.** Quiet and loud sections are almost the same level, so the song feels flat.

**Why it likely happened** (most usual first):
- [common] Heavy compression or limiting on the master flattens the sections.
- [common] No level automation between verse and chorus.
- [possible] The arrangement itself stays at one density. *(upstream)*

**Fix actions.** volume_automation, restore_transients

**Vigil (next time).**
- Plan contrast in the arrangement: let the verse be sparser than the chorus before reaching for the mix bus.

**Check.** Loudness range within the range for the style.

Your verdict: keep / change / drop

### too_dynamic  (`more_contrast_than_target`, `more_dynamic_than_target`, `ref_more_contrast`, `ref_more_dynamic`; scope mix)

**Issue.** The level varies more than is usual for the style, so quiet parts can get lost.

**Why it likely happened** (most usual first):
- [common] Not enough compression on the mix bus, or no limiter yet.
- [possible] Large level jumps between sections.

**Fix actions.** tame_contrast, glue_compression

**Check.** Loudness range and loudness-to-peak ratio within the range.

Your verdict: keep / change / drop

## Stage 5: De-essing

### vocal_sibilant  (`vocal_sibilant`; scope vocal)

**Issue.** S and T sounds are sharp or piercing.

**Why it likely happened** (most usual first):
- [common] No de-esser, or the de-esser is set too gently.
- [common] A bright microphone, or a high-frequency boost before compression, exaggerates sibilance. *(upstream)* Ask: Which microphone, and is there an air-band boost before the compressor?
- [possible] Compression after a bright EQ makes sibilants louder relative to the rest.
- [possible] Singing directly into the microphone rather than slightly off axis. *(upstream)*

**Fix actions.** deess_vocal

**Vigil (next time).**
- Sing slightly off axis or use a pop filter placed a little further out.
- Choose a smoother microphone for bright voices.

**Check.** Sibilant-band energy relative to the vocal within the range.

Your verdict: keep / change / drop

## Stage 8: Level and balance

### vocal_buried  (`vocal_buried`; scope vocal)

**Issue.** The vocal sits too far back against the music.

**Why it likely happened** (most usual first):
- [common] The vocal fader is too low, or the beat is too loud for the vocal.
- [common] Competing instruments fill the vocal's frequency range.
- [possible] The vocal has too much dynamic range, so quiet words are masked.

**Fix actions.** raise_vocal, compress_vocal

**Vigil (next time).**
- Mix the vocal first, then build the instruments around it.

**Check.** Vocal-to-mix level within the range for the style.

Your verdict: keep / change / drop

### vocal_dominant  (`vocal_dominant`; scope vocal)

**Issue.** The vocal sits too far forward over the music.

**Why it likely happened** (most usual first):
- [common] The vocal fader is too high, or the beat is quieter than it should be.
- [possible] Heavy compression and brightness make the vocal feel upfront.

**Fix actions.** lower_vocal

**Check.** Vocal-to-mix level within the range for the style.

Your verdict: keep / change / drop

## Stage 9: Stereo and phase

### polarity  (`negative_correlation`; scope mix)

**Issue.** The left and right channels are largely opposite, so the mix will cancel in mono.

**Why it likely happened** (most usual first):
- [common] One side of a stereo source or a microphone pair is polarity-inverted. *(upstream)* Ask: Is there a stereo pair or two-mic source, and did you flip one side?
- [possible] A stereo widener or Haas-style effect pushes the sides out of phase.
- [rare] A stem or sample was exported with one channel inverted. *(upstream)*

**Fix actions.** correlation_meter, invert_track, flip_one_side

**Vigil (next time).**
- Check polarity between multi-mic sources as soon as they are recorded, before processing.

**Check.** Overall left/right correlation above zero.

Your verdict: keep / change / drop

### mono_collapse  (`mono_loss`, `phase_section`; scope mix)

**Issue.** Parts of the mix lose level or vanish when summed to mono.

**Why it likely happened** (most usual first):
- [common] Wide stereo effects (chorus, doubler, widener, stereo reverb) put too much of the signal in the sides. Ask: Which stereo effects are on the vocal or the master?
- [possible] Doubled or stereo-recorded parts are slightly out of phase with each other. *(upstream)*
- [possible] A sample or pad was built with wide, out-of-phase stereo. *(upstream)*

**Fix actions.** mono_check, narrow_width, correlation_meter

**Vigil (next time).**
- Check the mix in mono each time a stereo effect is added, not only at the end.

**Check.** Mono loss under the warning level and no sustained negative-correlation sections.

Your verdict: keep / change / drop

### wide_low_end  (`wide_low_end`; scope mix)

**Issue.** The bass and kick are spread across left and right, so they thin out in mono and on club or vinyl systems.

**Why it likely happened** (most usual first):
- [common] A stereo bass or 808 sample, or a widener on the bass bus, carries low frequencies in the sides. Ask: Is there a stereo effect on the bass or 808?
- [possible] A stereo synth pad or sample has strong sub content. *(upstream)*

**Fix actions.** mono_low_end, narrow_width

**Vigil (next time).**
- Keep bass and kick in the centre from the start; add width above about 120 Hz only.

**Check.** Correlation below the crossover frequency stays high.

Your verdict: keep / change / drop

### imbalance  (`imbalance`; scope mix)

**Issue.** The mix leans to one side.

**Why it likely happened** (most usual first):
- [common] A loud part (a guitar, a pad, an ad-lib) is panned hard one way without a counterweight.
- [possible] A plugin or channel on the master processes the sides unevenly.
- [possible] A mono source was recorded or exported to one side only. *(upstream)*

**Fix actions.** recenter_image

**Vigil (next time).**
- Balance the pan positions of loud elements as you place them.

**Check.** Left/right level difference under the warning level.

Your verdict: keep / change / drop

### width_off_target  (`ref_wider`, `ref_narrower`; scope mix)

**Issue.** The stereo width differs from the reference.

**Why it likely happened** (most usual first):
- [common] Stereo effects and panning differ from the reference's arrangement.
- [possible] A widener or mid/side processing on the master.

**Fix actions.** widen_image, narrow_width

**Check.** Stereo width close to the reference's range.

Your verdict: keep / change / drop

## Stage 10: Master bus

### true_peak_ceiling  (`true_peak_over`, `true_peak_hot`; scope master)

**Issue.** Peaks can go above the delivery ceiling once the file is converted or played back.

**Why it likely happened** (most usual first):
- [common] The limiter's ceiling is set to 0 dB, which sample-peak limiters allow to overshoot between samples. Ask: What is the limiter's output ceiling set to?
- [common] Something after the limiter (tape, saturation, a clipper, a gain stage) adds level. Ask: Is any plugin after the limiter on the master?
- [possible] The master was pushed harder after an earlier approved version.

**Fix actions.** limit_true_peak, loudness_meter, master_headroom

**Vigil (next time).**
- Make the true-peak limiter the last plugin on the master from the start of the session, and keep its ceiling at -1.0 dBTP.

**Check.** True peak at or below -1.0 dBTP on a master; above 0 dBTP is an error at any stage.

Your verdict: keep / change / drop

### ending  (`abrupt_end`, `long_head`, `long_tail`; scope master)

**Issue.** The file starts or ends in a way that is not what was probably intended.

**Why it likely happened** (most usual first):
- [common] The bounce range was set a little short or long.
- [common] A reverb or delay tail was cut off by the end marker. Ask: Does the song end on a reverb or delay tail?
- [possible] Silence was left on purpose. Ask: Is the silence intentional?

**Fix actions.** include_tail, fade_out, trim_silence

**Check.** No loud last sample; no long silences unless wanted.

Your verdict: keep / change / drop

### over_limited  (`low_plr`, `more_limited_than_target`, `ref_more_limited`; scope master)

**Issue.** The loudness is held very close to the peak level, so the mix has little punch or dynamic movement.

**Why it likely happened** (most usual first):
- [common] The limiter's gain is pushed hard to reach a loudness target.
- [common] A mix-bus compressor and a limiter are both working hard. Ask: Is there a compressor or clipper on the master as well as the limiter?
- [possible] The mix itself had little dynamics because the sources were heavily compressed.

**Fix actions.** ease_limiting, restore_transients, ease_bus_comp

**Vigil (next time).**
- Mix toward a loudness you can reach with 2 to 3 dB of limiting, not 8 or more.

**Check.** Loudness-to-peak ratio within the range for the style.

Your verdict: keep / change / drop

### too_loud  (`very_loud`, `louder_than_target`, `ref_louder`; scope master)

**Issue.** The master is louder than the usual range for the style.

**Why it likely happened** (most usual first):
- [common] The limiter is pushed for competitive loudness.
- [possible] The mix reached the master very hot, leaving the limiter nothing but heavy gain.

**Fix actions.** ease_limiting, loudness_meter

**Check.** Integrated loudness near the style range.

Your verdict: keep / change / drop

### too_quiet  (`quieter_than_target`, `ref_quieter`; scope master)

**Issue.** The master is quieter than the usual range for the style.

**Why it likely happened** (most usual first):
- [common] No limiter or too little gain into it, as the file is still a mix. Ask: Is this a mix for mastering or the final master?
- [possible] A deliberate quiet, dynamic master.

**Fix actions.** push_limiting, loudness_meter

**Check.** Integrated loudness near the style range.

Your verdict: keep / change / drop
