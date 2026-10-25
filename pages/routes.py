"""
Public pages Google requires before the sign-in screen can be published: a home page
that says what the app does (/about) and a privacy policy (/privacy).

Unlike the dashboard these are open to everyone, locally and on Vercel. The text comes
from the templates in this folder; the channel name and contact email from config/channel.yaml.
"""

import html
from datetime import date
from pathlib import Path
from string import Template

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from common import load_config

PAGES_DIR = Path(__file__).resolve().parent
POLICY_UPDATED = date(2026, 10, 25)  # change when the privacy policy text changes

router = APIRouter()


def _render(name: str) -> HTMLResponse:
    channel = load_config()["channel"]
    email = (channel.get("contact_email") or "").strip()
    contact = (f'<a href="mailto:{html.escape(email)}">{html.escape(email)}</a>' if email
               else "the channel owner, through the “About” tab of the YouTube channel")
    body = Template((PAGES_DIR / f"{name}.html").read_text(encoding="utf-8")).substitute(
        channel=html.escape(channel["name"]),
        contact=contact,
        updated=POLICY_UPDATED.strftime("%d %B %Y").lstrip("0"),
    )
    return HTMLResponse(body)


@router.get("/about", include_in_schema=False)
def about():
    return _render("about")


@router.get("/privacy", include_in_schema=False)
def privacy():
    return _render("privacy")
