#!/usr/bin/env python3

import argparse
import re
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("build_log", type=Path)
    args = parser.parse_args()

    text = args.build_log.read_text(encoding="utf-8", errors="ignore")
    conflicts = re.findall(r"^\s*Conflict:.*$", text, flags=re.MULTILINE)

    if conflicts:
        print("Jekyll build reported destination conflicts:", file=sys.stderr)
        for line in conflicts:
            print(line.strip(), file=sys.stderr)
        return 1

    print("Jekyll build log is free of destination conflict warnings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
