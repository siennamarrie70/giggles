"""
Thin wrapper around Gemini (free tier) that returns JSON matching a schema.

Every model call in the project goes through generate_json(), so changing provider
or model means editing this one file. Models are tried in order: free-tier quotas
are per model, so a quota error or timeout on one falls through to the next.
Measured 2026-10-24 on the free tier: gemini-3.5-flash-lite answers in 2-6 s, gemini-3.1-flash-lite
and gemini-3.5-flash in ~2 s; gemini-3.8-flash took ~100 s per request (queueing), so it's the last
resort. gemini-2.5-flash is "no longer available to new users" (404).
Note: on the free tier Google may use prompts to improve its products. Nothing
private goes in here: the channel's settings, trend topics, characters and scripts.

Usage (check the key works):
    python tools/llm.py --prompt "Give me a two-word name for a cat"
"""

import argparse
import json
import sys
import time

import httpx
from google import genai
from google.genai import errors, types

from common import env

# Free-tier models, fastest first. GEMINI_MODEL in .env overrides the first choice.
DEFAULT_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]
# Casting and writing need little reasoning; less thinking = faster answers.
THINKING = {
    "gemini-3.5-flash-lite": types.ThinkingConfig(thinking_level="MINIMAL"),
    "gemini-3.1-flash-lite": types.ThinkingConfig(thinking_level="MINIMAL"),
    "gemini-3.5-flash": types.ThinkingConfig(thinking_level="MINIMAL"),
    "gemini-3.8-flash": types.ThinkingConfig(thinking_level="LOW"),  # MINIMAL isn't supported here
}
TIMEOUT_MS = 60_000

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        # attempts=1: no hidden SDK retries; generate_json() decides what to try next.
        _client = genai.Client(api_key=env("GEMINI_API_KEY", required=True), http_options=types.HttpOptions(
            timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))
    return _client


def models() -> list[str]:
    preferred = env("GEMINI_MODEL")
    return ([preferred] if preferred else []) + [m for m in DEFAULT_MODELS if m != preferred]


def _to_part(item) -> types.Part:
    """Text, or an image given as (mime_type, bytes)."""
    if isinstance(item, tuple):
        mime_type, data = item
        return types.Part.from_bytes(data=data, mime_type=mime_type)
    return types.Part.from_text(text=str(item))


def generate_json(parts: list, schema: dict, system: str) -> dict:
    """Send text/image parts and get back a dict that follows `schema`."""
    contents = [types.Content(role="user", parts=[_to_part(p) for p in parts])]
    failures = []
    for model in models():
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            thinking_config=THINKING.get(model),
        )
        for attempt in range(2):
            try:
                response = _get_client().models.generate_content(model=model, contents=contents, config=config)
                if not response.text:
                    raise ValueError("empty response")
                return json.loads(response.text)
            except errors.APIError as e:
                failures.append(f"{model}: {e.code} {e.message}")
                if e.code in (401, 403):
                    raise RuntimeError(f"Gemini rejected the API key: {e.message}") from e
                if e.code and e.code >= 500 and attempt == 0:
                    time.sleep(5)
                    continue
                break  # quota (429), unknown model (404) or unsupported request (400): next model
            except httpx.TransportError as e:  # timeout or connection problem: next model
                failures.append(f"{model}: {type(e).__name__}")
                break
            except ValueError as e:  # empty or non-JSON reply; retry once, then next model
                failures.append(f"{model}: {e}")
    raise RuntimeError("All Gemini models failed: " + " | ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()

    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    try:
        result = generate_json([args.prompt], schema, system="Answer briefly.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
