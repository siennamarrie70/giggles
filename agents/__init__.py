"""
The six agents that make the channel's case-study Shorts, in order:

  1 editor      decides the next case: its type, its topic and the question it answers
  2 researcher  gathers the facts, data and photos from free sources and checks every fact
  3 writer      writes the two hosts' script and fact-checks it line by line
  4 animator    voices, lip-sync, visuals and animation: the video
  5 publisher   uploads it to YouTube into its posting slot (news and politics after your OK)
  6 analyst     reads the numbers and comments, and writes the playbook the others follow

The two hosts who present every case are designed once (agents/hosts.py). Agents hold the judgment
(Gemini prompts and choices); the tools in tools/ do the work. tools/jobs.py runs them on the posting
schedule, and each agent's work is logged in `runs` under its name. Run one on its own with
`python -m agents.<name>` from the project folder.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _path in (ROOT / "tools", ROOT):  # the tools are plain modules in tools/
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

AGENTS = [
    {"key": "editor", "number": 1, "name": "Editor", "role": "Chooses the next case and its question"},
    {"key": "researcher", "number": 2, "name": "Researcher", "role": "Gathers and checks the facts, data and photos"},
    {"key": "writer", "number": 3, "name": "Writer", "role": "Writes the hosts' script and fact-checks it"},
    {"key": "animator", "number": 4, "name": "Animator", "role": "Voices, lip-sync and animation"},
    {"key": "publisher", "number": 5, "name": "Publisher", "role": "Uploads into the posting slots"},
    {"key": "analyst", "number": 6, "name": "Analyst", "role": "Reads the numbers, writes the playbook"},
]
