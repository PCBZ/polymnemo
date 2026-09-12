#!/usr/bin/env python3
"""Post the Gemini review as a GitHub PR Review with inline line comments.

The model can't run shell tools in the CI (gemini-cli denies run_shell_command
by policy in non-interactive mode), so it only WRITES a JSON object and this
script posts it deterministically:

    {"summary": "<markdown>",
     "comments": [{"path","line","severity","body"}, ...]}

Each finding becomes an inline comment on its diff line, prefixed by a severity
dot — 🔴 high · 🟠 medium · 🟡 low. Findings whose (path, line) can't be matched
to the diff are appended to the summary so nothing is lost. Reads env REVIEW_JSON,
PR, REPO and the file pr.diff. stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

DOTS = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    return s


def _diff_right_lines(path: str) -> dict[str, set[int]]:
    """file -> NEW-file line numbers present in the diff (added or context lines
    on the RIGHT side); those are the lines GitHub lets us comment on."""
    valid: dict[str, set[int]] = {}
    cur: str | None = None
    new_ln: int | None = None
    with open(path) as f:
        for line in f:
            if line.startswith("+++ "):
                p = line[4:].strip()
                cur = p[2:] if p.startswith("b/") else (None if p == "/dev/null" else p)
                new_ln = None
            elif line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                new_ln = int(m.group(1)) if m else None
            elif cur and new_ln is not None:
                if line.startswith("+++"):
                    continue
                if line.startswith(("+", " ")):
                    valid.setdefault(cur, set()).add(new_ln)
                    new_ln += 1
                # '-' lines are RIGHT-side absent; other lines are ignored
    return valid


def _post_review(repo: str, pr: str, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "gh", "api", "--method", "POST",
            f"repos/{repo}/pulls/{pr}/reviews", "--input", "-",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
    )


def main() -> int:
    repo = os.environ["REPO"]
    pr = os.environ["PR"]
    data = json.loads(_strip_fences(os.environ["REVIEW_JSON"]))

    summary = (data.get("summary") or "").strip() or "## 🤖 Gemini review"
    comments = data.get("comments") or []
    valid = _diff_right_lines("pr.diff")

    inline: list[dict] = []
    orphan: list[str] = []
    for c in comments:
        p, ln = c.get("path"), c.get("line")
        body = (c.get("body") or "").strip()
        if not body:
            continue
        dot = DOTS.get(str(c.get("severity", "")).lower(), "🟡")
        if p in valid and isinstance(ln, int) and ln in valid[p]:
            inline.append(
                {"path": p, "line": ln, "side": "RIGHT", "body": f"{dot} {body}"}
            )
        else:
            orphan.append(f"- {dot} `{p}:{ln}` — {body}")

    body = summary
    if orphan:
        body += (
            "\n\n<details><summary>Findings not anchored to a diff line</summary>"
            "\n\n" + "\n".join(orphan) + "\n</details>"
        )

    payload: dict = {"body": body, "event": "COMMENT"}
    if inline:
        payload["comments"] = inline

    result = _post_review(repo, pr, payload)
    if result.returncode == 0:
        print(f"posted review ({len(inline)} inline, {len(orphan)} orphaned)")
        return 0

    # Inline anchoring rejected (e.g. 422): retry body-only so the review survives.
    sys.stderr.write(result.stderr + "\n")
    if not inline:
        return 1
    fallback = {
        "body": body + "\n\n_(inline anchoring failed; posted as summary)_",
        "event": "COMMENT",
    }
    retry = _post_review(repo, pr, fallback)
    if retry.returncode != 0:
        sys.stderr.write(retry.stderr + "\n")
        return 1
    print("posted summary-only review (inline anchoring failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
