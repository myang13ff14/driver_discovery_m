"""Icicle chart of the L1 -> L2 -> L3 hierarchy; box height = number of requests."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb

HERE = Path(__file__).parent
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
NOISE, TEXT, SURFACE = "#d6d5d0", "#1f1f1e", "#ffffff"
COLS = [("L1", 0.0, 1.6), ("L2", 1.65, 2.3), ("L3", 4.0, 3.6)]  # (level, x, width)


def tint(hex_color, amount):
    """Mix a color toward white; amount 0 = original, 1 = white."""
    r, g, b = to_rgb(hex_color)
    return (r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount)


def box(ax, x, w, y, h, color, label, size, total, fontsize):
    # 1px surface gap between stacked boxes
    ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=color, edgecolor=SURFACE, linewidth=0.6))
    text = f"{label}  {size} ({size / total:.1%})"
    ax.text(x + 0.04, y + h / 2, text, va="center", ha="left", fontsize=fontsize, color=TEXT,
            clip_on=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=HERE / "result/hierarchy.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    d = json.loads(Path(args.input).read_text(encoding="utf-8"))
    total, noise = d["n_requests"], d["unclustered"]
    l2 = {p["id"]: p for p in d["L2"]}
    l3 = {c["id"]: c for c in d["L3"]}

    fig, ax = plt.subplots(figsize=(14, 26), dpi=200)
    y = total  # draw top-down
    for color, g in zip(SERIES, d["L1"]):
        box(ax, COLS[0][1], COLS[0][2], y - g["size"], g["size"], tint(color, 0.25),
            g["name"], g["size"], total, 9)
        y2 = y
        for pid in g["children"]:
            p = l2[pid]
            box(ax, COLS[1][1], COLS[1][2], y2 - p["size"], p["size"], tint(color, 0.55),
                p["name"], p["size"], total, 6.5)
            y3 = y2
            for cid in p["children"]:
                c = l3[cid]
                box(ax, COLS[2][1], COLS[2][2], y3 - c["size"], c["size"], tint(color, 0.8),
                    c["name"], c["size"], total, 4.6)
                y3 -= c["size"]
            y2 -= p["size"]
        y -= g["size"]
    # unclustered requests, so the chart accounts for every request
    for _, x, w in COLS:
        ax.add_patch(plt.Rectangle((x, 0), w, noise, facecolor=NOISE, edgecolor=SURFACE, lw=0.6))
    ax.text(COLS[0][1] + 0.04, noise / 2, f"Unclustered  {noise} ({noise / total:.1%})",
            va="center", fontsize=9, color=TEXT)

    for name, x, w in COLS:
        ax.text(x + 0.04, total + 8, name, fontsize=11, weight="bold", color=TEXT, va="bottom")
    ax.set_xlim(0, COLS[2][1] + COLS[2][2])
    ax.set_ylim(0, total + 30)
    ax.axis("off")
    ax.set_title(f"Call-driver hierarchy: {total} requests, {len(d['L1'])} L1, "
                 f"{len(d['L2'])} L2, {len(d['L3'])} L3 (box height = requests)",
                 loc="left", fontsize=13, color=TEXT)
    fig.tight_layout()
    out = Path(args.out or Path(args.input).with_suffix(".png"))
    fig.savefig(out, bbox_inches="tight", facecolor=SURFACE)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
