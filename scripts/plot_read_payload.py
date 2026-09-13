#!/usr/bin/env python
"""Plot the read-payload measurement (#89 / #96) from two measure_read_bytes runs.

    python scripts/measure_read_bytes.py --out before.json   # on main
    python scripts/measure_read_bytes.py --out after.json    # on the defer branch
    python scripts/plot_read_payload.py before.json after.json -o read-payload.png

Results live on the Performance wiki page, not in the repo — commit the PNG there
alongside the write-up: https://github.com/PCBZ/polymnemo/wiki/Performance

A dumbbell on a log x-axis, deliberately: the payloads span ~600x (144 B to
85 kB), so a linear axis flattens every single-row case into an invisible sliver
— and those are the cases with the highest embedding share. On a log axis a
constant ratio is a constant gap, which is exactly the claim being made.

Needs matplotlib.
"""

from __future__ import annotations

import argparse
import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

BLUE, ORANGE, GRAY, INK = "#2a78d6", "#eb6834", "#c3c2b7", "#52514e"


def load(path: str) -> dict[tuple[str, int], dict]:
    with open(path) as f:
        return {(r["op"], r["fanout"]): r for r in json.load(f)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot the read-payload measurement")
    ap.add_argument("before", help="measure_read_bytes JSON from main")
    ap.add_argument("after", help="measure_read_bytes JSON from the defer branch")
    ap.add_argument("-o", "--out", default="read-payload.png")
    args = ap.parse_args()

    before, after = load(args.before), load(args.after)
    keys = [k for k in before if k in after]
    if not keys:
        print("error: the two runs share no (op, fanout) cases", file=sys.stderr)
        return 2

    # Label by rows actually returned, not the requested fan-out — `session`
    # asks for a session, not a count, so its fan-out column is not a row count.
    # Plot top-down in file order; matplotlib's y-axis counts up from the bottom.
    rows = [
        (
            f"{op} {before[(op, n)].get('rows', n)}",
            before[(op, n)]["bytes"],
            after[(op, n)]["bytes"],
        )
        for op, n in keys
    ][::-1]
    y = range(len(rows))

    fig, ax = plt.subplots(figsize=(8.5, 0.42 * len(rows) + 1.9))
    for i, (_, b, a) in zip(y, rows, strict=True):
        ax.plot([a, b], [i, i], color=GRAY, lw=2, zorder=1, solid_capstyle="round")
        ax.annotate(
            f"-{(b - a) / b * 100:.0f}%",
            (b, i),
            xytext=(9, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK,
        )
    ax.scatter([r[2] for r in rows], y, s=70, color=ORANGE, zorder=3, label="deferred")
    ax.scatter([r[1] for r in rows], y, s=70, color=BLUE, zorder=3, label="fetched")

    tb, ta = sum(r[1] for r in rows), sum(r[2] for r in rows)
    ax.set_xscale("log")
    ax.set_xlim(min(r[2] for r in rows) * 0.55, max(r[1] for r in rows) * 4.5)
    ax.set_yticks(list(y))
    ax.set_yticklabels([r[0] for r in rows], fontsize=10)
    ax.set_xlabel("bytes returned per read  (log scale)", fontsize=10)
    ax.set_title(
        f"Read payload: {tb:,} B -> {ta:,} B  (-{(tb - ta) / tb * 100:.1f}%)",
        fontsize=12,
        loc="left",
        pad=12,
    )
    ax.legend(frameon=False, loc="lower right", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRAY)
    ax.grid(axis="x", color="#e1e0d9", lw=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK, labelsize=9)

    fig.tight_layout()
    fig.savefig(args.out, dpi=160, facecolor="white")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
