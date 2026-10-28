"""
The web app: the dashboard (dashboard/) at /, behind its sign-in page (/login) when it has a username and
password (always on Vercel), and the public About and Privacy pages Google
requires (pages/) at /about and /privacy. It can run on Vercel to show the dashboard; the Shorts
themselves are made by the morning run on GitHub Actions (.github/workflows/morning.yml), because
one Short needs more time and memory than a Vercel function has.

Run it on your computer:
    .venv/Scripts/python -m uvicorn app:app --port 8000
then open http://localhost:8000. While it runs with the database on this computer, it also
runs the morning run itself (dashboard/api.py), so the channel posts without GitHub too.

/api/health needs `Authorization: Bearer <CRON_SECRET>` (any request without it gets a 401) and
checks the deployment has its config, fonts, world and satellite maps, the Professor's drawings,
music, the footage keys and a working ffmpeg (the dashboard alone, on Vercel, has none). The old
/api/cron/<job> (Vercel's schedule, retired 2026-10-26) is gone: nothing used it, and with the
secret it could have started a run beside the real one on GitHub.

Every answer carries SECURITY_HEADERS: no other site may show these pages in a frame (one could
otherwise lay its own page over the dashboard's buttons and have you press them), the page may load
scripts, pictures and videos only from here (and Google's fonts), browsers mustn't guess file types,
keep any answer (no-store) or let another site's window or page reach in, and only /about and
/privacy may be listed by search engines; on Vercel, browsers use https only (HSTS). An error's
text is shown without secrets (common.redact).
"""

import hmac
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.exception_handlers import http_exception_handler
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]

import db  # noqa: E402
import infographics  # noqa: E402
import jobs  # noqa: E402
import lipsync  # noqa: E402
import short_render  # noqa: E402
from common import ASSETS_DIR, ON_VERCEL, env, load_config, redact  # noqa: E402
from dashboard.api import router as dashboard, sign_in, start_autopilot_loop  # noqa: E402
from pages.routes import router as public_pages  # noqa: E402

SECURITY_HEADERS = {
    "Content-Security-Policy": "; ".join([
        "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com", "img-src 'self' data:", "media-src 'self'", "connect-src 'self'",
        "frame-ancestors 'none'", "base-uri 'none'", "form-action 'self'", "object-src 'none'"]),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",    # no other site's window can reach into these pages
    "Cross-Origin-Resource-Policy": "same-origin",  # nor load their videos and pictures into its own page
    "Cache-Control": "no-store",  # nothing private kept by a browser or a cache (a page may say otherwise itself)
}
PUBLIC_PAGES = ("/about", "/privacy")  # the only pages search engines may list
HSTS = "max-age=63072000; includeSubDomains"  # on Vercel: browsers use https only, for two years


class SecurityHeaders:
    """Adds SECURITY_HEADERS to every answer (plain ASGI, so a long video answer still streams as it is)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if scope.get("path") not in PUBLIC_PAGES:
                    headers.setdefault("X-Robots-Tag", "noindex, nofollow")
                if ON_VERCEL:
                    headers.setdefault("Strict-Transport-Security", HSTS)
            await send(message)

        await self.inner(scope, receive, send_with_headers)


class OneConnection:
    """Each request shares one cloud-database connection, closed when it ends (db.held): a dashboard page opened 25
    connections to Neon before, ~15 s of the 20 it took from India, and the online page seemed blank."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        with db.held():
            await self.inner(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not ON_VERCEL:
        start_autopilot_loop()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SecurityHeaders)
app.add_middleware(OneConnection)
app.include_router(public_pages)
app.include_router(sign_in)
app.include_router(dashboard)


@app.exception_handler(StarletteHTTPException)
async def _without_secrets(request, error: StarletteHTTPException):
    if isinstance(error.detail, str):
        error.detail = redact(error.detail)
    return await http_exception_handler(request, error)


def _check_secret(authorization: str | None) -> None:
    secret = env("CRON_SECRET")
    if not secret or not hmac.compare_digest((authorization or "").encode(), f"Bearer {secret}".encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/api/health")
def health(authorization: str | None = Header(default=None)):
    _check_secret(authorization)
    try:
        ffmpeg = subprocess.run([short_render.ffmpeg_exe(), "-version"], capture_output=True, text=True, timeout=30)
        found = ffmpeg.stdout.splitlines()[0] if ffmpeg.returncode == 0 else ffmpeg.stderr[-300:]
    except (ImportError, OSError, RuntimeError, subprocess.SubprocessError) as e:  # (the dashboard alone has none)
        found = f"none here ({type(e).__name__})"
    return {
        "config": bool(load_config().get("channel")),
        "fonts": all(f.exists() for f in (short_render.FONT_PATH, infographics.HEAD_FONT, infographics.BODY_FONT)),
        "world_map": infographics.MAP_FILE.exists(),
        "satellite_map": (ASSETS_DIR / "maps" / "bluemarble.jpg").exists(),
        "host": (ASSETS_DIR / "host" / "rig.json").exists(),
        "music_tracks": len(short_render.music_tracks()),
        "lipsync": lipsync.ready(),
        "ffmpeg": found,
        "keys": {k: bool(env(k)) for k in ("GEMINI_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "YOUTUBE_REFRESH_TOKEN",
                                           "DATABASE_URL", "TELEGRAM_BOT_TOKEN")},
        "paused": jobs.is_true("PAUSED"),
    }
