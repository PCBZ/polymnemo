#!/usr/bin/env python3
"""A stand-in for the gitleaks binary, replaying a recorded case.

The real binary is installed in the image, not here, so the vendored plugin is
exercised against this. The findings it emits are not invented: FAKE_GITLEAKS_CASE
names a case in tests/fixtures/gitleaks-offsets.json, transcribed from what
gitleaks 8.30.1 actually printed. Making them up would produce numbers that
agree with whatever the adapter assumes, which is the failure the fixture's own
note describes -- and which an earlier version of this file reproduced.

FAKE_GITLEAKS_MODE=fail exits non-zero, which must not read as a clean chunk.
"""

import json
import os
import pathlib
import sys

FOUND = 2
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "gitleaks-offsets.json"


def case() -> dict | None:
    wanted = os.environ.get("FAKE_GITLEAKS_CASE")
    if not wanted:
        return None
    for entry in json.loads(FIXTURE.read_text())["tests"]:
        if str(entry["tcId"]) == str(wanted):
            return entry
    raise SystemExit(f"fake-gitleaks: no case {wanted!r}")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "version":
        print("8.30.1")
        return 0
    if os.environ.get("FAKE_GITLEAKS_MODE") == "fail":
        print("boom", file=sys.stderr)
        return 1

    sys.stdin.buffer.read()  # drain, so the writer never sees a broken pipe
    entry = case()
    findings = entry["findings"] if entry else []
    if not findings:
        return 0
    sys.stdout.write(json.dumps(findings))
    return FOUND


if __name__ == "__main__":
    sys.exit(main())
