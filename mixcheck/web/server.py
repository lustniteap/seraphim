"""Web interface: a small API around the analysis engine plus a static page.

Run:  mixcheck-web            (then open http://127.0.0.1:8000)
  or: uvicorn mixcheck.web.server:app --reload
"""
import json
import os
import queue
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .. import feedback
from .. import notes as ai_notes
from .. import refsets
from ..analyze import THRESHOLDS, analyze_file
from ..catalog import options as setup_options
from ..scan import LAUNCHERS, PLATFORM, PLATFORM_NAMES, scan_this_computer
from ..reference import MAX_REFERENCES, apply_reference, profile_file, sanitize_profile
from ..remediation import STAGES, attach_fixes, describe_setup, normalize_setup
from ..score import score_flags
from ..style import apply_style, style_match
from ..style import options as style_options
from ..util import utf8_console

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_SUFFIXES = {".wav", ".wave", ".aif", ".aiff", ".flac", ".mp3"}
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GB: a long 96 kHz/32-bit stereo bounce fits
CHUNK = 1024 * 1024

app = FastAPI(title="Seraphim", version=__version__)


@app.middleware("http")
async def no_stale_pages(request, call_next):
    # Make the browser revalidate, so an updated page shows up without a hard refresh.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/info")
def info():
    """What the page needs to set itself up."""
    return {
        "version": __version__,
        "setup_options": setup_options(),
        "platform": {"id": PLATFORM, "noun": PLATFORM_NAMES[PLATFORM],
                     "launcher": LAUNCHERS.get(PLATFORM, "the start script")},
        "style_options": style_options(),
        "accepted_formats": sorted(ALLOWED_SUFFIXES),
        "thresholds": THRESHOLDS,
        "max_references": MAX_REFERENCES,
        "ai_notes": dict(zip(("available", "reason"), ai_notes.available())),
        "notes_feedback": {"reasons": feedback.options(), **feedback.stats()},
    }


async def save_upload(file):
    """Stream an upload to a temporary file (large bounces never sit in memory). Returns its path."""
    name = file.filename or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, f"{name} isn't a supported format. Use WAV, AIFF, FLAC or MP3.")
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        size = 0
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "That file is larger than 1 GB.")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, f"{name} is empty.")
    except BaseException:
        remove(tmp_path)
        raise
    return tmp_path


def remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def audio_error(exc, name):
    """What to tell the user when a file couldn't be analyzed."""
    # Our own errors are written for users. The audio library's are not (they include the temp file's path).
    if isinstance(exc, (ValueError, RuntimeError)) and type(exc).__module__.split(".")[0] != "soundfile":
        return str(exc)
    return f"{name} couldn't be read as audio. Try re-bouncing it as a WAV."


async def with_upload(file, work):
    """Save an upload, run work(path) in a thread, and always delete the file."""
    tmp_path = await save_upload(file)
    try:
        return await run_in_threadpool(work, tmp_path)
    except Exception as exc:
        raise HTTPException(422, audio_error(exc, file.filename or "upload"))
    finally:
        remove(tmp_path)


def with_real_name(report, name):
    report["file"]["name"] = name  # show the real name, not the temp file's
    if report.get("profile"):
        report["profile"]["name"] = name
    return report


@app.get("/api/scan")
def scan():
    """What's installed on this computer, to pre-fill the setup screen. Reads bundle metadata only."""
    return scan_this_computer()


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), setup: str = Form("{}"), stage: str = Form("auto"),
                  target: str = Form(""), references: str = Form("[]"), progress: str = Form("")):
    """The report as JSON. With progress=1, newline-delimited JSON instead: {"stage": ...} as each
    part of the analysis finishes (see analyze.PROGRESS_STAGES), then {"report": ...} or {"error": ...}."""
    name = file.filename or "upload"
    user_setup = parse_setup(setup)
    refs = parse_references(parse_json(references, "references", []))
    run = lambda path, done=None: analyze_file(path, user_setup, stage, target or None, refs, progress=done)
    if progress != "1":
        return with_real_name(await with_upload(file, run), name)

    tmp_path = await save_upload(file)
    events = queue.Queue()

    def work():
        try:
            events.put({"report": with_real_name(run(tmp_path, lambda st: events.put({"stage": st})), name)})
        except Exception as exc:
            events.put({"error": audio_error(exc, name)})
        finally:
            remove(tmp_path)
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def lines():
        while (event := events.get()) is not None:
            yield json.dumps(event) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post("/api/reference")
async def reference(file: UploadFile = File(...)):
    """Measure a reference song and return its profile. The audio isn't kept."""
    name = file.filename or "reference"
    return await with_upload(file, lambda p: profile_file(p, name))


@app.get("/api/reference-sets")
def reference_sets():
    return {"sets": refsets.list_sets()}


@app.post("/api/notes")
async def notes(report: dict = Body(..., embed=True)):
    """Engineer's notes for a report the page already has. Sends numbers to Claude, never audio."""
    for key in ("flags", "loudness", "peaks", "stage", "setup", "score", "file", "dynamics"):
        if key not in report:
            raise HTTPException(422, f"The report is missing {key}; check the bounce again.")
    try:
        result = await run_in_threadpool(ai_notes.write_notes, report)
    except ai_notes.NotesUnavailable as exc:
        raise HTTPException(503, str(exc))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "That report couldn't be read; check the bounce again.")
    result["notes_id"] = feedback.remember(result)  # so these notes can be rated
    inp = result.pop("input")
    # Let the page show steps and findings by id without re-deriving MixCheck's numbering.
    result["steps"] = {s["id"]: s["text"] for f in inp["findings"] for s in f["steps"] + f["other_options"]}
    result["findings"] = {f["id"]: f["kind"] for f in inp["findings"]}
    return result


@app.post("/api/notes/feedback")
def rate_notes(notes_id: str = Body(...), rating: Optional[str] = Body(None), reasons: list = Body([])):
    """Thumbs up or down on a set of notes (rating null clears it). Kept on this computer only."""
    try:
        return feedback.rate(notes_id, rating, reasons)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except feedback.Gone:
        raise HTTPException(404, "Those notes are no longer in memory (Seraphim was restarted). Rewrite them to rate them.")


@app.get("/api/notes/feedback/export")
def export_feedback(name: str = ""):
    """Download the ratings as one file: measurements, notes and ratings, with no audio and no file name."""
    filename, text, count = feedback.export(name)
    if not count:
        raise HTTPException(404, "Nothing to export yet. Rate some notes first.")
    return Response(text, media_type="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.put("/api/reference-sets")
def save_reference_set(name: str = Body(...), references: list = Body(...)):
    try:
        return refsets.save_set(name, references)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc))
    except OSError:
        raise HTTPException(500, "Couldn't save the reference set on this computer.")


@app.delete("/api/reference-sets/{name}")
def delete_reference_set(name: str):
    try:
        refsets.delete_set(name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except KeyError as exc:
        raise HTTPException(404, exc.args[0])
    return {"deleted": name}


@app.post("/api/fixes")
def fixes(flags: list = Body(...), setup: dict = Body({}), stage: str = Body("mix"),
          target: str = Body(""), measures: dict = Body({}), profile: Optional[dict] = Body(None),
          references: list = Body([])):
    """Rebuild findings, fixes and scores for a new setup, stage, target or set of
    references, without re-analyzing."""
    if stage not in STAGES:
        raise HTTPException(422, f"stage must be one of {', '.join(STAGES)}")
    for f in flags:
        if not isinstance(f, dict) or "id" not in f or "severity" not in f:
            raise HTTPException(422, "Each finding needs an id and a severity.")
    user_setup = normalize_setup(setup)
    refs = parse_references(references)
    mine = parse_references([profile])[0] if profile else None
    flags, comparison = apply_reference(apply_style(flags, measures, target, stage), mine, refs, stage)
    flags = attach_fixes(flags, user_setup, stage)
    return {
        "flags": flags,
        "score": score_flags(flags, stage),
        "style": style_match(measures, target, stage),
        "reference": comparison,
        "target": target or None,
        "setup": {**user_setup, "label": describe_setup(user_setup)},
        "stage": stage,
    }


def parse_json(raw, what, default):
    try:
        value = json.loads(raw) if raw else default
    except ValueError:
        raise HTTPException(422, f"{what} must be JSON.")
    return value if isinstance(value, type(default)) else default


def parse_setup(raw):
    return parse_json(raw, "setup", {})


def parse_references(refs):
    if not isinstance(refs, list):
        raise HTTPException(422, "references must be a list.")
    if len(refs) > MAX_REFERENCES:
        raise HTTPException(422, f"Use up to {MAX_REFERENCES} reference songs.")
    try:
        return [sanitize_profile(r) for r in refs]
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# Mounted last so the /api routes above take priority.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def main():
    import argparse

    utf8_console()

    import uvicorn

    parser = argparse.ArgumentParser(prog="seraphim-web", description="Run the Seraphim web interface.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    if already_running(url):
        # Launching twice shouldn't fail: just show the copy that's already up.
        print(f"Seraphim is already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    if port_in_use(args.port):
        sys.exit(f"Port {args.port} is being used by another program. Try: seraphim-web --port {args.port + 1}")

    print(f"Seraphim is running at {url}")
    print("Keep this window open while you use it. Close it (or press Ctrl+C) to quit.")
    if not args.no_browser:
        # Open the tab once the server is listening, not before.
        threading.Thread(target=open_when_ready, args=(url, args.port), daemon=True).start()
    # 127.0.0.1 keeps it on this computer; nobody else on the network can reach it.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def port_in_use(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def already_running(url):
    try:
        with urllib.request.urlopen(f"{url}/api/info", timeout=1) as res:
            return "version" in json.load(res)
    except (OSError, ValueError):
        return False


def open_when_ready(url, port, timeout_s=15):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not port_in_use(port):
        time.sleep(0.1)
    webbrowser.open(url)


if __name__ == "__main__":
    main()
