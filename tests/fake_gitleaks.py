#!/usr/bin/env python3
"""A stand-in for the gitleaks binary, speaking its CLI and report format.

The real binary is installed in the image, not here, so the vendored plugin is
exercised against this. What matters is the contract the plugin depends on:
`version`, exit 0 for clean and 2 for found, and a JSON report whose columns
count the way gitleaks counts them.

FAKE_GITLEAKS_MODE=fail makes it exit non-zero, which must not read as clean.
"""

import json
import os
import sys

MARKER = b"AKIAFAKESECRETVALUE1"


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "version":
        print("8.30.1")
        return 0
    if os.environ.get("FAKE_GITLEAKS_MODE") == "fail":
        print("boom", file=sys.stderr)
        return 1

    content = sys.stdin.buffer.read()
    at = content.find(MARKER)
    if at < 0:
        return 0

    # gitleaks counts a line's columns from the newline byte ending the
    # previous line, so on line 1 the origin is 0 and StartColumn is 1-based.
    line = content.count(b"\n", 0, at) + 1
    origin = 0 if line == 1 else content.rfind(b"\n", 0, at)
    report = [
        {
            "RuleID": "aws-access-token",
            "Match": MARKER.decode(),
            "StartLine": line,
            "EndLine": line,
            # One formula for both cases. The plugin's origin is 0 on line 1
            # and the previous newline's byte index after it, which is exactly
            # what `origin` holds here -- so no special case is needed, and
            # writing one got the multi-line offsets wrong.
            "StartColumn": at - origin + 1,
            "EndColumn": at + len(MARKER) - origin,
        }
    ]
    sys.stdout.write(json.dumps(report))
    return 2


if __name__ == "__main__":
    sys.exit(main())
