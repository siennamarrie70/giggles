"""
The web app: Vercel Cron calls /api/cron/autopilot every hour and /api/cron/stats once a
day, the dashboard (dashboard/) is served at /, and the public About and Privacy pages
Google requires (pages/) at /about and /privacy.

Run it on your computer:
    .venv/Scripts/python -m uvicorn app:app --port 8000
then open http://localhost:8000. While it runs with the database on this computer, it also
runs the autopilot itself (dashboard/api.py), so the channel posts without Vercel too.

Vercel sends `Authorization: Bearer <CRON_SECRET>` with every cron request; any request
without it gets a 401. /api/health (same secret) checks the deployment has its config,
font, music and a working ffmpeg.
"""

import hmac
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]

import jobs  # noqa: E402
import short_render  # noqa: E402
from common import ON_VERCEL, env, load_config  # noqa: E402
from dashboard.api import router as dashboard, start_autopilot_loop  # noqa: E402
from pages.routes import router as public_pages  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not ON_VERCEL:
        start_autopilot_loop()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(public_pages)
app.include_router(dashboard)


def _check_secret(authorization: str | None) -> None:
    secret = env("CRON_SECRET")
    if not secret or not hmac.compare_digest(authorization or "", f"Bearer {secret}"):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/api/cron/{job}")
def cron(job: str, authorization: str | None = Header(default=None)):
    _check_secret(authorization)
    if job not in jobs.JOBS:
        raise HTTPException(status_code=404, detail="unknown job")
    if jobs.is_true("PAUSED"):  # checked before run_job so a paused deploy needs no database yet
        return {"skipped": "PAUSED is set"}
    if job == "autopilot":  # hourly: does real work only when a posting slot is due
        return jobs.tick()
    return jobs.run_job(job)


@app.get("/api/health")
def health(authorization: str | None = Header(default=None)):
    _check_secret(authorization)
    ffmpeg = subprocess.run([short_render.ffmpeg_exe(), "-version"], capture_output=True, text=True, timeout=30)
    return {
        "config": bool(load_config().get("channel")),
        "font": short_render.FONT_PATH.exists(),
        "music_tracks": len([p for p in short_render.MUSIC_DIR.glob("*") if p.suffix.lower() in short_render.MUSIC_EXTS]),
        "ffmpeg": ffmpeg.stdout.splitlines()[0] if ffmpeg.returncode == 0 else ffmpeg.stderr[-300:],
        "keys": {k: bool(env(k)) for k in ("GEMINI_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "YOUTUBE_REFRESH_TOKEN",
                                           "DATABASE_URL", "TELEGRAM_BOT_TOKEN")},
        "paused": jobs.is_true("PAUSED"),
    }
