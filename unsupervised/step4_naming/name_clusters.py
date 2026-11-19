"""Name step 2's fine clusters with an LLM, a few neighbouring clusters per call (L3 labels)."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from scipy.cluster.hierarchy import leaves_list, linkage

HERE = Path(__file__).parent
ROOT = HERE.parents[1]  # project root: .env, data/
STAGE = HERE.parent    # unsupervised/
PROMPT = (HERE / "naming_prompt.md").read_text(encoding="utf-8")
DEFAULT_IN = STAGE / "step2_clustering/result/clusters_request.json"


def load_clusters(path):
    """Clusters (noise excluded) with their BGE centroid and requests ordered most-central first."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    arr = np.load(path.with_suffix(".npz"))
    X, labels = arr["embeddings"], arr["labels"]
    clusters = []
    for c in data["clusters"]:
        if c["cluster"] == -1:
            continue
        E = X[labels == c["cluster"]]
        centroid = E.mean(0)
        order = np.argsort(-(E @ centroid))
        # npz rows and JSON members are both in extraction order within a cluster;
        # pair-mode clusters were formed on request + solution, so show both
        if data.get("embed") == "pair":
            requests = [f"{c['members'][i]['request']} -> agent: {c['members'][i]['solution']}"
                        for i in order]
        else:
            requests = [c["members"][i]["request"] for i in order]
        clusters.append({"id": c["cluster"], "size": c["size"], "centroid": centroid,
                         "requests": requests})
    return clusters


def neighbour_batches(clusters, size):
    """Batches of clusters adjacent in a hierarchical ordering of their centroids."""
    C = np.stack([c["centroid"] for c in clusters])
    order = leaves_list(linkage(C, method="average", metric="cosine"))
    ordered = [clusters[i] for i in order]
    return [ordered[i:i + size] for i in range(0, len(ordered), size)]


def format_cluster(c, n_show):
    shown = c["requests"][:n_show]
    lines = [f"## Cluster id {c['id']} ({c['size']} requests, showing {len(shown)}, most typical first)"]
    lines += [f"- {r}" for r in shown]
    return "\n".join(lines)


def name_batch(client, model, batch, n_show):
    prompt = (PROMPT.replace("{n}", str(len(batch)))
                    .replace("{clusters}", "\n\n".join(format_cluster(c, n_show) for c in batch)))
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"})
    named = {int(x["id"]): x for x in json.loads(resp.choices[0].message.content)["clusters"]}
    missing = [c["id"] for c in batch if c["id"] not in named]
    if missing:
        raise ValueError(f"model skipped cluster ids {missing}")
    return [{"cluster": c["id"], "size": c["size"], **{k: named[c["id"]][k]
             for k in ("name", "description", "coherence")}, "examples": c["requests"][:5]}
            for c in batch]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_IN)
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--batch", type=int, default=5, help="clusters per LLM call")
    ap.add_argument("--show", type=int, default=20, help="requests shown per cluster")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=HERE / "result/cluster_names.json")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    client = OpenAI()
    batches = neighbour_batches(load_clusters(args.input), args.batch)
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda b: name_batch(client, args.model, b, args.show), batches))
    named = sorted((c for batch in results for c in batch), key=lambda c: -c["size"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": args.model, "input": str(args.input), "clusters": named},
                              indent=1), encoding="utf-8")
    coh = {k: sum(c["coherence"] == k for c in named) for k in ("high", "medium", "low")}
    print(f"{len(named)} clusters named in {len(batches)} calls -> {out}  coherence {coh}")
    for c in named:
        print(f"  C{c['cluster']:<4} n={c['size']:<3} [{c['coherence']:<6}] {c['name']}")


if __name__ == "__main__":
    main()
