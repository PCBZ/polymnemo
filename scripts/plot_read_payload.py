#!/usr/bin/env python
"""Compare two measure_read_payload.py runs — before (no defer) vs after (defer)
— and render the saving per read method (#89 / #96).

    python scripts/plot_read_payload.py before.json after.json --png compare.png

Prints a Markdown table (for the run summary) and, with --png, a grouped bar
chart: per read op, before vs after transfer bytes, on a single log axis.
Colours: orange = before (fetches embedding), blue = after (defers it, #89).
"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

BEFORE = "#eb6834"  # fetches embedding
AFTER = "#2a78d6"  # defers embedding (#89)
INK = "#1a1a19"
MUTED = "#6b6a63"
GRID = "#e4e3de"

OPS = ["get", "recall", "list", "session"]


def _kb(n: int) -> str:
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.2f} MB"


def _fmt_bytes(before: dict, after: dict, wire: str) -> list[dict]:
    rows = []
    for op in OPS:
        if op not in before["reads"] or op not in after["reads"]:
            continue
        b = before["reads"][op][wire]
        a = after["reads"][op][wire]
        rows.append(
            {
                "op": op,
                "before": b,
                "after": a,
                "saved": b - a,
                "pct": round((b - a) / b * 100, 1) if b else 0.0,
            }
        )
    return rows


def markdown(before: dict, after: dict) -> str:
    meta = after["meta"]
    assert before["meta"]["reads_fetch_embedding"], "before run must fetch embedding"
    assert not meta["reads_fetch_embedding"], "after run must defer embedding"
    out = [
        f"## Read-payload: before vs after #89 — {meta['dim']}-dim embedding",
        "",
        f"_real `PostgresStore` reads on pg17; {meta['rows']} rows, "
        f"{meta['content_chars']}-char content; recall_limit={meta['recall_limit']}, "
        f"list_limit={meta['list_limit']}. Transfer via EXPLAIN (SERIALIZE)._",
    ]
    for wire in ("text", "binary"):
        out += [
            "",
            f"### {wire} wire format",
            "",
            "| read | before (fetch) | after (#89 defer) | saved |",
            "|---|--:|--:|--:|",
        ]
        for r in _fmt_bytes(before, after, wire):
            out.append(
                f"| `{r['op']}` | {_kb(r['before'])} | {_kb(r['after'])} | "
                f"{_kb(r['saved'])} ({r['pct']:.0f}%) |"
            )
    s_a = after["storage"]
    out += [
        "",
        "### Server storage (`pg_column_size`, same on both)",
        "",
        f"Embedding is **{s_a['embedding_pct']}%** of a stored row "
        f"({s_a['per_row_embedding']:,} B/row of {s_a['per_row_total']:,} B).",
        "",
    ]
    return "\n".join(out)


def figure(before: dict, after: dict, wire: str = "text"):
    data = _fmt_bytes(before, after, wire)
    ops = [r["op"] for r in data]
    x = range(len(ops))
    w = 0.38

    fig, ax = plt.subplots(figsize=(8, 4.6))
    fig.patch.set_facecolor("white")
    ax.bar(
        [i - w / 2 for i in x],
        [r["before"] for r in data],
        w,
        color=BEFORE,
        label="before (fetches embedding)",
    )
    ax.bar(
        [i + w / 2 for i in x],
        [r["after"] for r in data],
        w,
        color=AFTER,
        label="after (#89 defers embedding)",
    )
    ax.set_yscale("log")
    ax.set_ylabel("bytes transferred per read (log)", color=MUTED, fontsize=10)
    ax.set_xticks(list(x))
    ax.set_xticklabels(ops, fontsize=10)
    ax.set_title(
        f"Read payload before vs after #89 ({wire} wire, "
        f"{after['meta']['dim']}-dim embedding)",
        color=INK,
        fontsize=12,
        fontweight="600",
        pad=10,
    )
    ax.grid(True, axis="y", color=GRID, lw=0.8)
    ax.tick_params(colors=MUTED)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)
    # Saved % above each pair.
    for i, r in zip(x, data, strict=False):
        top = max(r["before"], r["after"])
        ax.text(
            i,
            top * 1.15,
            f"-{r['pct']:.0f}%",
            ha="center",
            fontsize=9,
            fontweight="600",
            color=AFTER,
        )
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.margins(y=0.2)
    fig.tight_layout()
    return fig


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare before/after read payload")
    ap.add_argument("before", help="JSON from the no-defer run")
    ap.add_argument("after", help="JSON from the defer run (#89)")
    ap.add_argument("--png", help="write the comparison chart here")
    ap.add_argument("--wire", default="text", choices=("text", "binary"))
    args = ap.parse_args()

    with open(args.before) as f:
        before = json.load(f)
    with open(args.after) as f:
        after = json.load(f)

    print(markdown(before, after))
    if args.png:
        figure(before, after, args.wire).savefig(
            args.png, dpi=150, bbox_inches="tight"
        )
        print(f"\nwrote {args.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
