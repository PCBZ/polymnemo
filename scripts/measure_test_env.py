#!/usr/bin/env python
"""Measure the read payload against the DEPLOYED test env (#89 / #96).

The test env runs at POLYMNEMO_LOG_LEVEL=DEBUG, so its reads emit the #96 observe
log (`read <op>: N rows, embedding fetched|deferred (~M bytes)`), which Azure
collects in Log Analytics. This script:

  1. targets the test env (its /mcp endpoint + Log Analytics workspace)
  2. runs the explicit test cases from scripts/read_payload_cases.csv
     (op, fanout) — seeds once, then reads each op at its fan-out; the observe
     log self-labels by the "N rows" it returns
  3. fetches the observe log lines from Log Analytics (via `az`)
  4. saves them (parsed) to a local JSON file

Run it once on the no-defer image and once on the +defer image, then compare the
two files: `fetched (~N bytes)` -> `deferred (~0)`.

Needs: az (logged in; `az extension add -n log-analytics` if prompted), python3.
stdlib only. Configure via flags or env (TEST_MCP_ENDPOINT, TEST_API_KEY, ...).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

_OBSERVE_RE = re.compile(
    r"read (?P<op>\w+): (?P<rows>\d+) rows, embedding (?P<state>fetched|deferred) "
    r"\(~(?P<bytes>\d+) bytes\)"
)


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


def fetch_logs(app: str, rg: str, workspace: str) -> list[dict]:
    """Pull the observe log lines from Log Analytics via az; parse to records."""
    wsid = subprocess.run(
        [
            "az",
            "monitor",
            "log-analytics",
            "workspace",
            "show",
            "-g",
            rg,
            "-n",
            workspace,
            "--query",
            "customerId",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    kql = (
        "ContainerAppConsoleLogs_CL "
        f"| where ContainerAppName_s == '{app}' "
        "| where Log_s startswith 'read ' "
        "| project TimeGenerated, Log_s "
        "| order by TimeGenerated desc | take 1000"
    )
    raw = subprocess.run(
        [
            "az",
            "monitor",
            "log-analytics",
            "query",
            "--workspace",
            wsid,
            "--analytics-query",
            kql,
            "-o",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    records = []
    for row in json.loads(raw):
        m = _OBSERVE_RE.search(row.get("Log_s", ""))
        if m:
            records.append(
                {
                    "time": row.get("TimeGenerated"),
                    "op": m["op"],
                    "rows": int(m["rows"]),
                    "state": m["state"],
                    "bytes": int(m["bytes"]),
                }
            )
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure read payload on the test env")
    ap.add_argument(
        "--endpoint", default=os.getenv("TEST_MCP_ENDPOINT"), help="test /mcp URL"
    )
    ap.add_argument("--key", default=os.getenv("TEST_API_KEY"), help="bearer key")
    ap.add_argument("--app", default=os.getenv("TEST_APP", "polymnemo-test"))
    ap.add_argument("--rg", default=os.getenv("TEST_RG", "polymnemo-test-rg"))
    ap.add_argument("--workspace", default=os.getenv("TEST_WORKSPACE"))
    ap.add_argument(
        "--cases",
        default=os.path.join(os.path.dirname(__file__), "read_payload_cases.csv"),
        help="CSV of test cases (columns: op, fanout)",
    )
    ap.add_argument(
        "--ingest-wait", type=int, default=180, help="Log Analytics lag (s)"
    )
    ap.add_argument(
        "--out", default=f"read-payload-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    args = ap.parse_args()

    if not args.endpoint or not args.key:
        print(
            "error: set --endpoint/--key (or TEST_MCP_ENDPOINT/TEST_API_KEY)",
            file=sys.stderr,
        )
        return 2
    workspace = args.workspace or f"{args.app}-logs"
    cases = read_cases(args.cases)

    print(f"1) test env: {args.app}  ({args.endpoint})")
    print(f"2) seed + read, {len(cases)} cases from {os.path.basename(args.cases)}")
    exercise(args.endpoint, args.key, cases)

    print(f"3) wait {args.ingest_wait}s for Log Analytics ingestion")
    time.sleep(args.ingest_wait)

    print("4) fetch observe logs")
    records = fetch_logs(args.app, args.rg, workspace)
    with open(args.out, "w") as f:
        json.dump(records, f, indent=2)
    print(f"saved {len(records)} observe records to {args.out}")
    if not records:
        print("(0 records — ingestion may still be lagging; re-run in a minute)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
