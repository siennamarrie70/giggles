"""
The videos of Reels kept between the cloud's runs (GitHub Actions). GitHub's machine is wiped when a run
ends, and Instagram's API can't schedule a Reel, so a Short whose slot comes after the run that made it
has ended needs its video kept until then:

  keep(videos)        at the end of a run, the videos of its Reels still waiting, encrypted into .tmp/kept;
                      GitHub stores that folder with the run for 3 days (its artifact "shorts-<run id>",
                      .github/workflows/morning.yml). Also a Short made and reviewed but not uploaded yet
                      (YouTube's daily upload limit), with its thumbnails (keep_files), so the next run
                      uploads it instead of making it again (agents/publisher.py)
  fetch(id, run, to)  a Reel's video: downloaded from the run that kept it (gh run download) and decrypted;
                      FileNotFoundError if that run kept none (it can't be posted then); fetch_file, any
                      file kept by name
  still_running(run)  whether that run is still going: then its videos aren't kept yet, and it posts the
                      Reels whose slot comes meanwhile itself (tools/jobs.py, morning)

Encrypted with AES-256 (openssl; the key is REELS_KEY in GitHub's secrets) because anyone signed in to
GitHub can download a public repository's run files: this way nobody can watch a Short before its time,
or one you vetoed. The Reels workflow (.github/workflows/reels.yml) posts the kept ones at their slots.

Usage (the morning workflow's last step, through jobs.py):
    python tools/jobs.py keep
"""

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from common import env, tmp_path

ARTIFACT = "shorts-{run}"  # what GitHub keeps a run's videos as (.github/workflows/morning.yml)
CIPHER = ["-aes-256-cbc", "-pbkdf2", "-iter", "100000", "-salt"]
MIN_KEY = 32               # characters in REELS_KEY
GONE = re.compile(r"no (valid )?artifacts?\b", re.I)  # gh's answer when a run kept nothing (or it expired)

_fetched: set[str] = set()  # runs whose videos this process has downloaded
_ended: set[str] = set()    # runs known to have ended
_lock = threading.Lock()


class StillRunning(RuntimeError):
    """The run that made the video is still going, so its videos aren't kept yet."""


def in_cloud() -> bool:
    """Whether this is a run on GitHub Actions."""
    return os.getenv("GITHUB_ACTIONS") == "true" and bool(os.getenv("GITHUB_RUN_ID"))


def this_run() -> str | None:
    """This run's id on GitHub (None on this computer)."""
    return os.getenv("GITHUB_RUN_ID") if in_cloud() else None


def _openssl(args: list[str]) -> None:
    if len(env("REELS_KEY") or "") < MIN_KEY:
        raise RuntimeError(f"REELS_KEY isn't set ({MIN_KEY}+ characters, in GitHub's secrets)")
    exe = shutil.which("openssl")
    if not exe:
        raise RuntimeError("openssl isn't installed here")
    subprocess.run([exe, "enc", *CIPHER, *args, "-pass", "env:REELS_KEY"], check=True, capture_output=True,
                   timeout=600)


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    """GitHub's own command-line tool (on every GitHub runner), signed in by GH_TOKEN."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=600)


def keep(videos: list[tuple[int, Path]]) -> list[Path]:
    """Each (video id, file) still here, encrypted into .tmp/kept/short_<id>.mp4.enc; the files kept."""
    return keep_files([(f"short_{int(video_id)}.mp4", file) for video_id, file in videos])


def keep_files(files: list[tuple[str, Path]]) -> list[Path]:
    """Each (name, file) still here, encrypted into .tmp/kept/<name>.enc (a Short's thumbnails beside its video); the
    files kept."""
    kept = []
    for name, file in files:
        if Path(file).exists():
            dest = tmp_path("kept", f"{name}.enc")
            _openssl(["-e", "-in", str(file), "-out", str(dest)])
            kept.append(dest)
    return kept


def still_running(run: str) -> bool:
    """Whether a run of this repository is still going (False if GitHub can't say: fetch() then tries)."""
    if run in _ended:
        return False
    answer = _gh(["api", f"repos/{os.getenv('GITHUB_REPOSITORY', '')}/actions/runs/{run}", "--jq", ".status"])
    if answer.returncode != 0:
        return False
    if answer.stdout.strip() == "completed":
        _ended.add(run)
        return False
    return True


def fetch(video_id: int, run: str, dest: Path) -> Path:
    """A Reel's video at `dest`, downloaded from the run that kept it and decrypted. StillRunning while that run goes
    on; FileNotFoundError if it kept none; RuntimeError if GitHub or openssl failed (worth trying again later)."""
    return fetch_file(run, f"short_{int(video_id)}.mp4", dest)


def fetch_file(run: str, name: str, dest: Path) -> Path:
    """The file a run kept as `name` (keep_files), at `dest`; as fetch()."""
    run = str(run)
    if not re.fullmatch(r"\d+", run):
        raise FileNotFoundError(f"no run kept its video ({run[:40]!r} isn't a run)")
    if not re.fullmatch(r"[\w-]+(\.[\w-]+)+", name):
        raise ValueError(f"not a kept file's name: {name[:60]!r}")
    with _lock:
        if run not in _fetched:
            if still_running(run):
                raise StillRunning(f"run {run}, which made it, is still going")
            where = tmp_path("kept", "runs", run, "x").parent
            got = _gh(["run", "download", run, "-n", ARTIFACT.format(run=run), "-D", str(where)])
            if got.returncode != 0:
                if GONE.search(got.stderr):
                    _fetched.add(run)  # (nothing to fetch there, now or later)
                    raise FileNotFoundError(f"run {run}, which made it, didn't keep its video")
                raise RuntimeError(f"GitHub didn't give run {run}'s videos ({got.stderr.strip()[-200:]})")
            _fetched.add(run)
        enc = tmp_path("kept", "runs", run, f"{name}.enc")
        if not enc.exists():
            raise FileNotFoundError(f"run {run}, which made it, didn't keep its video")
        part = dest.with_name(dest.name + ".part")
        _openssl(["-d", "-in", str(enc), "-out", str(part)])
        part.replace(dest)
        enc.unlink(missing_ok=True)
    return dest
