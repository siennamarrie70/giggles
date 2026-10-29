"""
Copies keys from .env to the GitHub repository's secrets, so the cloud's runs (GitHub Actions: the
morning run and Reels) use the same ones as this computer. The dashboard on this computer does it
right after you connect Instagram again (dashboard/api.py), since the cloud has its own copy of the
token and would otherwise keep the old one (seen 2026-10-29).

It uses GitHub's own command-line tool (gh), already signed in on this computer, and passes each
value on its standard input: never on a command line, in a file or in a log. The repository is this
folder's `origin` on GitHub. Only from this computer (Vercel has neither gh nor the right to change
secrets).

Usage:
    python tools/cloud_secrets.py INSTAGRAM_ACCESS_TOKEN INSTAGRAM_USER_ID INSTAGRAM_USERNAME
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import ON_VERCEL, ROOT, env, redact

GH_DEFAULT = Path(r"C:\Program Files\GitHub CLI\gh.exe")  # (where Windows installs it; VS Code may not have it on PATH)
INSTAGRAM = ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID", "INSTAGRAM_USERNAME")


class CloudSecretsError(RuntimeError):
    pass


def _gh() -> str:
    exe = shutil.which("gh") or (str(GH_DEFAULT) if GH_DEFAULT.exists() else None)
    if not exe:
        raise CloudSecretsError("GitHub's tool (gh) isn't installed on this computer")
    return exe


def repository() -> str:
    """owner/name of this folder's GitHub repository (its `origin`)."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True,
                             timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        url = ""
    found = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url)
    if not found:
        raise CloudSecretsError("this folder has no GitHub repository (origin)")
    return f"{found[1]}/{found[2]}"


def copy(names=INSTAGRAM) -> dict:
    """Each key in `names` (as .env has it now) set as a secret of the GitHub repository. {"copied": [...],
    "repository": ...}; CloudSecretsError if it couldn't be done (what's copied by then stays copied)."""
    if ON_VERCEL:
        raise CloudSecretsError("only from the dashboard on your computer")
    gh, repo, copied = _gh(), repository(), []
    for name in names:
        value = env(name)
        if not value:
            raise CloudSecretsError(f"{name} is empty in .env")
        done = subprocess.run([gh, "secret", "set", name, "-R", repo], input=value, capture_output=True, text=True,
                              timeout=60)
        if done.returncode != 0:
            raise CloudSecretsError(f"GitHub didn't take {name}: {redact(done.stderr.strip())[-200:] or 'no answer'}"
                                    + (f" (copied before it: {', '.join(copied)})" if copied else ""))
        copied.append(name)
    return {"copied": copied, "repository": repo}


def main() -> int:
    try:
        print(copy(sys.argv[1:] or INSTAGRAM))
    except CloudSecretsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
