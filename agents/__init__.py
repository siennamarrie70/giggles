"""
The seven agents that make the channel's case-study Shorts, in order:

  1 editor      decides the next case: its type, its topic, the paradox and the question it answers
  2 researcher  gathers the facts, data, photos and footage from free sources and checks every fact
  3 writer      writes the Professor's script as a mystery and fact-checks it line by line
  4 animator    the Professor's voice and lip-sync, the footage and graphics: the video and its thumbnail
  5 reviewer    watches and listens to every video; a failed one goes back to the animator with notes
  6 publisher   uploads what passed to YouTube into its posting slot, and to Instagram as a Reel
  7 analyst     reads the numbers and comments, and writes the playbook and each agent's lessons

Every agent learns: the Reviewer's recurring problems become standing fixes and advice, and the
Analyst's numbers become lessons for each agent (agents/base.py lessons_for).

The Professor hosts every case (the user's own character: assets/host/, tools/host.py). Agents hold the judgment
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
    {"key": "researcher", "number": 2, "name": "Researcher", "role": "Gathers and checks the facts, photos and footage"},
    {"key": "writer", "number": 3, "name": "Writer", "role": "Writes the Professor's mystery and fact-checks it"},
    {"key": "animator", "number": 4, "name": "Animator", "role": "The Professor's voice, the edit and the thumbnail"},
    {"key": "reviewer", "number": 5, "name": "Reviewer", "role": "Checks every video; sends failures back to be fixed"},
    {"key": "publisher", "number": 6, "name": "Publisher", "role": "Posts to YouTube and Instagram in the slots"},
    {"key": "analyst", "number": 7, "name": "Analyst", "role": "Reads the numbers, teaches every agent"},
]
