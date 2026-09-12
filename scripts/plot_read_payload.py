#!/usr/bin/env python
"""Plot the #96 sweep JSON (from measure_read_payload.py --sweep) as a matplotlib
figure, plus a Markdown data table for the run summary.

Two panels, one per designed sweep:
  A  read transfer vs content size   (rows fixed at list_limit)
  B  read transfer vs result size    (content fixed at a typical chunk)

Each panel plots per-read wire bytes WITH vs WITHOUT the embedding column on a
single log axis (never a dual axis) — the gap between the two lines is exactly
what deferring the embedding (#89) saves. Colours come from the validated
categorical palette: orange = embedding fetched (the cost), blue = deferred (#89).

    pip install matplotlib
    python scripts/plot_read_payload.py sweep.json --png read_payload.png
"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")  # headless: render to file, no display
import matplotlib.pyplot as plt

WITH = "#eb6834"  # cost — embedding fetched
WITHOUT = "#2a78d6"  # win — embedding deferred (#89)
INK = "#1a1a19"
MUTED = "#6b6a63"
GRID = "#e4e3de"


def _kb(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _panel(
    ax,
    points,
    xkey,
    xlabel,
    title,
    *,
    annotate_pct_at=None,
    marks=None,
    legend_loc="upper left",
):
    xs = [p[xkey] for p in points]
    yw = [p["wire"]["with_embedding_bytes"] for p in points]
    yo = [p["wire"]["without_embedding_bytes"] for p in points]

    ax.plot(xs, yw, marker="o", ms=7, lw=2, color=WITH, label="with embedding")
    ax.plot(
        xs, yo, marker="o", ms=7, lw=2, color=WITHOUT, label="without embedding (#89)"
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(xlabel, color=MUTED, fontsize=10)
    ax.set_ylabel("bytes per read (log)", color=MUTED, fontsize=10)
    ax.set_title(title, color=INK, fontsize=12, fontweight="600", pad=10)
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{x:,}" for x in xs], fontsize=9)
    ax.grid(True, which="major", color=GRID, lw=0.8)
    ax.tick_params(colors=MUTED)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)

    # Selective direct label: the saved % at one representative point.
    if annotate_pct_at is not None:
        p = next(p for p in points if p[xkey] == annotate_pct_at)
        ax.annotate(
            f"saved {p['wire']['saved_pct']:.0f}%",
            xy=(p[xkey], p["wire"]["without_embedding_bytes"]),
            xytext=(0, -28),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            fontweight="600",
            color=WITHOUT,
        )

    # Real operating points (get / recall / list) as recessive guides.
    if marks:
        top = max(yw)
        for x, label in marks:
            ax.axvline(x, color=GRID, lw=1, ls=":", zorder=0)
            ax.text(x, top * 1.25, label, ha="center", fontsize=8, color=MUTED)

    ax.legend(frameon=False, fontsize=9, loc=legend_loc)


def figure(sw: dict):
    meta = sw["meta"]
    fig, (axa, axb) = plt.subplots(1, 2, figsize=(11, 4.6))
    fig.patch.set_facecolor("white")

    _panel(
        axa,
        sw["content_sweep"],
        "content_chars",
        "content chars per row",
        f"A · transfer vs content size (rows={meta['a_rows']})",
        annotate_pct_at=500,
    )
    _panel(
        axb,
        sw["rows_sweep"],
        "rows",
        "rows returned per read",
        f"B · transfer vs result size (content={meta['b_content']} chars)",
        marks=[
            (1, "get"),
            (meta["recall_limit"], "recall"),
            (meta["list_limit"], "list"),
        ],
        legend_loc="lower right",
    )
    fig.suptitle(
        f"Read payload: what the {meta['dim']}-dim embedding column costs "
        "(EXPLAIN SERIALIZE, text wire format)",
        fontsize=13,
        fontweight="700",
        color=INK,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig


def markdown(sw: dict) -> str:
    meta = sw["meta"]
    lines = [
        f"## Read-payload sweeps — {meta['dim']}-dim embedding, real pgvector",
        "",
        "_transfer measured with PG17 `EXPLAIN (SERIALIZE)`; text is the "
        "headline wire format, binary shown for reference._",
        "",
        f"### A · transfer vs content size (rows = {meta['a_rows']})",
        "",
        "| content chars | with embedding | without (#89) "
        "| saved (text) | saved (binary) |",
        "|--:|--:|--:|--:|--:|",
    ]
    for m in sw["content_sweep"]:
        w, b = m["wire"], m["wire_binary"]
        lines.append(
            f"| {m['content_chars']:,} | {_kb(w['with_embedding_bytes'])} | "
            f"{_kb(w['without_embedding_bytes'])} | {w['saved_pct']:.0f}% | "
            f"{b['saved_pct']:.0f}% |"
        )
    lines += [
        "",
        f"### B · transfer vs result size (content = {meta['b_content']} chars)",
        "",
        "| rows | with embedding | without (#89) "
        "| saved (text) | saved (binary) |",
        "|--:|--:|--:|--:|--:|",
    ]
    for m in sw["rows_sweep"]:
        w, b = m["wire"], m["wire_binary"]
        lines.append(
            f"| {m['rows']:,} | {_kb(w['with_embedding_bytes'])} | "
            f"{_kb(w['without_embedding_bytes'])} | {_kb(w['saved_bytes'])} | "
            f"{b['saved_pct']:.0f}% |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot #96 sweep JSON")
    ap.add_argument("json_path", help="sweep JSON from measure_read_payload.py --sweep")
    ap.add_argument("--png", help="write the figure PNG here")
    args = ap.parse_args()

    with open(args.json_path) as f:
        sw = json.load(f)

    print(markdown(sw))
    if args.png:
        fig = figure(sw)
        fig.savefig(args.png, dpi=150, bbox_inches="tight")
        print(f"\nwrote {args.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
