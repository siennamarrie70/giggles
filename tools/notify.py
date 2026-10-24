"""
Sends a short message to your phone through a Telegram bot (optional).

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to turn it on; otherwise messages are
only printed (they show up in Vercel's logs). A failed message never fails a job.

Usage:
    python tools/notify.py --text "Hello from the channel bot"
"""

import argparse
import sys
from collections import deque
from datetime import datetime, timezone

import requests

from common import env

history = deque(maxlen=50)  # recent messages, shown in the dashboard's Activity tab


def is_configured() -> bool:
    return bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"))


def _send(text: str) -> bool:
    if not is_configured():
        return False
    try:
        resp = requests.post(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage", timeout=15,
                             json={"chat_id": env("TELEGRAM_CHAT_ID"), "text": text[:4000],
                                   "disable_web_page_preview": True})
        return resp.ok
    except requests.RequestException:
        return False


def run(text: str) -> bool:
    print(f"[notify] {text}")
    sent = _send(text)
    history.appendleft({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "text": text, "sent": sent})
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--text", required=True)
    args = parser.parse_args()

    sent = run(args.text)
    print("Sent to Telegram" if sent else "Not sent (Telegram not configured or unreachable)")
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
