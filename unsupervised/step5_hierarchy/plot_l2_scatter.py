"""Step 2's t-SNE scatter of request embeddings, colored by step 5's L2 category.

Hue = L1 domain, shade = L2 within that domain; each L2 is also labeled on the
plot, so identity never depends on telling 20+ shades apart. Uses the same t-SNE
settings as step2_clustering/plot.py, so the layout matches clusters_request.png.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from adjustText import adjust_text
from matplotlib.colors import to_rgb
from matplotlib.lines import Line2D
from sklearn.manifold import TSNE

HERE = Path(__file__).parent
STAGE = HERE.parent    # unsupervised/
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6", "#008300", "#e34948"]
NOISE, TEXT, MUTED = "#d6d5d0", "#1f1f1e", "#6b6a64"


def shade(hex_color, amount):
    """amount < 0 darkens toward black, > 0 lightens toward white."""
    rgb = np.array(to_rgb(hex_color))
    return tuple(rgb * (1 + amount) if amount < 0 else rgb + (1 - rgb) * amount)


def request_keys(extractions):
    """(genuuid, request_idx) in the row order step 2 used for its embeddings."""
    calls = json.loads(Path(extractions).read_text(encoding="utf-8"))["calls"]
    return [(c["genuuid"], i) for c in calls for i, _ in enumerate(c["requests"])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embeddings", default=STAGE / "step2_clustering/result/clusters_request.npz")
    ap.add_argument("--extractions", default=STAGE / "step1_extraction/result/extractions.json")
    ap.add_argument("--hierarchy", default=HERE / "result/hierarchy.json")
    ap.add_argument("--labels", default=HERE / "result/labels.json")
    ap.add_argument("--perplexity", type=float, default=30)
    ap.add_argument("--out", default=HERE / "result/scatter_l2.png")
    args = ap.parse_args()

    arr = np.load(args.embeddings)
    X, texts = arr["embeddings"], arr["texts"]
    keys = request_keys(args.extractions)
    labels = {(r["genuuid"], r["request_idx"]): r for r in
              json.loads(Path(args.labels).read_text(encoding="utf-8"))}
    if len(keys) != len(X):
        raise ValueError(f"{len(keys)} requests in extractions vs {len(X)} embeddings")
    rows = [labels[k] for k in keys]
    bad = [i for i, r in enumerate(rows) if r["request"] != texts[i]]
    if bad:
        raise ValueError(f"row order mismatch between embeddings and labels at rows {bad[:5]}")

    H = json.loads(Path(args.hierarchy).read_text(encoding="utf-8"))
    l2_by_id = {p["id"]: p for p in H["L2"]}
    # L1 by size -> palette slot; L2s within an L1 spread from darker to lighter
    color_of, l1_of = {}, {}
    for slot, g in enumerate(H["L1"]):
        kids = [l2_by_id[c]["name"] for c in g["children"]]
        steps = np.linspace(-0.3, 0.45, len(kids)) if len(kids) > 1 else [0.0]
        for name, amt in zip(kids, steps):
            color_of[name] = shade(SERIES[slot % len(SERIES)], amt)
            l1_of[name] = g["name"]

    perp = min(args.perplexity, (len(X) - 1) / 3)
    xy = TSNE(n_components=2, metric="cosine", perplexity=perp, init="pca",
              random_state=0).fit_transform(X)

    l2 = np.array([r["L2"] or "" for r in rows])
    noise = l2 == ""
    fig, ax = plt.subplots(figsize=(12, 9), dpi=300)
    ax.scatter(*xy[noise].T, s=14, c=NOISE, linewidths=0)
    texts_on_plot = []
    for name in color_of:
        m = l2 == name
        if not m.any():  # a category added in review has no requests yet; it stays in the legend
            continue
        ax.scatter(*xy[m].T, s=28, color=color_of[name], edgecolors="white", linewidths=0.8)
        # label at the member nearest the 2D median, so it sits on real points
        med = np.median(xy[m], axis=0)
        anchor = xy[m][np.argmin(((xy[m] - med) ** 2).sum(1))]
        texts_on_plot.append(ax.text(*anchor, name, fontsize=5.5, color=TEXT, weight="bold",
                                     bbox=dict(boxstyle="round,pad=0.15", fc="white",
                                               ec=color_of[name], lw=0.6, alpha=0.9)))
    adjust_text(texts_on_plot, ax=ax, expand=(1.1, 1.3),
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.4))

    # legend grouped by L1: a bold header row, then its L2 rows with counts
    handles, names, headers = [], [], []
    by_l1 = defaultdict(list)
    for name in color_of:
        by_l1[l1_of[name]].append(name)
    for g in H["L1"]:
        headers.append(len(names))
        handles.append(Line2D([], [], linestyle="none"))
        names.append(f"{g['name']} ({g['size']})")
        for name in by_l1[g["name"]]:
            handles.append(Line2D([], [], marker="o", linestyle="none", markersize=5,
                                  markerfacecolor=color_of[name], markeredgecolor="white"))
            names.append(f"{name} ({int((l2 == name).sum())})")
    handles.append(Line2D([], [], marker="o", linestyle="none", markersize=5,
                          markerfacecolor=NOISE, markeredgecolor="white"))
    names.append(f"Unclustered ({int(noise.sum())})")
    leg = ax.legend(handles, names, loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False,
                    fontsize=7, labelcolor=TEXT, handletextpad=0.3, labelspacing=0.45)
    for i in headers:
        leg.get_texts()[i].set_fontweight("bold")

    ax.set_title(f"{len(X)} requests colored by L2 category ({len(H['L2'])} L2 in "
                 f"{len(H['L1'])} L1; t-SNE of request embeddings)", loc="left", fontsize=12, color=TEXT)
    ax.set_xticks([]), ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
