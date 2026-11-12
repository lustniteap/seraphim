"""Build mixcheck/library/plugins.json from docs/plugin-catalog-source.md (the compiled vendor catalog).

    python3 tools/build_plugin_list.py

The result is the searchable plugin list the setup screen offers, with the bundles a vendor sells. Only effects and
utilities are kept: instruments, synths, sample libraries, bundles and subscriptions are left out because they are not
part of a mixing chain. A plugin Seraphim already has steps for (catalog.PACKAGES) is mapped to its existing id.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SRC = ROOT / "docs" / "plugin-catalog-source.md"
OUT = ROOT / "mixcheck" / "library" / "plugins.json"

# Catalog names that are already pickable with fix steps: map them to the existing package id instead.
EXISTING = {"L2 Ultramaximizer": "waves_l2", "F6 Floating-Band Dynamic EQ": "waves_f6",
            "Renaissance Equalizer": "waves_ren_eq", "Renaissance Compressor": "waves_ren_comp",
            "S1 Stereo Imager": "waves_s1_imager", "PAZ Analyzer": "waves_paz", "WLM Plus Loudness Meter": "waves_wlm",
            "Insight 2": "izotope_insight"}
SKIP_WORDS = re.compile(
    r"bundle|mix tape|subscription|synth|piano|organ|minimoog|keyboard|keys|strings|brass|woodwinds|sampler|luna|"
    r"kontakt|massive|drums|sample pack|oscillator|pad controller|arpeggiator|chordaxe|captain chords|groove|"
    r"cell$|^software:|studioverse|cosmos|cr8|element 2|flow motion|wave traveller|autogun|beepmap|boobass|"
    r"directwave|drumpad|flex$|gms$|minisynth|plucked|simsynth|speech|fl keys|video|razer|vfx|controller|"
    r"notebook|patcher|control surface|spitfire|clavinet|bass fingers|bass slapper|infected mushroom|codex|"
    r"harmor|kepler|morphine|ogun|poizone|sakura|sawer|toxic|transistor|drumaxx|hybrid keys|haze|lo-fi & chill|"
    r"soul sessions|boom$|db-33|mini grand|structure|vacuum|xpand|ableton|note stack|pitch control|velocity control|"
    r"human lite|eon-arp|seqund|riffer|tatat|vocoder|vocodex|opal|anthem|electra|waterfall|cyclosonic|oto biscuit|"
    r"sound machine|sphere mic|mic collection|microphones|wood works|studio d chorus$|click ii|stream$|playlist rider|"
    r"key detector|waves harmony|b360|c360|l360|lfe360|m360|mv360|r360|s360|ir360|dorrough surround|spherix|"
    r"immersive|walkmix|mpeg-h|dolby|audio vivid|stem separator|soundflow|splice|acoustica|bounce factory|melodyne|"
    r"forte|rx 11|spectralayers|wavelab|repitch|dynassist|sonic drop|inner circle|sample finder|sound city|"
    r"capitol studios$|ocean way studios deluxe|hitsville reverb|universal|spark|native|vocal tune|topline|"
    r"free$|catalyst|tuner$|^uad (ultimate|complete|select|custom)|paradise guitar", re.I)
CATEGORY = [
    ("de-esser", r"de-?ess|sibilance|suprsser|esser"), ("limiter", r"limiter|maximi|l1 |l2 |l3|l4|clipper|pro-l|maxim$|inflator|bx_limiter|c-max"),
    ("reverb", r"reverb|verb|plate|chamber|room|spring|space designer|chromaverb|convolution|ir-?l|ir1|nx|atlas|quantec|spaces"),
    ("delay", r"delay|echo|tapped|time cube|supertap|timeless|bbd"), ("imager", r"imager|width|stereo (maker|shaper|enhancer)|spreader|ps22|center|doubler|panner|k-stereo|spread|stereomaker"),
    ("eq", r"\beq\b|equali[sz]er|pultec|puigtec|meq|eqp|q10|pro-q|curves|tilt|geq|graphic|v-eq|e-?channel eq|massive passive|tonebox"),
    ("compressor", r"compress|comp\b|leveler|la-?2a|la-?3a|1176|cla-?76|distressor|dynamics|bf-?76|bf-?2a|bf-?3a|opto|fairchild|expander|gate|transient|smack|pro-c|pro-mb|multiband|vari mu|variable mu|tla-100|zener|vsc-2|ssl.*bus|bus"),
    ("channel strip", r"channel|strip|console|preamp|neve|api |ssl|helios|trident|harrison|vision|v76|1073|1084|1081|88rs|dfc|rs124|redd|tg12345"),
    ("saturation", r"saturat|tape|distort|fuzz|overdrive|drive|vulture|exciter|enhancer|heat|lo-?fi|fatso|vitamin|vinyl|aural|oxide|j37|fi\b|crackle|retro"),
    ("modulation", r"chorus|flang|phas|mod|vibe|rotary|wah|ring|ensemble|doppler|brauer|filter|vintage filter|tremolo|kill eq|motion"),
    ("pitch", r"tune|pitch|shifter|soundshifter|ultrapitch|ovox|x-form|time shift|bender"),
    ("amp", r"amp|gtr|sansamp|eleven|bass amp|svt|diezel|fender|engl|friedman|suhr|ampeg|chandler.*gav|marshall|energy|voltage"),
    ("meter", r"meter|analyzer|spl meter|insight|tonal balance|spectroman|db meter|vu|mastermeter|tract|calibration|metric|clock"),
]


def category(name):
    for cat, pat in CATEGORY:
        if re.search(pat, name, re.I):
            return cat
    return "utility"


def slug(vendor, name):
    return f"{vendor}_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}"


def parse():
    vendor = tier = None
    for line in SRC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            vendor, tier = re.sub(r"\s*\(.*", "", line[3:]).strip(), None
        elif line.startswith("### "):
            tier = line[4:].strip()
        elif line.startswith("- ") and vendor:
            yield vendor, tier, line[2:].strip()


VENDOR_PREFIX = {"Waves": "waves", "UAD": "uad", "FabFilter": "ff", "iZotope": "iz", "Plugin Alliance": "pa",
                 "Pro Tools": "avid", "FL Studio": "fl", "Logic Pro": "logic", "GarageBand": "gb"}
GROUPS = {"Waves": "Waves", "UAD": "Universal Audio (UAD)", "FabFilter": "FabFilter", "iZotope": "iZotope",
          "Plugin Alliance": "Plugin Alliance", "Pro Tools": "Avid (Pro Tools)", "FL Studio": "Image-Line (FL Studio)",
          "Logic Pro": "Apple (Logic Pro)", "GarageBand": "Apple (GarageBand)"}
# Not mixing plugins: instruments or hardware-bound lists that the Pro Tools Artist list mixes in without headings.
PT_SKIP_FROM, PT_SKIP_TO = "510k SEQUND Lite", "Pro Tools Factory Essentials (Kontakt)"


def main():
    plugins, bundles, seen, skipping_pt = {}, {}, set(), False
    for vendor_raw, tier, name in parse():
        key = next((k for k in VENDOR_PREFIX if vendor_raw.startswith(k)), None)
        if key is None or (key == "GarageBand"):
            continue
        if key == "Pro Tools":
            if name == PT_SKIP_FROM:
                skipping_pt = True
            if skipping_pt:
                skipping_pt = name != PT_SKIP_TO
                continue
        if key == "Logic Pro" and (tier or "").startswith("Named instruments"):
            continue
        if key == "FL Studio" and (tier or "").startswith("Fruity") and not re.search(
                r"compress|limiter|eq|reverb|delay|chorus|flang|phas|dist|filter|clip|stereo|multiband|maximus|"
                r"squeeze|vocoder|soundgoodizer|balance|convolver|emphasi|transient|waveshaper|wave candy|spectroman|db meter|"
                r"gross|low lifter|pitcher|reeverb|luxeverb", name, re.I):
            continue
        if SKIP_WORDS.search(name) and name not in EXISTING:
            continue
        pid = EXISTING.get(name) or slug(VENDOR_PREFIX[key], name)
        if pid in seen:
            continue
        seen.add(pid)
        if name not in EXISTING:
            plugins[pid] = {"name": re.sub(r"\s*\((AudioSuite only|equalizer|compressor|limiter|reverb|delay|filter)\)", "", name),
                            "group": GROUPS[key], "category": category(name)}
        label = tier or ""
        if key == "Waves":
            bundles.setdefault("waves_essential" if label.startswith("Waves Essential") else "waves_ultimate_extra", []).append(pid)
        elif key == "Pro Tools" and "Ultimate" not in label:
            bundles.setdefault("pro_tools_artist" if "Artist" in label else "pro_tools_studio_extra", []).append(pid)
        elif key == "FL Studio":
            ed = ("fruity" if label.startswith("Fruity") else "producer" if label.startswith("Producer") else
                  "signature" if label.startswith("Signature") else "all")
            bundles.setdefault(f"fl_{ed}", []).append(pid)
    ess = bundles["waves_essential"]
    out_bundles = [
        {"id": "waves_essential", "name": "Waves Essential", "plugins": ess},
        {"id": "waves_ultimate", "name": "Waves Ultimate", "plugins": ess + bundles["waves_ultimate_extra"]},
        {"id": "pro_tools_artist", "name": "Pro Tools Artist", "plugins": bundles["pro_tools_artist"]},
        {"id": "pro_tools_studio", "name": "Pro Tools Studio", "plugins": bundles["pro_tools_artist"] + bundles["pro_tools_studio_extra"]},
        {"id": "fl_producer", "name": "FL Studio Producer Edition", "plugins": bundles["fl_fruity"] + bundles["fl_producer"]},
        {"id": "fl_all", "name": "FL Studio All Plugins Edition",
         "plugins": bundles["fl_fruity"] + bundles["fl_producer"] + bundles["fl_signature"] + bundles["fl_all"]},
    ]
    OUT.write_text(json.dumps({"version": 1, "source": "docs/plugin-catalog-source.md (vendor pages and retail listings, "
                               "November 2026; verify on each vendor's site)", "plugins": plugins, "bundles": out_bundles},
                              indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    from collections import Counter
    print(len(plugins), "plugins;", Counter(p["group"] for p in plugins.values()))
    print({b["id"]: len(b["plugins"]) for b in out_bundles})


if __name__ == "__main__":
    main()
