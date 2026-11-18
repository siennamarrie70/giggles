"""
The six agents that make the channel's daily motivation story, in order:

  1 theme       the day's theme, a vice or a virtue, and the title named from it
  2 story       the screenplay in eight parts, shot by shot in the look's own vocabulary, the narrator's script, and the
                short version's script (the whole story in under a minute)
  3 animator    the narrator's reading, the film drawn in code in your silhouette look, its thumbnail, its short version
  4 reviewer    watches and listens to every film and its short version; a failed one goes back to the Animator with notes
  5 publisher   uploads what passed to YouTube into its slot, the short version as a Short after it, and as a Reel
  6 analyst     reads the numbers (watch time first) and writes the playbook and each agent's lessons

Every agent learns: the Reviewer's recurring problems become standing fixes and advice, and the Analyst's numbers become
lessons for each agent (agents/base.py lessons_for).

Agents hold the judgment (Gemini prompts and choices); the tools in tools/ do the work. tools/jobs.py runs them on the
posting schedule, and each agent's work is logged in `runs` under its name. Run one on its own with
`python -m agents.<name>` from the project folder.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _path in (ROOT / "tools", ROOT):  # the tools are plain modules in tools/
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

AGENTS = [
    {"key": "theme", "number": 1, "name": "Theme", "role": "The day's theme, a vice or a virtue, and its title"},
    {"key": "story", "number": 2, "name": "Story", "role": "The screenplay, the narrator's script, the short version's"},
    {"key": "animator", "number": 3, "name": "Animator", "role": "The narrator, the film drawn in code, its short version"},
    {"key": "reviewer", "number": 4, "name": "Reviewer", "role": "Watches every film; sends failures back to be fixed"},
    {"key": "publisher", "number": 5, "name": "Publisher", "role": "The film in its slot, its short version after"},
    {"key": "analyst", "number": 6, "name": "Analyst", "role": "Reads watch time, teaches every agent"},
]
