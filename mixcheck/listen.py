"""The listener: an audio-understanding model describes what it hears, as context for the rest of the pipeline.

It is the `listen` block of the case file (docs/contracts.md). The audio model supplies the *where* and the *what*:
a genre and sub-genre guess with a confidence, the instruments, the sections with their times, the kind of vocal, and
a few qualities no measurement covers (labelled "heard, unverified"). It supplies **no measured quantity**: no
loudness, no frequencies, no tempo, no key, no "typical" numbers. Those belong to the engine. check() enforces that,
so a reply that quotes numbers is rejected and retried once, then dropped ("not listened") without stopping the run.

This is the test version: Gemini Flash-Lite over HTTPS with the person's own key (GEMINI_API_KEY), run on their
computer. The audio leaves the machine only when they run it, and only to the provider they chose. The audio is
reduced to 16 kHz mono before sending (the provider reduces it further itself), and nothing is stored.

    listen_to(path)                 -> {"ok": True, "listen": {...}, "usage": {...}} or {"ok": False, "reason": ...}
    check(reply, duration_s)        -> list of problems (empty when the reply is acceptable)
    estimate_cost(duration_s)       -> dollars, from the published audio price (confirm it on the provider's page)
"""
import base64
import io
import json
import os
import random
import re
import time
import urllib.error
import urllib.request

import numpy as np

from .audio_io import load_audio
from .style import SUBGENRES, TARGETS, style_ids

LISTEN_VERSION = 1
PROVIDERS = ("gemini", "fake")
DEFAULT_MODEL = "gemini-3.1-flash-lite"   # confirm the current id on the provider's models page; --model overrides
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SEND_RATE = 16000                         # Hz, mono, 16-bit: the provider downsamples to this class anyway
MAX_SECONDS = 480                         # keeps the request under the 20 MB inline limit (32 KB/s * 480 s = 15 MB)
TOKENS_PER_SECOND = 32                    # audio tokens per second, third-party figure: confirm on the provider's page
PRICE_PER_M_AUDIO = 0.90                  # dollars per million audio input tokens, the higher published figure
SECTION_LABELS = ("intro", "verse", "hook", "pre_hook", "bridge", "drop", "beat_only", "breakdown", "outro", "other")
VOCAL_KINDS = ("rapped", "sung", "rapped_and_sung", "spoken", "none")
MAX_INSTRUMENTS, MAX_QUALITIES, MAX_SECTIONS = 12, 6, 40
END_SLACK_S = 20.0                        # a section end this far past the audio is clamped to it; further is rejected

# Numbers that belong to the engine. A free-text field that carries one is a violation.
_MEASURED = re.compile(r"\d+(\.\d+)?\s*(db|dbfs|dbtp|lufs|lu|hz|khz|bpm|%|percent|ms|semitone)\b|\bbpm\b|\b[a-g][#b]?\s*(major|minor)\b",
                       re.I)


# What separates the hip-hop sub-genres, in plain words and no numbers, for the prompt's optional "describe" mode.
# Drafted from general knowledge: Tyler's to correct.
DESCRIPTIONS = {
    "hiphop_rap.trap": "hard 808 bass, rolling or stuttering hi-hats, sparse dark synths; the broad mainstream trap sound",
    "hiphop_rap.drill": "sliding 808 bass, bouncy triplet-feel hi-hats and snares, dark menacing mood, cold deadpan delivery "
                        "(Chicago, UK and Brooklyn variants)",
    "hiphop_rap.boom_bap": "sampled drum breaks and soul or jazz loops, dusty swung drums, lyric-focused, 1990s-rooted",
    "hiphop_rap.melodic": "sung or pitch-corrected melodies over trap beats, emotional or dreamy mood, melodic hooks",
    "hiphop_rap.rage": "distorted aggressive synth leads and heavy bass, chaotic high-energy delivery with shouted ad-libs, "
                       "often video-game-like synth sounds",
}


def vocabulary():
    """The style ids the model may choose from, each with its name."""
    names = {}
    for sid in style_ids():
        if sid in SUBGENRES:
            sub = SUBGENRES[sid]
            names[sid] = f"{TARGETS[sub['parent']]['name']} / {sub['name']}"
        else:
            names[sid] = TARGETS[sid]["name"]
    return names


def prompt(duration_s=None, shuffle_seed=None, describe=False):
    length = f"The audio is {duration_s:.0f} seconds long. " if duration_s else ""
    names = list(vocabulary().items())
    if shuffle_seed is not None:                   # an order that favours no style: the same for one song, different between songs
        random.Random(shuffle_seed).shuffle(names)
    styles = "\n".join(f"  {sid}: {name}" + (f" ({DESCRIPTIONS[sid]})" if describe and sid in DESCRIPTIONS else "")
                       for sid, name in names)
    return f"""You are listening to a finished or nearly finished song to describe it for a mixing engineer's assistant.
Describe only what you can hear. {length}Reply with one JSON object and nothing else.

Rules:
- Do not state any measured quantity: no loudness, no decibels, no frequencies, no tempo or BPM, no musical key, no
  percentages. Another tool measures those. Describe in plain words only.
- "style": choose the closest id from the list below (a sub-genre id if one fits, otherwise its parent), or null if you
  cannot tell. "confidence" is between 0 and 1 and should be honest: use low values when unsure.
  "alternatives" lists up to 2 other ids you considered.
- "instruments": up to {MAX_INSTRUMENTS} short lowercase names of what you hear (for example "808 bass", "hi-hats", "piano").
- "vocal": "kind" is one of {', '.join(VOCAL_KINDS)}; "present" is true or false.
- "sections": the song's sections in order, each with a "label" from {', '.join(SECTION_LABELS)} and "start_s" and
  "end_s" in seconds from the start of the audio you were given. Sections must not overlap, and the last one must end where the
  audio ends.
- "qualities": up to {MAX_QUALITIES} short plain phrases about things you hear that a meter would not tell us (for example
  "vocal sounds heavily pitch-corrected", "bass sounds distorted"). These are impressions, not measurements.

Style ids:
{styles}

JSON shape:
{{"style": {{"id": "...", "confidence": 0.0, "alternatives": ["..."]}},
  "instruments": ["..."], "vocal": {{"present": true, "kind": "rapped"}},
  "sections": [{{"label": "intro", "start_s": 0.0, "end_s": 12.5}}], "qualities": ["..."]}}"""


# ---------------------------------------------------------------- checking the reply

def _text_problems(where, value):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        return [f"{where}: expected short text"]
    if _MEASURED.search(value):
        return [f"{where}: states a measured quantity ({value!r})"]
    return []


def check(reply, duration_s, strict_sections=True):
    """Problems with a reply (a dict). Empty when it can be used. Never raises. With strict_sections False the section
    list is not judged here: clean() drops the sections that are unusable and keeps the rest."""
    if not isinstance(reply, dict):
        return ["reply is not a JSON object"]
    out, ids = [], set(vocabulary())
    st = reply.get("style")
    if not isinstance(st, dict):
        out.append("style: missing")
    else:
        if st.get("id") is not None and st["id"] not in ids:
            out.append(f"style.id: {st['id']!r} is not in the list")
        c = st.get("confidence")
        if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1:
            out.append("style.confidence: must be a number from 0 to 1")
        alts = st.get("alternatives", [])
        if not isinstance(alts, list) or len(alts) > 2 or any(a not in ids for a in alts):
            out.append("style.alternatives: up to 2 ids from the list")
    for key, limit in (("instruments", MAX_INSTRUMENTS), ("qualities", MAX_QUALITIES)):
        items = reply.get(key)
        if not isinstance(items, list) or len(items) > limit:
            out.append(f"{key}: expected a list of at most {limit}")
        else:
            for i, t in enumerate(items):
                out += _text_problems(f"{key}[{i}]", t)
    vo = reply.get("vocal")
    if not isinstance(vo, dict) or not isinstance(vo.get("present"), bool) or vo.get("kind") not in VOCAL_KINDS:
        out.append(f"vocal: needs present (true/false) and kind from {', '.join(VOCAL_KINDS)}")
    secs = reply.get("sections")
    if not isinstance(secs, list) or len(secs) > MAX_SECTIONS:
        out.append("sections: expected a list")
    elif strict_sections:
        prev_end = 0.0
        for i, s in enumerate(secs):
            ok = (isinstance(s, dict) and s.get("label") in SECTION_LABELS
                  and all(isinstance(s.get(k), (int, float)) and not isinstance(s.get(k), bool) for k in ("start_s", "end_s")))
            if not ok:
                out.append(f"sections[{i}]: needs a label from the list and numeric start_s and end_s")
                continue
            if s["start_s"] < 0 or s["start_s"] >= duration_s or s["end_s"] <= s["start_s"] or s["end_s"] > duration_s + END_SLACK_S:
                out.append(f"sections[{i}]: times outside the audio ({s['start_s']} to {s['end_s']})")
            elif s["start_s"] < prev_end - 1.0:
                out.append(f"sections[{i}]: overlaps the previous section")
            prev_end = max(prev_end, s["end_s"])
    return out


def clean(reply, duration_s=None):
    """The reply reduced to the fields in the contract, with the confidence rounded, sections sorted and any section end
    that runs a little past the audio clamped to it."""
    end = (lambda t: min(t, duration_s)) if duration_s else (lambda t: t)
    st = reply["style"]
    sections, dropped, prev_end = [], 0, 0.0
    for s in sorted((s for s in reply["sections"] if isinstance(s, dict)
                     and isinstance(s.get("start_s"), (int, float)) and not isinstance(s.get("start_s"), bool)),
                    key=lambda s: s["start_s"]):
        ok = (s.get("label") in SECTION_LABELS and isinstance(s.get("end_s"), (int, float)) and not isinstance(s.get("end_s"), bool)
              and s["start_s"] >= 0 and s["end_s"] > s["start_s"] and s["start_s"] >= prev_end - 1.0
              and (duration_s is None or (s["start_s"] < duration_s and s["end_s"] <= duration_s + END_SLACK_S)))
        if not ok:
            dropped += 1
            continue
        sections.append({"label": s["label"], "start_s": round(float(s["start_s"]), 1),
                         "end_s": round(float(end(s["end_s"])), 1)})
        prev_end = max(prev_end, s["end_s"])
    dropped += max(0, len(reply["sections"]) - len(sections) - dropped)   # entries that were not objects at all
    return {"version": LISTEN_VERSION,
            "style": {"id": st.get("id"), "confidence": round(float(st["confidence"]), 2),
                      "alternatives": list(st.get("alternatives", []))},
            "instruments": [t.strip().lower() for t in reply["instruments"]],
            "vocal": {"present": reply["vocal"]["present"], "kind": reply["vocal"]["kind"]},
            "sections": sections,
            "sections_dropped": dropped,
            "qualities": [{"note": t.strip(), "trust": "heard, unverified"} for t in reply["qualities"]]}


# ---------------------------------------------------------------- audio and cost

def prepare_audio(path):
    """(wav bytes at 16 kHz mono 16-bit, seconds sent, seconds in the file). Long files are cut to MAX_SECONDS."""
    import soundfile as sf
    from scipy.signal import resample_poly
    x, fs = load_audio(path)
    total = x.shape[0] / fs
    mono = x.mean(axis=1)
    g = np.gcd(int(fs), SEND_RATE)
    mono = resample_poly(mono, SEND_RATE // g, int(fs) // g)
    mono = np.clip(mono[:SEND_RATE * MAX_SECONDS], -1.0, 1.0)
    buf = io.BytesIO()
    sf.write(buf, mono, SEND_RATE, format="WAV", subtype="PCM_16")
    return buf.getvalue(), len(mono) / SEND_RATE, total


def estimate_cost(duration_s):
    """Dollars for one song at the published audio price. An estimate: confirm the price on the provider's page."""
    return min(duration_s, MAX_SECONDS) * TOKENS_PER_SECOND * PRICE_PER_M_AUDIO / 1e6


# ---------------------------------------------------------------- providers

class RateLimited(RuntimeError):
    """The provider asked us to slow down. retry_s is how long it said to wait (None if it did not say);
    daily is True when the limit is for the whole day, where waiting a minute will not help."""
    def __init__(self, message, retry_s=None, daily=False):
        super().__init__(message)
        self.retry_s, self.daily = retry_s, daily


def _ssl_context():
    """Certificates to trust. Python installed from python.org on a Mac has none until a setup file is run, so use the
    certifi bundle when it is installed (it comes with the web extras)."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _post_json(url, body, key, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        detail = raw[:300]
        if e.code == 429:
            m = re.search(r'retry(?:Delay"?:\s*"|\s+in\s+)([\d.]+)s', raw)
            raise RateLimited(f"The provider says the quota or rate limit was reached ({detail[:200]})",
                              float(m.group(1)) if m else None, "PerDay" in raw or "per day" in raw.lower()) from None
        raise RuntimeError(f"The provider answered {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        why = str(e.reason)
        hint = (" On a Mac with Python from python.org, run 'Install Certificates.command' in /Applications/Python 3.x/, "
                "or run: pip install certifi") if "CERTIFICATE_VERIFY_FAILED" in why else ""
        raise RuntimeError(f"Could not reach the provider: {why}.{hint}") from None


def _gemini(wav, model, key, text):
    body = {"contents": [{"parts": [{"text": text},
                                    {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(wav).decode("ascii")}}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    r = _post_json(ENDPOINT.format(model=model), body, key)
    try:
        text = r["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"No answer in the reply ({str(r)[:200]})") from None
    use = r.get("usageMetadata") or {}
    return text, {"input_tokens": use.get("promptTokenCount"), "output_tokens": use.get("candidatesTokenCount")}


def _fake(wav, model, key, text):
    """A stand-in that answers well-formed replies with no key and no cost, for testing the harness."""
    return json.dumps({"style": {"id": "hiphop_rap", "confidence": 0.5, "alternatives": []},
                       "instruments": ["808 bass", "hi-hats"], "vocal": {"present": True, "kind": "rapped"},
                       "sections": [{"label": "intro", "start_s": 0.0, "end_s": 8.0}], "qualities": []}), {}


def _with_backoff(call, wav, model, key, ask, waits=3):
    """call(...), waiting and trying again when the provider says to slow down (up to `waits` times)."""
    for n in range(waits + 1):
        try:
            return call(wav, model, key, ask)
        except RateLimited as e:
            if e.daily or n == waits:
                raise RuntimeError(str(e) + (" It looks like a daily limit: wait until tomorrow or turn on billing for the key."
                                              if e.daily else " Run fewer songs at a time, or turn on billing for the key.")) from None
            time.sleep(min(65.0, (e.retry_s or 20.0) + 1.0))


def listen_to(path, provider="gemini", model=None, key=None, shuffle=False, describe=False):
    """Listen to one song. Retries once if the reply does not pass check(). Never raises for provider trouble."""
    model = model or DEFAULT_MODEL
    key = key or os.environ.get("GEMINI_API_KEY", "")
    if provider not in PROVIDERS:
        return {"ok": False, "reason": f"unknown provider {provider!r}"}
    if provider == "gemini" and not key:
        return {"ok": False, "reason": "No GEMINI_API_KEY is set. Set it in the Terminal window you run this from."}
    t0 = time.time()
    try:
        wav, sent_s, total_s = prepare_audio(path)
    except Exception as e:  # noqa: BLE001 - an unreadable file is a result, not a crash
        return {"ok": False, "reason": f"could not read the audio: {e}"}
    call = _gemini if provider == "gemini" else _fake
    ask = prompt(sent_s, shuffle_seed=os.path.getsize(path) if shuffle else None, describe=describe)
    problems, tokens_in, tokens_out = [], 0, 0
    for attempt in (1, 2):
        try:
            text, usage = _with_backoff(call, wav, model, key, ask)
        except RuntimeError as e:
            return {"ok": False, "reason": str(e), "seconds": round(time.time() - t0, 1)}
        tokens_in += usage.get("input_tokens") or 0
        tokens_out += usage.get("output_tokens") or 0
        try:
            reply = json.loads(text)
        except ValueError:
            problems = ["the reply was not valid JSON"]
            continue
        problems = check(reply, sent_s, strict_sections=False)
        if not problems:
            return {"ok": True, "listen": clean(reply, sent_s), "attempts": attempt, "model": model,
                    "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out, "sent_s": round(sent_s, 1),
                              "file_s": round(total_s, 1)},
                    "seconds": round(time.time() - t0, 1)}
    return {"ok": False, "reason": "the reply did not pass the checks twice: " + "; ".join(problems[:4]),
            "problems": problems, "attempts": 2, "seconds": round(time.time() - t0, 1)}
