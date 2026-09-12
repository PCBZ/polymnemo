#!/usr/bin/env python
"""Render measure_read_payload.py's JSON as a visual report.

Writes a Markdown report (table + mermaid bar chart) to stdout — the
measure-read-payload workflow appends it to $GITHUB_STEP_SUMMARY — and,
optionally, a standalone SVG bar chart via --svg-out (uploaded as an artifact).
"""

from __future__ import annotations

import argparse
import json


def markdown(m: dict) -> str:
    s, w = m["storage"], m["wire"]
    per_with = round(w["with_embedding_bytes"] / m["rows"])
    per_without = round(w["without_embedding_bytes"] / m["rows"])
    return "\n".join(
        [
            f"## Read-payload measurement — {m['rows']} rows x {m['dim']}-dim",
            "",
            f"_content: {m['content_chars']} chars/row · measured on a real "
            "pgvector Postgres; data rolled back, nothing persisted._",
            "",
            "### Client transfer (bytes shipped back per read)",
            "",
            "| | total bytes | per row |",
            "|---|--:|--:|",
            f"| with embedding | {w['with_embedding_bytes']:,} | {per_with:,} |",
            f"| without embedding (#89) | {w['without_embedding_bytes']:,} | "
            f"{per_without:,} |",
            f"| **saved** | **{w['saved_bytes']:,}** | — |",
            "",
            f"**Transfer saved: {w['saved_pct']}%**",
            "",
            "```mermaid",
            "xychart-beta",
            f'    title "Client transfer bytes ({m["rows"]} rows)"',
            '    x-axis ["with embedding", "without embedding"]',
            '    y-axis "bytes"',
            f"    bar [{w['with_embedding_bytes']}, {w['without_embedding_bytes']}]",
            "```",
            "",
            "### Server storage (`pg_column_size`)",
            "",
            "| | total bytes | per row |",
            "|---|--:|--:|",
            f"| embedding column | {s['embedding_bytes']:,} | "
            f"{s['per_row_embedding']:,} |",
            f"| whole row | {s['row_bytes']:,} | {s['per_row_total']:,} |",
            "",
            f"**Embedding is {s['embedding_pct']}% of the stored row.**",
            "",
        ]
    )


def svg(m: dict) -> str:
    w = m["wire"]
    a, b = w["with_embedding_bytes"], w["without_embedding_bytes"]
    hi = max(a, b, 1)
    width, height, pad, bar_w = 480, 280, 48, 130
    base_y = height - pad
    plot_h = height - 2 * pad
    xa, xb = 90, 90 + 180
    ha, hb = int(plot_h * a / hi), int(plot_h * b / hi)

    def bar(x: int, h: int, val: int, label: str, color: str) -> str:
        y = base_y - h
        return (
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h}" '
            f'rx="4" fill="{color}"/>'
            f'<text x="{x + bar_w // 2}" y="{y - 8}" text-anchor="middle" '
            f'font-size="13" font-weight="600" fill="#111">{val:,}</text>'
            f'<text x="{x + bar_w // 2}" y="{base_y + 20}" text-anchor="middle" '
            f'font-size="12" fill="#444">{label}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="system-ui, sans-serif">'
        f'<rect width="{width}" height="{height}" fill="#fff"/>'
        f'<text x="{width // 2}" y="28" text-anchor="middle" font-size="15" '
        f'font-weight="700" fill="#111">Read transfer bytes '
        f'({m["rows"]} rows, {m["dim"]}-dim)</text>'
        f'<line x1="{pad}" y1="{base_y}" x2="{width - pad}" y2="{base_y}" '
        f'stroke="#ccc"/>'
        + bar(xa, ha, a, "with embedding", "#d0743c")
        + bar(xb, hb, b, "without (#89)", "#3c7dd0")
        + f'<text x="{width // 2}" y="{height - 6}" text-anchor="middle" '
        f'font-size="12" fill="#2a7">saved {w["saved_pct"]}%</text>'
        "</svg>"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Render read-payload report")
    ap.add_argument("json_path", help="JSON from measure_read_payload.py")
    ap.add_argument("--svg-out", help="write a standalone SVG chart here")
    args = ap.parse_args()

    with open(args.json_path) as f:
        m = json.load(f)

    print(markdown(m))
    if args.svg_out:
        with open(args.svg_out, "w") as f:
            f.write(svg(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
