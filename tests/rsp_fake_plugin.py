"""A protocol-conformant RSP plugin whose verdict is set by RSP_FAKE_MODE.

Invoked as a subprocess by the guard tests, never imported. Keep it dependency
free -- it runs as its own process, not as part of the suite.
"""

import json
import os
import sys

MARKER = "AKIAFAKESECRETVALUE1"


def main() -> int:
    request = json.loads(sys.stdin.read())
    if request.get("hook") == "handshake":
        print(
            json.dumps(
                {
                    "rsp_version": "0.1",
                    "name": "fake",
                    "version": "1",
                    "hooks": ["on_chunk"],
                }
            )
        )
        return 0

    mode = os.environ.get("RSP_FAKE_MODE", "allow")
    if mode == "crash":
        return 3
    if mode == "garbage":
        print("this is not json")
        return 0

    # Counts invocations, so a test can prove a BLOCK stops the remaining spawns.
    counter = os.environ.get("RSP_FAKE_COUNTER")
    if counter:
        with open(counter, "a") as handle:
            handle.write("x")

    content = request.get("content", "")
    if mode == "block" and MARKER in content:
        print(json.dumps({"verdict": "BLOCK", "reason": f"found {MARKER}"}))
        return 0
    if mode == "redact" and MARKER in content:
        start = content.encode().find(MARKER.encode())
        print(
            json.dumps(
                {
                    "verdict": "REDACT",
                    "spans": [
                        {"start": start, "end": start + len(MARKER), "type": "aws"}
                    ],
                    "replacement": "[REDACTED]",
                }
            )
        )
        return 0
    print(json.dumps({"verdict": "ALLOW"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
