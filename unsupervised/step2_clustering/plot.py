"""Scatter plot of clustering results: t-SNE of request embeddings, colored by cluster.

The 8 largest clusters get distinct colors and are labeled; other clusters are
mid-gray and noise (-1) is light gray, so color never has to carry 50+ identities.
"""

import argparse
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.manifold import TSNE

HERE = Path(__file__).parent
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER, NOISE, TEXT, MUTED = "#9a9a96", "#d6d5d0", "#1f1f1e", "#6b6a64"


def plot_all(X, xy, labels, texts, ids, args):
    """Every cluster colored, labeled by ID in the plot, and listed with its topic on the side.

    Same layout as the top-N plot (12x9 canvas, legend at right, sorted by size);
    the legend runs in 3 columns to fit 200+ entries. Colors repeat, so the ID is
    the identity and color only separates neighbouring clusters.
    """
    from adjustText import adjust_text

    # drop the gray swatches (tab20 14-15, tab20c 16-19) so no cluster reads as noise
    grays = {("tab20", 14), ("tab20", 15)} | {("tab20c", i) for i in range(16, 20)}
    cmap = [plt.get_cmap(n)(i) for n in ("tab20", "tab20b", "tab20c") for i in range(20)
            if (n, i) not in grays]
    order = np.random.default_rng(0).permutation(len(ids))  # adjacent IDs get unrelated hues
    color_of = {int(cid): cmap[order[k] % len(cmap)] for k, cid in enumerate(ids)}
    sizes = {int(cid): int((labels == cid).sum()) for cid in ids}
    by_size = sorted(sizes, key=lambda c: (-sizes[c], c))

    fig, ax = plt.subplots(figsize=(12, 9), dpi=300)
    noise = labels == -1
    ax.scatter(*xy[noise].T, s=14, c=NOISE, linewidths=0, label=f"Noise (n={noise.sum()})")
    annotations = []
    for cid in by_size:
        m = labels == cid
        central = np.argmax(X[m] @ X[m].mean(0))
        topic = textwrap.shorten(str(texts[m][central]), 46, placeholder="…")
        ax.scatter(*xy[m].T, s=28, color=color_of[cid], edgecolors="white", linewidths=0.8,
                   label=f"C{cid} (n={sizes[cid]}): {topic}")
        annotations.append(ax.text(*xy[m][central], f"C{cid}", fontsize=4.5, color=TEXT,
                                   weight="bold"))
    adjust_text(annotations, ax=ax, expand=(1.05, 1.2),
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.3))
    cov = (~noise).mean()
    ax.set_title(f"{len(X)} requests, {len(ids)} clusters, {cov:.0%} coverage (t-SNE of request embeddings)",
                 color=TEXT, loc="left", fontsize=12)
    ax.set_xticks([]), ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False, fontsize=4.6,
              ncol=3, columnspacing=1.0, handletextpad=0.2, labelspacing=0.35,
              markerscale=0.6, labelcolor=TEXT,
              title="All clusters by size (central example)", title_fontsize=9)
    fig.tight_layout()
    out = Path(args.out or Path(args.input).with_name(Path(args.input).stem + "_all.png"))
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"saved {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=HERE / "result/clusters_request.npz")
    ap.add_argument("--top", type=int, default=8, help="clusters to color (max 8)")
    ap.add_argument("--all", action="store_true",
                    help="color and label every cluster (colors repeat; use the IDs)")
    ap.add_argument("--perplexity", type=float, default=30)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    d = np.load(args.input)
    X, labels, texts = d["embeddings"], d["labels"], d["texts"]
    perp = min(args.perplexity, (len(X) - 1) / 3)
    xy = TSNE(n_components=2, metric="cosine", perplexity=perp, init="pca",
              random_state=0).fit_transform(X)

    ids, counts = np.unique(labels[labels != -1], return_counts=True)
    top = [int(i) for i in ids[np.argsort(-counts)][: min(args.top, len(SERIES))]]
    if args.all:
        plot_all(X, xy, labels, texts, ids, args)
        return

    fig, ax = plt.subplots(figsize=(12, 9), dpi=120)
    noise = labels == -1
    rest = ~noise & ~np.isin(labels, top)
    ax.scatter(*xy[noise].T, s=14, c=NOISE, linewidths=0, label=f"Noise (n={noise.sum()})")
    if rest.any():
        ax.scatter(*xy[rest].T, s=18, c=OTHER, linewidths=0,
                   label=f"Other clusters ({len(ids) - len(top)}, n={rest.sum()})")
    for color, cid in zip(SERIES, top):
        m = labels == cid
        # most central member serves as the cluster's example text
        centroid = X[m].mean(0)
        central = np.argmax(X[m] @ centroid)
        example = texts[m][central]
        ax.scatter(*xy[m].T, s=28, c=color, edgecolors="white", linewidths=0.8,
                   label=f"C{cid} (n={m.sum()}): " + textwrap.shorten(str(example), 50))
        # label sits on the central member, not the 2D mean, which can fall in empty space
        cx, cy = xy[m][central]
        ax.annotate(f"C{cid}", (cx, cy), xytext=(8, 8), textcoords="offset points",
                    color=TEXT, fontsize=10, weight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=color, lw=1))

    n_cl = len(ids)
    cov = (~noise).mean()
    ax.set_title(f"{len(X)} requests, {n_cl} clusters, {cov:.0%} coverage (t-SNE of request embeddings)",
                 color=TEXT, loc="left", fontsize=12)
    ax.set_xticks([]), ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False, fontsize=9,
              labelcolor=TEXT, title="Largest clusters (central example)", title_fontsize=9)
    fig.tight_layout()

    out = Path(args.out or Path(args.input).with_suffix(".png"))
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
