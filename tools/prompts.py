"""
Your own words, kept word for word, encrypted in prompts/*.enc because this repository is public (your choice,
2026-11-03): the silhouette look's description (look_silhouette, 2026-11-15: tools/silhouette.py draws it; agents/story.py
and the Reviewer are given it) and your script writer's prompt (script_writer, 2026-11-16: Agent 2 writes every script
with it). The key is PROMPTS_KEY, in .env and GitHub's secrets. It's only ever read into memory,
never written out or logged by the running system. (Your Agent 3 and Agent 4 prompts for the case-study Shorts went with
them on 2026-11-16; they're in git's history, tag v6-motivation-series.)

Encrypted the same way as the Reels' videos (tools/kept.py: AES-256 with openssl). Without the key it can't be read:
load() raises NoPromptKey, which makes the morning run stop and say so rather than throw a story away (tools/jobs.py).

  load("look_silhouette")   the text
  seal(name, path)          encrypts a new version (with the key in .env)

Usage:
    python tools/prompts.py --seal look_silhouette .tmp/prompts/look_silhouette.txt    # after you change it
    python tools/prompts.py --check                                                     # it can be read (size, never the text)
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from common import ROOT, env
from kept import CIPHER, MIN_KEY

PROMPTS_DIR = ROOT / "prompts"
NAMES = ("look_silhouette", "script_writer")
GIT_OPENSSL = (r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe")  # (on Windows,
# openssl comes with Git but often isn't on the PATH Python sees)


class NoPromptKey(RuntimeError):
    """PROMPTS_KEY is missing or wrong: no story can be written until it's there; no other theme would get past this."""


def _openssl() -> str:
    exe = shutil.which("openssl") or next((p for p in GIT_OPENSSL if Path(p).exists()), None)
    if not exe:
        raise NoPromptKey("openssl isn't installed here, so the prompts can't be read")
    return exe


def _key() -> dict:
    key = env("PROMPTS_KEY") or ""
    if len(key) < MIN_KEY:
        raise NoPromptKey(f"PROMPTS_KEY isn't set ({MIN_KEY}+ characters, in .env and GitHub's secrets), so the "
                          "prompts can't be read")
    return {**os.environ, "PROMPTS_KEY": key}


@lru_cache(maxsize=4)
def load(name: str) -> str:
    """The prompt's text, decrypted into memory."""
    if name not in NAMES:
        raise ValueError(f"no prompt called {name!r}")
    path = PROMPTS_DIR / f"{name}.txt.enc"
    if not path.exists():
        raise NoPromptKey(f"{path.name} isn't in the prompts folder")
    done = subprocess.run([_openssl(), "enc", *CIPHER, "-d", "-in", str(path), "-pass", "env:PROMPTS_KEY"], env=_key(),
                          capture_output=True, timeout=60)
    if done.returncode:
        raise NoPromptKey("PROMPTS_KEY doesn't open the prompts (the wrong key?)")
    return done.stdout.decode("utf-8").replace("\r\n", "\n")


def seal(name: str, source: Path) -> Path:
    """Encrypts a prompt into prompts/<name>.txt.enc."""
    if name not in NAMES:
        raise ValueError(f"no prompt called {name!r}")
    PROMPTS_DIR.mkdir(exist_ok=True)
    dest = PROMPTS_DIR / f"{name}.txt.enc"
    subprocess.run([_openssl(), "enc", *CIPHER, "-e", "-in", str(source), "-out", str(dest), "-pass", "env:PROMPTS_KEY"],
                   env=_key(), check=True, capture_output=True, timeout=60)
    load.cache_clear()
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--seal", nargs=2, metavar=("NAME", "FILE"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.seal:
            print(f"Wrote {seal(args.seal[0], Path(args.seal[1]))}")
        for name in NAMES:
            text = load(name)
            print(f"{name}: {len(text)} characters, sha1 {hashlib.sha1(text.strip().encode('utf-8')).hexdigest()[:12]}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
