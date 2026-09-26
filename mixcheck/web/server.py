"""Web interface: a small API around the analysis engine plus a static page.

Run:  mixcheck-web            (then open http://127.0.0.1:8000)
  or: uvicorn mixcheck.web.server:app --reload
"""
import json
import os
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
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .. import notes as ai_notes
from .. import refsets
from ..analyze import THRESHOLDS, analyze_file
from ..catalog import options as setup_options
from ..reference import MAX_REFERENCES, apply_reference, profile_file, sanitize_profile
from ..remediation import STAGES, attach_fixes, describe_setup, normalize_setup
from ..score import score_flags
from ..style import apply_style, style_match
from ..style import options as style_options

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_SUFFIXES = {".wav", ".wave", ".aif", ".aiff", ".flac", ".mp3"}
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GB: a long 96 kHz/32-bit stereo bounce fits
CHUNK = 1024 * 1024

app = FastAPI(title="MixCheck", version=__version__)


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
        "style_options": style_options(),
        "accepted_formats": sorted(ALLOWED_SUFFIXES),
        "thresholds": THRESHOLDS,
        "max_references": MAX_REFERENCES,
        "ai_notes": dict(zip(("available", "reason"), ai_notes.available())),
    }


async def with_upload(file, work):
    """Stream an upload to a temporary file, run work(path) in a thread, and always delete the file."""
    name = file.filename or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, f"{name} isn't a supported format. Use WAV, AIFF, FLAC or MP3.")

    # Stream to disk so large bounces don't sit in memory.
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

        try:
            return await run_in_threadpool(work, tmp_path)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(422, str(exc))
        except Exception:
            raise HTTPException(422, f"{name} couldn't be read as audio. Try re-bouncing it as a WAV.")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), setup: str = Form("{}"), stage: str = Form("auto"),
                  target: str = Form(""), references: str = Form("[]")):
    name = file.filename or "upload"
    user_setup = parse_setup(setup)
    refs = parse_references(parse_json(references, "references", []))
    report = await with_upload(file, lambda p: analyze_file(p, user_setup, stage, target or None, refs))
    report["file"]["name"] = name  # show the real name, not the temp file's
    if report.get("profile"):
        report["profile"]["name"] = name
    return report


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
    inp = result.pop("input")
    # Let the page show steps and findings by id without re-deriving MixCheck's numbering.
    result["steps"] = {s["id"]: s["text"] for f in inp["findings"] for s in f["steps"] + f["other_options"]}
    result["findings"] = {f["id"]: f["kind"] for f in inp["findings"]}
    return result


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

    import uvicorn

    parser = argparse.ArgumentParser(prog="mixcheck-web", description="Run the MixCheck web interface.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    if already_running(url):
        # Launching twice shouldn't fail: just show the copy that's already up.
        print(f"MixCheck is already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    if port_in_use(args.port):
        sys.exit(f"Port {args.port} is being used by another program. Try: mixcheck-web --port {args.port + 1}")

    print(f"MixCheck is running at {url}")
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
