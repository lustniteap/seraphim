"""Start the real server, then check it from outside like a browser would.

    python tests/smoke_server.py

Starts `python -m mixcheck.web.server` on a free port, waits for it to answer, then checks /api/info,
/api/scan and an upload of a generated WAV through /api/analyze (which writes and then deletes a
temporary file, the part most likely to behave differently on Windows). Exits non-zero on any problem.
"""
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_wav(seconds=3, fs=44100):
    import math
    import struct
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(fs)
        frames = b"".join(struct.pack("<hh", *(int(12000 * math.sin(2 * math.pi * 220 * i / fs)),) * 2)
                          for i in range(seconds * fs))
        w.writeframes(frames)
    return buf.getvalue()


def post_file(port, name, data):
    boundary = "----seraphim-smoke"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    conn.request("POST", "/api/analyze", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    res = conn.getresponse()
    return res.status, json.loads(res.read())


def main():
    port = free_port()
    home = tempfile.mkdtemp(prefix="seraphim-smoke-")
    env = {**os.environ, "MIXCHECK_HOME": home, "PYTHONPATH": str(ROOT)}
    server = subprocess.Popen([sys.executable, "-m", "mixcheck.web.server", "--port", str(port), "--no-browser"],
                              env=env)
    try:
        info = None
        for _ in range(120):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=2) as res:
                    info = json.load(res)
                break
            except OSError:
                if server.poll() is not None:
                    sys.exit(f"the server exited early with code {server.returncode}")
                time.sleep(0.5)
        if info is None:
            sys.exit("the server never answered")
        print("info:", info["platform"], "version", info["version"])
        assert info["platform"]["id"] in ("mac", "windows", "other")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/scan", timeout=30) as res:
            scan = json.load(res)
        print("scan:", scan["platform"], "supported" if scan["supported"] else "unsupported",
              [d["id"] for d in scan["daws"]], list(scan["packages"]), "waves" if scan["waves_installed"] else "")

        status, report = post_file(port, "smoke test.wav", make_wav())
        assert status == 200, (status, report)
        assert report["file"]["name"] == "smoke test.wav" and report["flags"] is not None
        print("analyze: ok, score", report["score"]["value"])

        # The upload must not be left behind in the temp folder.
        leftovers = [p for p in Path(tempfile.gettempdir()).glob("tmp*.wav") if time.time() - p.stat().st_mtime < 120]
        assert not leftovers, f"uploaded file left behind: {leftovers[:2]}"
        print("smoke test passed")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
