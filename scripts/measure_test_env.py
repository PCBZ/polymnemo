#!/usr/bin/env python
"""Measure the read payload against the Neon test branch (#89 / #96).

Run polymnemo locally against the test branch at POLYMNEMO_LOG_LEVEL=DEBUG, so
its reads emit the #96 observe log (`read <op>: N rows, embedding
fetched|deferred (~M bytes)`). See deploy/terraform/test/README.md for the server
command. This script:

  1. notes where the server's log file currently ends
  2. runs the explicit test cases from scripts/read_payload_cases.csv
     (op, fanout) — seeds once, then reads each op at its fan-out; the observe
     log self-labels by the "N rows" it returns
  3. parses the lines the run appended, and saves them to a local JSON file

Run it once on main (no defer) and once on the +defer branch, then compare the
two files: `fetched (~N bytes)` -> `deferred (~0)`.

Needs: python3, stdlib only. Configure via flags or env (TEST_MCP_ENDPOINT,
TEST_API_KEY, TEST_LOG_FILE).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

_OBSERVE_RE = re.compile(
    r"read (?P<op>\w+): (?P<rows>\d+) rows, embedding (?P<state>fetched|deferred) "
    r"\(~(?P<bytes>\d+) bytes\)"
)
# Leading `%(asctime)s` from the server's logging.basicConfig format.
_TIME_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})")


def mcp(endpoint: str, key: str, tool: str, args: dict) -> dict:
    """Call an MCP tool over Streamable HTTP; return the JSON-RPC result dict."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode()
    # Streamable HTTP replies as SSE: find the `data: {json}` line.
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :]).get("result", {})
    return {}


def read_cases(path: str) -> list[tuple[str, int]]:
    """Load the explicit test-case table (op, fanout) from CSV."""
    with open(path, newline="") as f:
        return [(r["op"].strip(), int(r["fanout"])) for r in csv.DictReader(f)]


def exercise(endpoint: str, key: str, cases: list[tuple[str, int]]) -> None:
    """Seed once (to the largest recall/list fan-out), then run each case's read
    at its fan-out via `limit`. The #96 observe log self-labels by rows returned.

    Note: the `recall` case reads via the recall tool, which the store logs as
    op `search`; `list`/`get`/`session` keep their names.
    """
    stamp = int(time.time())
    ns = f"measure-{stamp}"
    sess = f"measure-sess-{stamp}"
    max_fanout = max((n for op, n in cases if op in ("recall", "list")), default=1)

    ids: list[str] = []
    for i in range(max_fanout):
        r = mcp(
            endpoint, key, "remember", {"content": f"measure row {i}", "namespace": ns}
        )
        if not ids:
            ids = (r.get("structuredContent") or {}).get("ids", [])
    mcp(endpoint, key, "save_session", {"session_id": sess, "content": "a\nb\nc"})

    for op, n in cases:
        if op == "recall":
            mcp(
                endpoint,
                key,
                "recall",
                {"query": "measure", "namespace": ns, "limit": n},
            )
        elif op == "list":
            mcp(endpoint, key, "list_memories", {"namespace": ns, "limit": n})
        elif op == "get" and ids:
            mcp(endpoint, key, "get_memory", {"id": ids[0]})
        elif op == "session":
            mcp(endpoint, key, "load_session", {"session_id": sess})
        print(f"  {op:>8} @ fanout {n}")


def log_end(path: str) -> int:
    """Byte offset of the log's current end, so we only read what this run adds."""
    return os.path.getsize(path) if os.path.exists(path) else 0


def parse_logs(path: str, offset: int) -> list[dict]:
    """Parse the observe lines the run appended past `offset`."""
    with open(path, errors="replace") as f:
        f.seek(offset)
        lines = f.readlines()

    records = []
    for line in lines:
        m = _OBSERVE_RE.search(line)
        if m:
            stamped = _TIME_RE.match(line)
            records.append(
                {
                    "time": stamped.group(1) if stamped else None,
                    "op": m["op"],
                    "rows": int(m["rows"]),
                    "state": m["state"],
                    "bytes": int(m["bytes"]),
                }
            )
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure read payload on the test branch")
    ap.add_argument(
        "--endpoint",
        default=os.getenv("TEST_MCP_ENDPOINT", "http://127.0.0.1:8000/mcp"),
        help="the locally-run server's /mcp URL",
    )
    ap.add_argument("--key", default=os.getenv("TEST_API_KEY"), help="bearer key")
    ap.add_argument(
        "--log",
        default=os.getenv("TEST_LOG_FILE"),
        help="the server's log file (it must be running at DEBUG)",
    )
    ap.add_argument(
        "--cases",
        default=os.path.join(os.path.dirname(__file__), "read_payload_cases.csv"),
        help="CSV of test cases (columns: op, fanout)",
    )
    ap.add_argument(
        "--out", default=f"read-payload-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    args = ap.parse_args()

    if not args.key or not args.log:
        print(
            "error: set --key/--log (or TEST_API_KEY/TEST_LOG_FILE)",
            file=sys.stderr,
        )
        return 2
    if not os.path.exists(args.log):
        print(
            f"error: no log file at {args.log} — is the server running?",
            file=sys.stderr,
        )
        return 2
    cases = read_cases(args.cases)

    print(f"1) server: {args.endpoint}  (log: {args.log})")
    offset = log_end(args.log)

    print(f"2) seed + read, {len(cases)} cases from {os.path.basename(args.cases)}")
    exercise(args.endpoint, args.key, cases)

    # StreamHandler flushes per record, so this is just slack for a pipe.
    time.sleep(1)

    print("3) parse the observe lines this run appended")
    records = parse_logs(args.log, offset)
    with open(args.out, "w") as f:
        json.dump(records, f, indent=2)
    print(f"saved {len(records)} observe records to {args.out}")
    if not records:
        print("(0 records — is POLYMNEMO_LOG_LEVEL=DEBUG set on the server?)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
