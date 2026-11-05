"""What each user's tools can do, and exactly how to do it with them.

Fixes (remediation.py) are written as tool-neutral *actions*, such as
"limit_true_peak". This catalog says which tools can perform each action and
how, in that tool's own words. When a report is built, each action is matched
to the best tool the user actually owns.

Adding a plugin means adding one entry to TOOLS; every fix that uses its
actions picks it up automatically. The same actions are what an in-app fixer
would apply later, so keep them concrete.

Text placeholders: {value} {times} {start} {end}, and for reference tone {band} {amount} {shape}
"""

# What the user picks in setup: one DAW, plus any number of packages.
DAWS = {
    "pro_tools": "Pro Tools",
    "logic": "Logic Pro",
    "ableton": "Ableton Live",
    "fl_studio": "FL Studio",
    "other": "Other DAW",
}

PACKAGES = {
    "waves_l2": {"name": "L2", "group": "Waves"},
    "waves_f6": {"name": "F6", "group": "Waves"},
    "waves_ren_eq": {"name": "Renaissance EQ", "group": "Waves"},
    "waves_ren_comp": {"name": "Renaissance Compressor", "group": "Waves"},
    "waves_s1_imager": {"name": "S1 Stereo Imager", "group": "Waves"},
    "waves_s1_shuffler": {"name": "S1 Shuffler", "group": "Waves"},
    "waves_paz": {"name": "PAZ Analyzer", "group": "Waves"},
    "waves_wlm": {"name": "WLM Plus", "group": "Waves"},
    "fabfilter": {"name": "FabFilter (Pro-L 2, Pro-Q, Pro-C 2)", "group": "FabFilter"},
    "izotope_ozone": {"name": "iZotope Ozone", "group": "iZotope"},
    "izotope_insight": {"name": "iZotope Insight 2", "group": "iZotope"},
}

# Ids that older saved setups, scripts and eval cases use, each standing for several current ones.
# "waves_essential" used to be one item covering these four Waves plugins.
LEGACY_PACKAGES = {
    "waves_essential": ["waves_l2", "waves_f6", "waves_ren_eq", "waves_ren_comp"],
}

# Waves sells its plugins as subscription tiers. These are the plugins in each tier that Seraphim has
# fix steps for, from Waves' own plugin list (waves.com, checked 2026-10-14: the list flags each plugin
# for the low tier, Waves Essential, and the high tier, Waves Ultimate). Ultimate also has L3 and many
# more, which Seraphim can't write steps for yet. S1 Shuffler isn't in either tier, so it's chosen alone.
_ESSENTIAL = ["waves_l2", "waves_f6", "waves_ren_eq", "waves_ren_comp", "waves_s1_imager", "waves_paz", "waves_wlm"]
WAVES_TIERS = {
    "essential": {"name": "Waves Essential", "plugins": _ESSENTIAL},
    "ultimate": {"name": "Waves Ultimate", "plugins": _ESSENTIAL},
}

# Every action a fix can ask for, with wording that works in any DAW.
ACTIONS = {
    "limit_true_peak": "Put a true-peak limiter last on the master with its ceiling at −1.0 dBTP.",
    "ease_limiting": "Turn the limiter's input gain down (or its threshold up) by 2–4 dB and compare at matched volume.",
    "remove_mix_limiting": "Bypass any limiter or maximizer on the mix bus before you bounce for mastering.",
    "master_headroom": "Lower the level into the master bus (a gain plugin first on the master) until peaks sit around −6 to −3 dBFS.",
    "clip_gain": "Turn down the clip or region gain on the part that clips around {times}.",
    "ease_bus_comp": "Ease the mix-bus compressor: raise the threshold or slow the attack so transients get through.",
    "restore_transients": "On the drum bus, use a compressor with a slower attack (10–30 ms) or a transient shaper to bring back punch.",
    "volume_automation": "Automate volume so verses sit 2–3 dB below choruses.",
    "flip_one_side": "Put a gain/utility plugin on the suspect track and flip polarity on one side only to test.",
    "invert_track": "If one track is inverted all the way through, invert its polarity permanently.",
    "mono_check": "Sum the master to mono and listen for parts that disappear.",
    "mono_low_end": "Make everything below about 150 Hz mono, with a bass-mono tool or a mid/side EQ cutting the side channel below 150 Hz.",
    "narrow_width": "Reduce stereo widening (chorus, doublers, wideners, very short stereo delays) on the tracks that vanish in mono.",
    "correlation_meter": "Watch a correlation meter while you loop {start}–{end}; it should stay above 0.",
    "remove_dc": "Remove the DC offset on the source tracks, or high-pass the master at 20 Hz.",
    "recenter_image": "Check the panning of the loudest elements and any reverb or delay returns that lean one way.",
    "trim_silence": "Set the bounce range to start at the first note and end shortly after the last tail.",
    "include_tail": "Extend the bounce range past the last reverb and delay tails, then bounce again.",
    "fade_out": "Add a short fade-out at the end of the last region, then bounce again.",
    "find_lowpass": "Look for a low-pass filter on the master or a bus cutting everything above 16 kHz.",
    "push_limiting": "Raise the limiter's input gain (or lower its threshold) in 1 dB steps until you reach the target, keeping the ceiling at −1.0 dBTP.",
    "glue_compression": "Add gentle bus compression (1.5:1 to 2:1, slow attack, auto or medium release) for 1–2 dB of gain reduction.",
    "tame_contrast": "Ride the quietest sections up 1–2 dB with volume automation so the song holds together at one listening level.",
    "loudness_meter": "Before bouncing, play the whole song through a loudness meter and check integrated LUFS and true peak.",
    "eq_cut_band": "On the master bus, use a broad EQ ({shape}) to lower {band} by about {amount} dB, then A/B it at matched volume.",
    "eq_boost_band": "On the master bus, use a broad EQ ({shape}) to raise {band} by about {amount} dB, then A/B it at matched volume.",
    "widen_image": "Widen the loud sections a little with a stereo imager on the pads, guitars and backing vocals (or gently on the master), keeping everything below about 150 Hz mono.",
    # The vocal on its own (vocal.py)
    "compress_vocal": "Put a compressor on the vocal: ratio about 3:1, attack 10–20 ms, fast release, for 3–6 dB of gain reduction on the loudest words.",
    "highpass_vocal": "Put an EQ on the vocal and high-pass it around 80–100 Hz to clear rumble and plosives.",
    "cut_vocal_mud": "On the vocal's EQ, cut 2–4 dB with a medium-width bell somewhere between 200 and 400 Hz; sweep to find where it clears.",
    "add_vocal_warmth": "On the vocal's EQ, add a gentle 1–3 dB low shelf or wide bell around 150–250 Hz, then check it doesn't turn muddy.",
    "deess_vocal": "Put a de-esser on the vocal, centered around 5–8 kHz, taking 3–5 dB off the loudest 's' sounds.",
    "raise_vocal": "Raise the vocal fader about 2 dB and compare against the beat at matched volume.",
    "lower_vocal": "Lower the vocal fader about 2 dB and compare against the beat at matched volume.",
}

# id -> {name, in: packages or DAWs that include it, can: {action: (rank, how)}}
# Higher rank wins when a user owns several tools for the same action.
TOOLS = {
    # Pro Tools stock
    "pt_pro_limiter": {"name": "Pro Limiter", "in": ["pro_tools"], "can": {
        "limit_true_peak": (3, "Insert Pro Limiter last on the Master Fader, turn on ISP, and set Ceiling to −1.0 dB."),
        "ease_limiting": (2, "Lower Pro Limiter's Input by 2–4 dB and compare at matched volume."),
        "push_limiting": (2, "Raise Pro Limiter's Input in 1 dB steps until you reach the target; keep ISP on and Ceiling at −1.0 dB."),
        "remove_mix_limiting": (2, "Bypass Pro Limiter (and any other limiter) on the Master Fader before bouncing for mastering."),
        "loudness_meter": (2, "Watch Pro Limiter's loudness meter (Integrated LUFS) while the whole song plays."),
    }},
    "pt_dyn3": {"name": "Compressor/Limiter Dyn 3", "in": ["pro_tools"], "can": {
        "compress_vocal": (2, "Insert Compressor/Limiter Dyn 3 on the vocal: Ratio 3:1, Attack 10–20 ms, Release 100 ms, for 3–6 dB of gain reduction on the loudest words."),
        "glue_compression": (2, "Insert Compressor/Limiter Dyn 3 on the Master Fader: Ratio 2:1, Attack 30 ms, for 1–2 dB of gain reduction."),
    }},
    "pt_trim": {"name": "Trim", "in": ["pro_tools"], "can": {
        "raise_vocal": (1, "Raise the vocal track's fader (or Trim) about 2 dB and compare against the beat at matched volume."),
        "lower_vocal": (1, "Lower the vocal track's fader (or Trim) about 2 dB and compare against the beat at matched volume."),
        "master_headroom": (2, "Insert Trim first on the Master Fader and lower Gain until peaks sit around −6 to −3 dBFS."),
        "flip_one_side": (2, "Insert Trim as multi-mono on the stereo track and click Ø on one side only."),
    }},
    "pt_clip_gain": {"name": "Clip Gain", "in": ["pro_tools"], "can": {
        "clip_gain": (3, "Select the clip at {times} and lower its Clip Gain (Control-Shift-Down Arrow) until the clip indicator stays clear."),
        "volume_automation": (1, "Use Clip Gain on the verse clips so they sit 2–3 dB below the choruses."),
    }},
    "pt_automation": {"name": "Volume automation", "in": ["pro_tools"], "can": {
        "volume_automation": (2, "Write volume automation (or use Clip Gain) so verses sit 2–3 dB below choruses."),
    }},
    "pt_eq3": {"name": "EQ3 7-Band", "in": ["pro_tools"], "can": {
        "highpass_vocal": (2, "Insert EQ3 7-Band on the vocal and turn on the high-pass filter at about 90 Hz."),
        "cut_vocal_mud": (2, "On EQ3 7-Band on the vocal, use a mid band with a medium Q between 200 and 400 Hz and cut 2–4 dB; sweep to find where it clears."),
        "add_vocal_warmth": (2, "On EQ3 7-Band on the vocal, use the low-mid band around 150–250 Hz and add 1–3 dB, then check it doesn't turn muddy."),
        "eq_cut_band": (2, "Insert EQ3 7-Band on the Master Fader and use a {shape} over {band}, cutting about {amount} dB."),
        "eq_boost_band": (2, "Insert EQ3 7-Band on the Master Fader and use a {shape} over {band}, boosting about {amount} dB."),
    }},
    "pt_invert": {"name": "Invert AudioSuite", "in": ["pro_tools"], "can": {
        "invert_track": (3, "Select the whole clip and run AudioSuite › Other › Invert."),
    }},
    "pt_dc_removal": {"name": "DC Offset Removal", "in": ["pro_tools"], "can": {
        "remove_dc": (3, "Select the affected clips and run AudioSuite › Other › DC Offset Removal."),
    }},
    "pt_bounce": {"name": "Bounce Mix", "in": ["pro_tools"], "can": {
        "trim_silence": (3, "Tighten the timeline selection so it starts at the first note, then File › Bounce Mix."),
        "include_tail": (3, "Extend the timeline selection past the last reverb and delay tails, then File › Bounce Mix again."),
        "fade_out": (3, "Select the end of the last clip, press Command-F to add a fade-out, and bounce again."),
    }},

    # Logic Pro stock
    "logic_adaptive_limiter": {"name": "Adaptive Limiter", "in": ["logic"], "can": {
        "limit_true_peak": (3, "Put Adaptive Limiter last on the Stereo Out, turn on True Peak Detection, and set Out Ceiling to −1.0 dB."),
        "ease_limiting": (2, "Lower Adaptive Limiter's Gain by 2–4 dB and compare at matched volume."),
        "push_limiting": (2, "Raise Adaptive Limiter's Gain in 1 dB steps until you reach the target; keep Out Ceiling at −1.0 dB."),
        "remove_mix_limiting": (2, "Bypass Adaptive Limiter (and any other limiter) on the Stereo Out before bouncing for mastering."),
    }},
    "logic_compressor": {"name": "Compressor", "in": ["logic"], "can": {
        "compress_vocal": (2, "Insert Compressor on the vocal (Studio VCA or Platinum Digital): Ratio 3:1, Attack 10–20 ms, for 3–6 dB of gain reduction on the loudest words."),
        "glue_compression": (2, "Insert Compressor on the Stereo Out, choose Vintage VCA, Ratio 2:1, slow attack, for 1–2 dB of gain reduction."),
    }},
    "logic_gain": {"name": "Gain", "in": ["logic"], "can": {
        "master_headroom": (2, "Put Utility › Gain first on the Stereo Out and lower Gain until peaks sit around −6 to −3 dBFS."),
        "flip_one_side": (3, "Insert Utility › Gain on the track and turn on Phase Invert for Left or Right only."),
        "invert_track": (2, "Insert Utility › Gain on the track and turn on Phase Invert for both sides."),
        "mono_check": (2, "Insert Utility › Gain on the Stereo Out and set Mono to hear the mix summed."),
    }},
    "logic_channel_eq": {"name": "Channel EQ", "in": ["logic"], "can": {
        "highpass_vocal": (2, "Add Channel EQ on the vocal and turn on Low Cut at about 90 Hz."),
        "cut_vocal_mud": (2, "On Channel EQ on the vocal, use a band with a medium Q between 200 and 400 Hz and cut 2–4 dB; sweep to find where it clears."),
        "add_vocal_warmth": (2, "On Channel EQ on the vocal, use the Low Shelf or a wide band around 150–250 Hz and add 1–3 dB, then check it doesn't turn muddy."),
        "mono_low_end": (2, "Add a Channel EQ, set Processing to Side, and turn on Low Cut at 150 Hz so the lows are mono."),
        "eq_cut_band": (2, "Add Channel EQ on the Stereo Out and use a {shape} over {band}, cutting about {amount} dB."),
        "eq_boost_band": (2, "Add Channel EQ on the Stereo Out and use a {shape} over {band}, boosting about {amount} dB."),
        "remove_dc": (1, "Turn on Channel EQ's Low Cut at 20 Hz on the Stereo Out."),
    }},
    "logic_direction_mixer": {"name": "Direction Mixer", "in": ["logic"], "can": {
        "narrow_width": (2, "Insert Imaging › Direction Mixer on the tracks that vanish in mono and lower Spread below 1.0."),
        "widen_image": (2, "Insert Imaging › Direction Mixer on the pads, guitars and backing vocals and raise Spread above 1.0; leave bass and kick alone."),
    }},
    "logic_meters": {"name": "Loudness Meter / MultiMeter", "in": ["logic"], "can": {
        "loudness_meter": (2, "Insert Metering › Loudness Meter on the Stereo Out and play the whole song; read the Integrated value."),
        "correlation_meter": (2, "Insert Metering › MultiMeter on the Stereo Out and watch Correlation while you loop {start}–{end}."),
    }},
    "logic_region": {"name": "Region inspector", "in": ["logic"], "can": {
        "clip_gain": (3, "Select the region at {times} and lower Gain in the Region inspector until it stops clipping."),
        "fade_out": (2, "Set a Fade Out on the last region in the Region inspector, then bounce again."),
    }},
    "logic_automation": {"name": "Volume automation", "in": ["logic"], "can": {
        "volume_automation": (2, "Press A to show automation and draw volume so verses sit 2–3 dB below choruses."),
    }},
    "logic_bounce": {"name": "Bounce", "in": ["logic"], "can": {
        "trim_silence": (3, "Set the cycle range to start at the first note, then File › Bounce › Project or Section (Command-B)."),
        "include_tail": (3, "In the Bounce window, turn on Include Audio Tail (or extend the cycle range past the last tail)."),
    }},

    "pt_deesser": {"name": "Dyn 3 De-Esser", "in": ["pro_tools"], "can": {
        "deess_vocal": (2, "Insert Dyn 3 De-Esser on the vocal, set the frequency around 6–8 kHz, and lower the Threshold until the loudest 's' sounds drop 3–5 dB."),
    }},
    "logic_deesser": {"name": "DeEsser 2", "in": ["logic"], "can": {
        "deess_vocal": (2, "Insert DeEsser 2 on the vocal, set Frequency around 6–8 kHz, and raise Suppression until the loudest 's' sounds drop 3–5 dB."),
    }},
    "ff_pro_ds": {"name": "FabFilter Pro-DS", "in": ["fabfilter"], "can": {
        "deess_vocal": (3, "Put Pro-DS on the vocal in Allround mode and lower the Threshold until the loudest 's' sounds drop 3–5 dB."),
    }},

    # Ableton Live stock
    "live_limiter": {"name": "Limiter", "in": ["ableton"], "can": {
        "limit_true_peak": (2, "Put Limiter last on the Main track with Ceiling at −1.0 dB and True Peak on (Live 12; on older versions use −1.5 dB)."),
        "ease_limiting": (2, "Lower Limiter's Gain by 2–4 dB and compare at matched volume."),
        "push_limiting": (2, "Raise Limiter's Gain in 1 dB steps until you reach the target; keep Ceiling at −1.0 dB."),
        "remove_mix_limiting": (2, "Turn off Limiter (and any other limiter) on the Main track before exporting for mastering."),
    }},
    "live_glue": {"name": "Glue Compressor", "in": ["ableton"], "can": {
        "compress_vocal": (2, "Put Glue Compressor (or the stock Compressor) on the vocal: Ratio 4, Attack 10 ms, Release 0.2, for 3–6 dB of reduction on the loudest words."),
        "glue_compression": (3, "Put Glue Compressor on the Main track: Ratio 2, Attack 10–30 ms, Release Auto, for 1–2 dB of reduction."),
    }},
    "live_utility": {"name": "Utility", "in": ["ableton"], "can": {
        "master_headroom": (2, "Put Utility first on the Main track and lower Gain until peaks sit around −6 to −3 dBFS."),
        "flip_one_side": (3, "Add Utility to the track and turn on Invert for the Left or Right channel only."),
        "invert_track": (3, "Add Utility to the track and turn on Invert for both channels."),
        "mono_check": (3, "Add Utility to the Main track and switch on Mono."),
        "mono_low_end": (3, "Add Utility to the track (or the Main track) and turn on Bass Mono at about 120 Hz."),
        "narrow_width": (2, "Lower Utility's Width on the tracks that vanish in mono."),
        "widen_image": (2, "Raise Utility's Width to 110–130% on the pads, guitars and backing vocals; keep Bass Mono on."),
        "remove_dc": (3, "Turn on Utility's DC filter on the affected tracks."),
    }},
    "live_eq8": {"name": "EQ Eight", "in": ["ableton"], "can": {
        "highpass_vocal": (3, "Put EQ Eight on the vocal and use band 1 as a high-pass at about 90 Hz."),
        "cut_vocal_mud": (3, "On EQ Eight on the vocal, use a bell between 200 and 400 Hz and cut 2–4 dB; sweep to find where it clears."),
        "add_vocal_warmth": (3, "On EQ Eight on the vocal, use a low shelf or wide bell around 150–250 Hz and add 1–3 dB, then check it doesn't turn muddy."),
        "eq_cut_band": (2, "Put EQ Eight on the Main track and use a {shape} over {band}, cutting about {amount} dB."),
        "eq_boost_band": (2, "Put EQ Eight on the Main track and use a {shape} over {band}, boosting about {amount} dB."),
    }},
    "live_clip": {"name": "Clip View", "in": ["ableton"], "can": {
        "clip_gain": (3, "Open the clip at {times} and lower its Gain in Clip View until it stops clipping."),
        "fade_out": (2, "Drag a fade-out on the last clip in the Arrangement, then export again."),
    }},
    "live_automation": {"name": "Volume automation", "in": ["ableton"], "can": {
        "volume_automation": (2, "Press A for automation mode and draw volume so verses sit 2–3 dB below choruses."),
    }},
    "live_export": {"name": "Export Audio/Video", "in": ["ableton"], "can": {
        "trim_silence": (3, "Select the Arrangement from the first note to the end of the last tail, then File › Export Audio/Video."),
        "include_tail": (3, "Extend the Arrangement selection past the last reverb and delay tails, then export again."),
    }},

    # FL Studio stock
    "fl_limiter": {"name": "Fruity Limiter", "in": ["fl_studio"], "can": {
        "limit_true_peak": (1, "Put Fruity Limiter last on the Master and set Ceil to −1.5 dB (it doesn't measure true peak, so leave extra margin)."),
        "ease_limiting": (1, "Lower Fruity Limiter's Gain by 2–4 dB and compare at matched volume."),
        "push_limiting": (1, "Raise Fruity Limiter's Gain in 1 dB steps until you reach the target; keep Ceil at −1.5 dB."),
        "remove_mix_limiting": (2, "Bypass Fruity Limiter on the Master (the default template puts one there) before exporting for mastering."),
    }},
    "fl_mixer": {"name": "Mixer", "in": ["fl_studio"], "can": {
        "master_headroom": (2, "Pull down the Master mixer track's fader until peaks sit around −6 to −3 dBFS."),
        "mono_check": (2, "Turn the Master mixer track's stereo separation knob fully to merged to hear the mix in mono."),
        "narrow_width": (2, "Turn the stereo separation knob toward merged on the mixer tracks that vanish in mono."),
        "widen_image": (2, "Turn the stereo separation knob toward separated on the pads, guitars and backing vocals' mixer tracks."),
    }},
    "fl_stereo_enhancer": {"name": "Fruity Stereo Enhancer", "in": ["fl_studio"], "can": {
        "flip_one_side": (3, "Add Fruity Stereo Enhancer to the track's insert and set Phase Inversion to Left or Right."),
    }},
    "fl_parametric_eq": {"name": "Fruity Parametric EQ 2", "in": ["fl_studio"], "can": {
        "highpass_vocal": (2, "Add Fruity Parametric EQ 2 on the vocal's mixer track with a high-pass at about 90 Hz."),
        "cut_vocal_mud": (2, "On Fruity Parametric EQ 2 on the vocal, use a bell between 200 and 400 Hz and cut 2–4 dB; sweep to find where it clears."),
        "add_vocal_warmth": (2, "On Fruity Parametric EQ 2 on the vocal, use a low shelf or wide bell around 150–250 Hz and add 1–3 dB, then check it doesn't turn muddy."),
        "remove_dc": (1, "Add Fruity Parametric EQ 2 on the Master with a high-pass at 20 Hz."),
        "eq_cut_band": (2, "Add Fruity Parametric EQ 2 on the Master and use a {shape} over {band}, cutting about {amount} dB."),
        "eq_boost_band": (2, "Add Fruity Parametric EQ 2 on the Master and use a {shape} over {band}, boosting about {amount} dB."),
    }},
    "fl_automation": {"name": "Automation clip", "in": ["fl_studio"], "can": {
        "volume_automation": (2, "Right-click the track's fader › Create automation clip, and draw verses 2–3 dB below choruses."),
    }},
    "fl_export": {"name": "Export", "in": ["fl_studio"], "can": {
        "trim_silence": (2, "Remove empty bars at the start of the Playlist, then File › Export › WAV."),
        "include_tail": (3, "In File › Export, set Tail to Leave remainder so reverb and delay tails aren't cut."),
    }},

    # Waves Essential
    "waves_l2": {"name": "Waves L2", "in": ["waves_l2"], "can": {
        "limit_true_peak": (1, "Set the L2's Out Ceiling to −1.5 dB; the L2 limits sample peaks, so leave margin for true peaks."),
        "ease_limiting": (2, "Raise the L2's Threshold by 2–4 dB (less limiting) and compare at matched volume."),
        "push_limiting": (2, "Lower the L2's Threshold in 1 dB steps until you reach the target; keep Out Ceiling at −1.5 dB."),
        "remove_mix_limiting": (2, "Bypass the L2 on the master bus before bouncing for mastering."),
    }},
    "waves_f6": {"name": "Waves F6", "in": ["waves_f6"], "can": {
        "mono_low_end": (2, "Insert F6 in M/S mode and cut the Side below 150 Hz with a high-pass band."),
    }},
    "waves_renaissance_eq": {"name": "Renaissance EQ", "in": ["waves_ren_eq"], "can": {
        "highpass_vocal": (2, "Add Renaissance EQ on the vocal with a high-pass at about 90 Hz."),
        "cut_vocal_mud": (2, "On Renaissance EQ on the vocal, use a bell between 200 and 400 Hz and cut 2–4 dB; sweep to find where it clears."),
        "add_vocal_warmth": (2, "On Renaissance EQ on the vocal, use a low shelf or wide bell around 150–250 Hz and add 1–3 dB, then check it doesn't turn muddy."),
        "remove_dc": (1, "Add Renaissance EQ on the master with a high-pass at 20 Hz."),
        "eq_cut_band": (2, "Add Renaissance EQ on the master and use a {shape} over {band}, cutting about {amount} dB."),
        "eq_boost_band": (2, "Add Renaissance EQ on the master and use a {shape} over {band}, boosting about {amount} dB."),
    }},
    "waves_rcomp": {"name": "Renaissance Compressor", "in": ["waves_ren_comp"], "can": {
        "compress_vocal": (2, "Insert Renaissance Compressor on the vocal: Ratio about 3, Attack 10–20 ms, for 3–6 dB of gain reduction on the loudest words."),
        "restore_transients": (2, "On the drum bus, use Renaissance Compressor with a slower attack (10–30 ms) to let the hits through."),
    }},

    # Waves individual plugins
    "waves_s1_imager": {"name": "S1 Stereo Imager", "in": ["waves_s1_imager"], "can": {
        "mono_check": (3, "Put S1 Imager on the master and set Width to 0 to hear the mix in mono."),
        "recenter_image": (3, "Use S1 Imager's Rotation and Asymmetry controls to re-center a lopsided stereo source."),
        "narrow_width": (3, "Use S1 Imager on the tracks that vanish in mono and lower Width."),
        "widen_image": (3, "Use S1 Imager on the pads, guitars and backing vocals and raise Width a little at a time."),
    }},
    "waves_s1_shuffler": {"name": "S1 Shuffler", "in": ["waves_s1_shuffler"], "can": {
        "mono_low_end": (3, "Use S1 Shuffler on the stereo source and lower the width of just the low band."),
    }},
    "waves_paz": {"name": "PAZ Analyzer", "in": ["waves_paz"], "can": {
        "correlation_meter": (3, "Watch PAZ Analyzer's position/correlation display while you loop {start}–{end}."),
    }},
    "waves_wlm": {"name": "WLM Plus", "in": ["waves_wlm"], "can": {
        "loudness_meter": (3, "Put WLM Plus last on the master in true-peak mode and play the whole song before bouncing."),
    }},

    # FabFilter
    "ff_pro_l2": {"name": "FabFilter Pro-L 2", "in": ["fabfilter"], "can": {
        "limit_true_peak": (4, "Put Pro-L 2 last on the master, turn on True Peak Limiting, and set Output Level to −1.0 dB."),
        "ease_limiting": (3, "Lower Pro-L 2's Gain by 2–4 dB and use Unity Gain to compare at matched volume."),
        "push_limiting": (3, "Raise Pro-L 2's Gain in 1 dB steps until you reach the target; keep True Peak Limiting on at −1.0 dB."),
        "remove_mix_limiting": (2, "Bypass Pro-L 2 on the mix bus before bouncing for mastering."),
        "loudness_meter": (3, "Open Pro-L 2's loudness meters and read Integrated and True Peak over the whole song."),
    }},
    "ff_pro_q": {"name": "FabFilter Pro-Q", "in": ["fabfilter"], "can": {
        "highpass_vocal": (3, "In Pro-Q on the vocal, add a low cut at about 90 Hz."),
        "cut_vocal_mud": (3, "In Pro-Q on the vocal, add a bell between 200 and 400 Hz and cut 2–4 dB; sweep to find where it clears."),
        "add_vocal_warmth": (3, "In Pro-Q on the vocal, add a low shelf or wide bell around 150–250 Hz and raise it 1–3 dB, then check it doesn't turn muddy."),
        "mono_low_end": (3, "In Pro-Q, add a low cut at 150 Hz and set that band's stereo placement to Side."),
        "remove_dc": (2, "Add a Pro-Q low cut at 20 Hz on the master."),
        "eq_cut_band": (3, "In Pro-Q on the master, add a {shape} over {band} and pull it down about {amount} dB; turn on Auto Gain to compare at matched volume."),
        "eq_boost_band": (3, "In Pro-Q on the master, add a {shape} over {band} and raise it about {amount} dB; turn on Auto Gain to compare at matched volume."),
    }},
    "ff_pro_c2": {"name": "FabFilter Pro-C 2", "in": ["fabfilter"], "can": {
        "compress_vocal": (3, "Put Pro-C 2 on the vocal in Vocal style: Ratio about 3:1, Attack 10–20 ms, for 3–6 dB of gain reduction on the loudest words."),
        "restore_transients": (3, "On the drum bus, use Pro-C 2 in Punch style with a slower attack (10–30 ms)."),
        "ease_bus_comp": (3, "In Pro-C 2 on the mix bus, raise Threshold or lengthen Attack until transients come through."),
        "glue_compression": (3, "Put Pro-C 2 on the mix bus in Bus style: Ratio 2:1, slow attack, for 1–2 dB of gain reduction."),
    }},

    # iZotope
    "ozone_maximizer": {"name": "Ozone Maximizer", "in": ["izotope_ozone"], "can": {
        "limit_true_peak": (4, "In Ozone's Maximizer, turn on True Peak and set Ceiling to −1.0 dB."),
        "ease_limiting": (3, "Raise the Maximizer's Threshold by 2–4 dB and use Gain Match to compare."),
        "push_limiting": (3, "Lower the Maximizer's Threshold in 1 dB steps until you reach the target; keep True Peak on at −1.0 dB."),
        "remove_mix_limiting": (2, "Bypass Ozone on the mix bus before bouncing for mastering."),
    }},
    "ozone_imager": {"name": "Ozone Imager", "in": ["izotope_ozone"], "can": {
        "mono_low_end": (3, "In Ozone Imager, go multiband and set the lowest band (below about 120 Hz) to Width −100."),
        "narrow_width": (2, "In Ozone Imager, lower Width on the bands that vanish in mono."),
        "widen_image": (3, "In Ozone Imager, go multiband and raise Width on the upper bands only; keep the lowest band at 0 or below."),
    }},
    "ozone_eq": {"name": "Ozone EQ", "in": ["izotope_ozone"], "can": {
        "eq_cut_band": (3, "In Ozone's Equalizer, add a {shape} over {band} and cut about {amount} dB; use Gain Match to A/B it at matched volume."),
        "eq_boost_band": (3, "In Ozone's Equalizer, add a {shape} over {band} and boost about {amount} dB; use Gain Match to A/B it at matched volume."),
    }},
    "insight": {"name": "Insight 2", "in": ["izotope_insight"], "can": {
        "loudness_meter": (3, "Put Insight 2 on the master and read Integrated loudness and True Peak over the whole song."),
        "correlation_meter": (3, "Watch Insight 2's Sound Field correlation while you loop {start}–{end}."),
    }},
}


def owned_tools(setup):
    """Tools available to a user: their DAW's stock tools plus their packages."""
    have = {setup.get("daw", "other"), *expand_packages(setup.get("packages"))}
    return {tid: t for tid, t in TOOLS.items() if have & set(t["in"])}


def expand_packages(ids):
    """Package ids as saved or typed, with legacy ones replaced by what they stood for; unknown ones dropped."""
    out = []
    for p in ids or []:
        for q in LEGACY_PACKAGES.get(p, [p]):
            if q in PACKAGES and q not in out:
                out.append(q)
    return out


def options():
    """What the setup screen offers."""
    return {
        "daws": [{"id": k, "name": v} for k, v in DAWS.items()],
        "packages": [{"id": k, **v} for k, v in PACKAGES.items()],
        "waves_tiers": [{"id": k, **v} for k, v in WAVES_TIERS.items()],
        "legacy_packages": LEGACY_PACKAGES,
    }
