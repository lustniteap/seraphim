"""Every frequency band Seraphim uses, defined once (docs/09-analysis-model.md).

Two resolutions for the band-by-band analysis:

  ENGINEER_BANDS  ten bands a mix engineer talks in (what users read)
  FINE_BANDS      31 one-third-octave bands, 20 Hz to 20 kHz (what detectors use)

and two older groupings that saved data and the page depend on:

  TONE_BANDS      the five tone bands shared by reference tracks and style targets
  ENERGY_BANDS    the five bands of the report's "spectrum" energy shares

The tone bands keep the edges they have always had (100 Hz, 300 Hz, 2 kHz, 6 kHz), because saved
calibrations and reference sets were measured with them. Those two lower edges are not engineer-band
edges (120 Hz, 250 Hz), so TONE_GROUPS maps each engineer band to the tone band it mostly sits in:
close enough to say which tone band a finding belongs to, not a way to add levels up.
ENERGY_BANDS are exact unions of engineer bands (ENERGY_GROUPS).

Tone levels are measured relative to the song's own loudness (see reference.py), so they compare
at matched volume.
"""

# id, low Hz, high Hz, short name
ENGINEER_BANDS = [
    ("sub", 20, 60, "Sub"),
    ("bass", 60, 120, "Bass"),
    ("low_mids", 120, 250, "Low mids"),
    ("mud", 250, 500, "Mud"),
    ("box", 500, 1000, "Box"),
    ("mids", 1000, 2000, "Mids"),
    ("presence", 2000, 4000, "Presence"),
    ("bite", 4000, 6000, "Bite"),
    ("sibilance", 6000, 10000, "Sibilance"),
    ("air", 10000, 20000, "Air"),
]
ENGINEER_IDS = [b[0] for b in ENGINEER_BANDS]

# One-third-octave bands (IEC 61260, base ten): centers at 1000 * 10^(n/10) Hz, edges a sixth of an
# octave either side. Named by the usual nominal center.
FINE_NOMINAL_HZ = [20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800,
                   1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000]
# (nominal center Hz, low Hz, high Hz)
FINE_BANDS = [(nominal, 1000 * 10 ** ((n - 0.5) / 10), 1000 * 10 ** ((n + 0.5) / 10))
              for n, nominal in zip(range(-17, 14), FINE_NOMINAL_HZ)]

# id, low Hz, high Hz, short name, how fixes name it, how findings phrase it,
# words for (more, less), EQ shape to fix it with.
TONE_BANDS = [
    ("lows", 20, 100, "Lows", "the lows (below 100 Hz)", "below 100 Hz", ("heavier", "lighter"), "low shelf"),
    ("low_mids", 100, 300, "Low mids", "the low mids (100–300 Hz)", "at 100–300 Hz", ("heavier", "lighter"), "wide bell"),
    ("mids", 300, 2000, "Mids", "the mids (300 Hz–2 kHz)", "at 300 Hz–2 kHz", ("fuller", "thinner"), "wide bell"),
    ("presence", 2000, 6000, "Presence", "the presence range (2–6 kHz)", "at 2–6 kHz", ("more forward", "further back"), "wide bell"),
    ("highs", 6000, 20000, "Highs", "the highs (above 6 kHz)", "above 6 kHz", ("brighter", "duller"), "high shelf"),
]
BAND_IDS = [b[0] for b in TONE_BANDS]
BANDS = {b[0]: b for b in TONE_BANDS}

# tone band -> the engineer bands that mostly sit in it (approximate below 300 Hz, exact above).
TONE_GROUPS = {
    "lows": ["sub", "bass"],
    "low_mids": ["low_mids"],
    "mids": ["mud", "box", "mids"],
    "presence": ["presence", "bite"],
    "highs": ["sibilance", "air"],
}

# The report's "spectrum.band_energy_pct" bands: id -> the engineer bands it is exactly made of.
ENERGY_GROUPS = {
    "sub": ["sub"],
    "low": ["bass", "low_mids"],
    "low_mid": ["mud", "box", "mids"],
    "high_mid": ["presence", "bite"],
    "high": ["sibilance", "air"],
}
_EDGES = {b[0]: (b[1], b[2]) for b in ENGINEER_BANDS}
# (id, low Hz, high Hz)
ENERGY_BANDS = [(eid, _EDGES[members[0]][0], _EDGES[members[-1]][1]) for eid, members in ENERGY_GROUPS.items()]
