"""
Shared paths and settings for every tool.

Loads .env once, points TMP_DIR somewhere writable (.tmp/ locally, /tmp on Vercel,
where the project folder is read-only) and reads (and edits, comments kept) the YAML files in config/.
"""

import os
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


def tmp_path(*parts: str) -> Path:
    """Path inside TMP_DIR, creating parent folders as needed."""
    path = TMP_DIR.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
