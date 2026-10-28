"""
Shared paths and settings for every tool.

Loads .env once, points TMP_DIR somewhere writable (.tmp/ locally, /tmp on Vercel,
where the project folder is read-only) and reads (and edits, comments kept) the YAML files in config/.

redact() hides secrets in text before it's shown, saved, printed or sent: a failed web request's
error names its whole address, and some services take their key in it (Instagram's access_token,
Pixabay's key, Telegram's bot token), so one network error put a token into the dashboard, the
database, a Telegram message and the morning run's log, which is public on GitHub (found 2026-10-27).
"""

import os
import re
import sys
import tempfile
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ASSETS_DIR = ROOT / "assets"

ON_VERCEL = bool(os.getenv("VERCEL"))
TMP_DIR = Path(tempfile.gettempdir()) / "ezzy" if ON_VERCEL else ROOT / ".tmp"

load_dotenv(ROOT / ".env")

# Titles and messages contain emoji; don't crash when a Windows console can't show them.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Read an environment variable, failing with a clear message if it's required."""
    value = os.getenv(name) or default
    if required and not value:
        where = "the Vercel project's Environment Variables" if ON_VERCEL else ".env"
        raise RuntimeError(f"{name} is not set. Add it to {where}.")
    return value


def is_true(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


SECRET_NAMES = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL|POSTGRES_URL", re.I)
SECRET_PARAMS = re.compile(r"(?i)([?&](?:access_token|input_token|fb_exchange_token|client_secret|refresh_token|key|"
                           r"token|upload_id)=)[^&\s'\"<>]+")
BOT_PATH = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")
_made_secrets: set[str] = set()  # secrets made while running (keep_secret)


def keep_secret(value: str) -> None:
    """A secret made while running, not kept in the environment (YouTube's hourly access token): redact() hides it
    too, and so do GitHub's run logs (public for a public repository)."""
    if value and len(value) >= 8 and value not in _made_secrets:
        _made_secrets.add(value)
        if os.getenv("GITHUB_ACTIONS") == "true":
            print(f"::add-mask::{value}", flush=True)


def redact(text, addresses: bool = True) -> str:
    """The text with every secret hidden: the value of each key, token, secret, password and database address in the
    environment (.env, or GitHub's and Vercel's settings), each secret made while running (keep_secret) and, with
    `addresses`, any token or key in a web address and a Telegram bot's (for one not kept in the environment, like a
    token just made while connecting Instagram)."""
    text = str(text)
    for name, value in os.environ.items():
        if value and len(value) >= 8 and SECRET_NAMES.search(name) and value in text:
            text = text.replace(value, "[hidden]")
    for value in list(_made_secrets):
        if value in text:
            text = text.replace(value, "[hidden]")
    return BOT_PATH.sub("/bot[hidden]", SECRET_PARAMS.sub(r"\1[hidden]", text)) if addresses else text


def load_config(name: str = "channel") -> dict:
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def update_config(change, name: str = "channel") -> None:
    """Edits config/<name>.yaml in place, keeping its comments: change(data) changes the loaded YAML."""
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.preserve_quotes = True  # "14:00" must stay a string (unquoted, YAML 1.1 reads it as a number)
    yaml.width = 130  # wide enough that lines already in the file aren't re-wrapped
    path = CONFIG_DIR / f"{name}.yaml"
    data = yaml.load(path.read_text(encoding="utf-8"))
    change(data)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


def background_priority() -> None:
    """This process, and the programs it starts (ffmpeg, Rhubarb), at below-normal priority: the channel's work gives
    way to whatever you're doing on this computer and only takes a little longer (see tools/jobs.py)."""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        kernel = ctypes.WinDLL("kernel32")  # its own copy: the types set here don't change ctypes.windll's for others
        kernel.GetCurrentProcess.restype = wt.HANDLE  # (left as int, the handle is cut to 32 bits and the call fails)
        kernel.SetPriorityClass.argtypes = [wt.HANDLE, wt.DWORD]
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
    else:
        try:
            os.nice(5)
        except OSError:
            pass


def tmp_path(*parts: str) -> Path:
    """Path inside TMP_DIR, creating parent folders as needed."""
    path = TMP_DIR.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
