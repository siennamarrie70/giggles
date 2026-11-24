"""
The seven agents that make the channel's silhouette stories (a Short or a long story, each for its turn), in order:

  1 theme       the brief: its topic (a vice or a virtue) or the writer's choice
  2 story       your script writer's script, and its moments with their bubbles (speech, thought, pictures)
  3 visuals     the pictures for the script (2026-11-24): its storyboard from the code-drawn library, everything there
                reused; what the library lacks (a thing, a bubble picture) made new, always as a silhouette, and added
                to the library for every later story (agents/visuals.py)
  4 animator    the film drawn in code from the script and those pictures (a Short upright, a long story wide), the
                long story's thumbnail
  5 reviewer    watches every film; a failed one goes back to the Animator with notes
  6 publisher   uploads what passed to YouTube into its turn: a Short with its Reel, or a long story
  7 analyst     reads the numbers (watch time first) and writes the playbook and each agent's lessons

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
    {"key": "story", "number": 2, "name": "Story", "role": "The script of each Short or long story, and its bubbles"},
    {"key": "visuals", "number": 3, "name": "Visuals", "role": "The pictures for each script: the library's reused, new silhouettes made when it lacks one"},
    {"key": "animator", "number": 4, "name": "Animator", "role": "The film drawn in code: a Short upright, a long story wide"},
    {"key": "reviewer", "number": 5, "name": "Reviewer", "role": "Watches every film; sends failures back to be fixed"},
    {"key": "publisher", "number": 6, "name": "Publisher", "role": "Each video in its slot: a Short with its Reel, or a long story"},
    {"key": "analyst", "number": 7, "name": "Analyst", "role": "Reads watch time, teaches every agent"},
]
