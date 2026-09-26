"""The five tone bands shared by reference tracks and style targets.

Levels in these bands are measured relative to the song's own loudness (see
reference.py), so they compare at matched volume.
"""

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
