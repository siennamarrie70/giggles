"""
A temporary public web address for one file on this computer, so a service can fetch it: Instagram's
servers take a Reel's video from it (tools/instagram.py: video_url, the way Instagram's API is meant to
get a video, instead of this computer pushing the file to Instagram's upload server, whose last step
dropped about half the uploads on 2026-10-27).

It's Cloudflare's free quick tunnel (cloudflared; no account, nothing to set up): an address like
https://<random-words>.trycloudflare.com that leads to a small server of its own on 127.0.0.1, which
serves that one file at a random path (TOKEN_BYTES) and nothing else: never the dashboard. Both live
only inside `with link(path) as url:`, and the address dies with them. The file is served whole or in
ranges (Range requests), with its length and type; what was fetched is listed in `served`.

cloudflared is Cloudflare's own program: on this PC it's installed in C:\\Program Files (x86)\\cloudflared
(winget install Cloudflare.cloudflared); where it isn't (GitHub Actions' Linux), it's downloaded once
from Cloudflare's GitHub releases into .tmp/models/cloudflared: one pinned version (VERSION), used only
if it's exactly the file Cloudflare published (SHA256, from the release). A new tunnel's address takes a few
seconds to answer: link() waits until it serves the file (READY_FOR) before handing it out.

Usage:
    python tools/tunnel.py --file .tmp/out/short_12.mp4    # a public link to the file until Ctrl+C
"""

import argparse
import hashlib
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from common import tmp_path

INSTALLED = (r"C:\Program Files (x86)\cloudflared\cloudflared.exe", r"C:\Program Files\cloudflared\cloudflared.exe")
VERSION = "2026.10.0"  # (released 2026-10-05)
RELEASES = f"https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/"
SHA256 = {"cloudflared-windows-amd64.exe": "86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c",
          "cloudflared-linux-amd64": "d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db"}
ADDRESS = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com")  # (its log also names api.trycloudflare.com)
START_FOR = 60      # seconds for cloudflared to give the tunnel's address
READY_FOR = 120     # seconds for the address to start serving the file
TOKEN_BYTES = 16    # the random path: 32 hex characters
PIECE = 1 << 16     # bytes written at a time


class TunnelError(RuntimeError):
    """No public link could be made (cloudflared missing or failing, or the address never answered)."""


def binary(progress=print) -> str:
    """cloudflared: installed, on the PATH, or downloaded once."""
    found = shutil.which("cloudflared") or next((p for p in INSTALLED if os.path.exists(p)), None)
    if found:
        return found
    windows = sys.platform == "win32"
    asset = "cloudflared-windows-amd64.exe" if windows else "cloudflared-linux-amd64"
    path = tmp_path("models", "cloudflared", f"{VERSION}-{asset}")
    if not path.exists():
        progress("Downloading cloudflared (Cloudflare's tunnel program), once")
        partial, digest = path.with_name(path.name + ".part"), hashlib.sha256()
        try:
            with requests.get(RELEASES + asset, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with open(partial, "wb") as f:
                    for chunk in resp.iter_content(1 << 20):
                        digest.update(chunk)
                        f.write(chunk)
        except requests.RequestException as e:
            raise TunnelError(f"cloudflared couldn't be downloaded ({type(e).__name__})") from e
        if digest.hexdigest() != SHA256[asset]:
            partial.unlink(missing_ok=True)
            raise TunnelError("the cloudflared download isn't the file Cloudflare published; not used")
        partial.replace(path)
        path.chmod(0o755)
    return str(path)


def _handler(path: str, file: Path, served: list):
    """Serves `file` at `path` (GET and HEAD, whole or one byte range); anything else is 404."""

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._answer(body=False)

        def do_GET(self):
            self._answer(body=True)

        def _answer(self, body: bool):
            if self.path.split("?")[0] != path:
                self.send_error(404)
                return
            size = file.stat().st_size
            start, end = 0, size - 1
            asked = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
            if asked and (asked[1] or asked[2]):
                if asked[1]:
                    start, end = int(asked[1]), min(int(asked[2]) if asked[2] else size - 1, size - 1)
                else:  # the last N bytes
                    start = max(0, size - int(asked[2]))
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            sent = 0
            if body:
                with open(file, "rb") as f:
                    f.seek(start)
                    while sent < end - start + 1:
                        chunk = f.read(min(PIECE, end - start + 1 - sent))
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except OSError:  # the other side hung up
                            break
                        sent += len(chunk)
            served.append({"method": self.command, "range": self.headers.get("Range"), "bytes": sent,
                           "agent": (self.headers.get("User-Agent") or "")[:80]})

        def log_message(self, *args):  # (quiet: what was served is in `served`)
            pass

    return Handler


def _ready(url: str) -> None:
    """Waits until the new address serves the file (a few seconds, usually)."""
    deadline, last = time.monotonic() + READY_FOR, None
    while time.monotonic() < deadline:
        try:
            resp = requests.head(url, timeout=15)
            if resp.status_code == 200:
                return
            last = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(3)
    raise TunnelError(f"the tunnel's address never answered ({last})")


@contextmanager
def link(file: Path | str, progress=print, served: list | None = None):
    """A public https address that serves `file` while the block runs (with link(path) as url: ...). What was
    fetched from it is appended to `served` ({"method", "range", "bytes", "agent"})."""
    file = Path(file)
    path = f"/{secrets.token_hex(TOKEN_BYTES)}/{file.name}"
    served = served if served is not None else []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(path, file, served))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    process = None
    try:
        process = subprocess.Popen([binary(progress), "tunnel", "--no-autoupdate", "--url",
                                    f"http://127.0.0.1:{server.server_address[1]}"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        found, said = {}, []

        def read():  # to the end: a full pipe would stall cloudflared
            for line in process.stderr:
                said[:] = (said + [line.strip()])[-5:]
                if "url" not in found and (address := ADDRESS.search(line)):
                    found["url"] = address[0]

        threading.Thread(target=read, daemon=True).start()
        deadline = time.monotonic() + START_FOR
        while "url" not in found:
            if process.poll() is not None or time.monotonic() > deadline:
                raise TunnelError("cloudflared gave no address: " + " | ".join(said[-2:])[:300])
            time.sleep(0.5)
        url = found["url"] + path
        _ready(url)
        yield url
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
        server.shutdown()
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    served = []
    try:
        with link(args.file, served=served) as url:
            print(url, flush=True)
            while True:
                time.sleep(5)
                while served:
                    print(served.pop(0), flush=True)
    except KeyboardInterrupt:
        return 0
    except TunnelError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
