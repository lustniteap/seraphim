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

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..analyze import THRESHOLDS, analyze_file
from ..remediation import DEFAULT_PROFILE, optional_plugins

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
        "profile": DEFAULT_PROFILE,
        "optional_plugins": optional_plugins(),
        "accepted_formats": sorted(ALLOWED_SUFFIXES),
        "thresholds": THRESHOLDS,
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    name = file.filename or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, f"{name} isn't a supported format. Bounce to WAV, AIFF, FLAC or MP3.")

    # Stream the upload to a temporary file so large bounces don't sit in memory.
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
            report = await run_in_threadpool(analyze_file, tmp_path)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(422, str(exc))
        except Exception:
            raise HTTPException(422, f"{name} couldn't be read as audio. Try re-bouncing it as a WAV.")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    report["file"]["name"] = name  # show the real name, not the temp file's
    return report


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
