"""Web interface: a small API around the analysis engine plus a static page.

Run:  mixcheck-web            (then open http://127.0.0.1:8000)
  or: uvicorn mixcheck.web.server:app --reload
"""
import os
import tempfile
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..analyze import THRESHOLDS, analyze_file
from ..remediation import DEFAULT_PROFILE, optional_plugins

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_SUFFIXES = {".wav", ".wave", ".aif", ".aiff", ".flac"}
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GB: a long 96 kHz/32-bit stereo bounce fits
CHUNK = 1024 * 1024

app = FastAPI(title="MixCheck", version=__version__)


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
        raise HTTPException(415, f"{name} isn't a supported format. Bounce to WAV, AIFF or FLAC.")

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
    print(f"MixCheck running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    # 127.0.0.1 keeps it on this computer; nobody else on the network can reach it.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
