"""
<tool name>: one-line summary of what this tool does.

Inputs:  command-line arguments (see --help) and keys from .env
Outputs: files written to .tmp/ (or a deliverable pushed to a cloud service)

Usage:
    python tools/_template.py --input <value>
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = ROOT / ".tmp"

load_dotenv(ROOT / ".env")


def run(input_value: str) -> Path:
    """Do the actual work and return the path of the output file."""
    TMP_DIR.mkdir(exist_ok=True)
    output_path = TMP_DIR / "template_output.txt"
    output_path.write_text(input_value, encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--input", required=True, help="Value to process")
    args = parser.parse_args()

    # Example of reading a required key from .env:
    # api_key = os.getenv("SOME_API_KEY")
    # if not api_key:
    #     print("Error: SOME_API_KEY is not set in .env", file=sys.stderr)
    #     return 1

    try:
        output_path = run(args.input)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
