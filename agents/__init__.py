"""
The five agents that make the channel's cartoon Shorts, in order:

  1 casting    decides the characters (and the setting) for each episode
  2 writer     writes the sketch for them, from today's trends
  3 animator   voices, lip-sync and animation: the video
  4 publisher  uploads it to YouTube into its posting slot
  5 analyst    reads the numbers and writes the playbook the others follow

Agents hold the judgment (Gemini prompts and choices); the tools in tools/ do the work. tools/jobs.py
runs them on the posting schedule, and each agent's work is logged in `runs` under its name.
Run one on its own with `python -m agents.<name>` from the project folder.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _path in (ROOT / "tools", ROOT):  # the tools are plain modules in tools/
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

AGENTS = [
    {"key": "casting", "number": 1, "name": "Casting", "role": "Decides the characters for each episode"},
    {"key": "writer", "number": 2, "name": "Writer", "role": "Writes the sketch, from today's trends"},
    {"key": "animator", "number": 3, "name": "Animator", "role": "Voices, lip-sync and animation"},
    {"key": "publisher", "number": 4, "name": "Publisher", "role": "Uploads into the posting slots"},
    {"key": "analyst", "number": 5, "name": "Analyst", "role": "Reads the numbers, writes the playbook"},
]
