"""Cluster extracted requests: all-mpnet-base-v2 embeddings + iterative OPTICS (ChatMap §3.3).

Each round runs OPTICS only on points not yet assigned to a cluster, with a
smaller min_samples than the round before, until `--coverage` of points are
assigned or min_samples reaches its floor. Points left over are noise (-1).
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import OPTICS

HERE = Path(__file__).parent
ROOT = HERE.parents[1]  # project root: .env, data/
STAGE = HERE.parent    # unsupervised/
DEFAULT_IN = STAGE / "step1_extraction/result/extractions.json"


def load_requests(path):
    """Flatten calls into one row per request."""
    calls = json.loads(Path(path).read_text(encoding="utf-8"))["calls"]
    rows = []
    for call in calls:
        for i, r in enumerate(call["requests"]):
            rows.append({
                "genuuid": call["genuuid"],
                "product": call["product"],
                "request_idx": i,
                **r,
            })
    return rows


def embed_text(row, mode):
    if mode == "pair":
        return f"{row['request']} {row['solution']}"
    return row[mode]  # "request" or "category"


def iterative_optics(X, coverage, min_samples, min_floor, xi, metric="cosine"):
    labels = np.full(len(X), -1)
    next_id = 0
    rounds = []
    ms = min_samples
    while ms >= min_floor:
        todo = np.where(labels == -1)[0]
        if len(todo) < ms:
            break
        sub = OPTICS(min_samples=ms, metric=metric, xi=xi).fit(X[todo]).labels_
        found = sorted(set(sub) - {-1})
        for c in found:
            labels[todo[sub == c]] = next_id
            next_id += 1
        cov = float((labels != -1).mean())
        rounds.append({"min_samples": ms, "new_clusters": len(found), "coverage": round(cov, 3)})
        if cov >= coverage:
            break
        ms -= 1
    return labels, rounds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_IN)
    ap.add_argument("--embed", choices=["category", "request", "pair"], default="request",
                    help="category: driver area; request: specific issue; "
                         "pair: request+solution as in ChatMap")
    ap.add_argument("--model", default="sentence-transformers/all-mpnet-base-v2")
    ap.add_argument("--coverage", type=float, default=0.8)
    ap.add_argument("--min-samples", type=int, default=5, help="first-round OPTICS min_samples")
    ap.add_argument("--min-floor", type=int, default=2, help="lowest min_samples to relax to")
    ap.add_argument("--xi", type=float, default=0.05)
    ap.add_argument("--umap-dims", type=int, default=10,
                    help="reduce embeddings with UMAP (cosine) before OPTICS; 0 = off")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = load_requests(args.input)
    texts = [embed_text(r, args.embed) for r in rows]
    # symmetric model, no query prefix: clustering compares requests with each other
    model = SentenceTransformer(args.model)
    X = model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)

    if args.umap_dims:
        import umap
        Z = umap.UMAP(n_components=args.umap_dims, n_neighbors=15, min_dist=0.0,
                      metric="cosine", random_state=0).fit_transform(X)
        labels, rounds = iterative_optics(Z, args.coverage, args.min_samples, args.min_floor,
                                          args.xi, metric="euclidean")
    else:
        labels, rounds = iterative_optics(X, args.coverage, args.min_samples, args.min_floor, args.xi)

    clusters = {}
    for row, lab in zip(rows, labels):
        clusters.setdefault(int(lab), []).append(row)
    summary = []
    for lab, members in sorted(clusters.items(), key=lambda kv: (kv[0] == -1, -len(kv[1]))):
        summary.append({
            "cluster": lab,
            "size": len(members),
            "primary": sum(m["is_primary"] for m in members),
            "outcomes": dict(Counter(m["outcome"] for m in members)),
            "members": members,
        })

    out = Path(args.out or HERE / f"result/clusters_{args.embed}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "input": str(args.input), "embed": args.embed, "model": args.model,
        "umap_dims": args.umap_dims,
        "n_requests": len(rows), "rounds": rounds, "clusters": summary,
    }, indent=1), encoding="utf-8")
    # row-aligned arrays for plotting (the JSON above is grouped by cluster)
    np.savez(out.with_suffix(".npz"), embeddings=X, labels=labels, texts=np.array(texts))

    n_clusters = len(set(labels) - {-1})
    print(f"{len(rows)} requests -> {n_clusters} clusters, coverage {(labels != -1).mean():.0%} -> {out}")
    for r in rounds:
        print("  round", r)
    for c in summary:
        name = "NOISE" if c["cluster"] == -1 else f"C{c['cluster']}"
        print(f"\n{name} (n={c['size']}, primary={c['primary']}) {c['outcomes']}")
        for m in c["members"][:8]:
            print("   -", m["request"])


if __name__ == "__main__":
    main()
