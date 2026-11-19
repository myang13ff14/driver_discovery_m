"""Recluster only where the review changed something: inside the parent of each edited category.

Run: .venv/bin/python supervised/recluster.py [--input feedback/result] [--out supervised/result]
                                              [--base unsupervised/step5_hierarchy/result/hierarchy.json]

The reviewed hierarchy.json is compared with --base (what the review started from), by ID:
  - a driver (L3) added or removed (merged counts as removed) -> its topic (L2) is reclustered:
    that topic's requests are re-sorted among that topic's drivers;
  - a topic (L2) added or removed -> its area (L1) is reclustered: that area's requests among its drivers;
  - an area (L1) added or removed -> everything is reclustered.
If the parent was removed as well, the scope moves one level up. Renames, description edits and moves
change no scope (a moved category takes its requests with it). Requests outside every scope keep the
driver the review gave them. Requests never clustered are sorted across the whole taxonomy.

Re-sorting = nearest driver centre (cosine between step 2 request embeddings and each driver's mean
request embedding; a driver added in review has no requests, so its embedded "name: description").
A request without a reviewed driver is left for review if even its best match is weak.

Writes hierarchy.json and labels.json in step 5's format, and recluster_report.json.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "feedback"))
import step5_format  # noqa: E402

STAGE = ROOT / "unsupervised"
EMBEDDINGS = STAGE / "step2_clustering/result/clusters_request.npz"
EXTRACTIONS = STAGE / "step1_extraction/result/extractions.json"
LABEL = {"L1": "area", "L2": "topic", "L3": "driver"}


def embeddings_by_request():
    """{(genuuid, request_idx): unit vector}, from step 2's stored embeddings (row order = extractions)."""
    d = np.load(EMBEDDINGS)
    calls = json.loads(EXTRACTIONS.read_text(encoding="utf-8"))["calls"]
    keys = [(c["genuuid"], i, r["request"]) for c in calls for i, r in enumerate(c["requests"])]
    if len(keys) != len(d["embeddings"]) or any(t != d["texts"][i] for i, (_, _, t) in enumerate(keys)):
        sys.exit("step 2's embeddings don't line up with step 1's extractions; rerun step 2")
    return {(g, i): v for (g, i, _), v in zip(keys, d["embeddings"])}


class Tree:
    """A hierarchy.json: names, and each category's parent."""

    def __init__(self, h):
        self.h = h
        self.ids = {lv: {c["id"] for c in h[lv]} for lv in ("L1", "L2", "L3")}
        self.name = {lv: {c["id"]: c["name"] for c in h[lv]} for lv in ("L1", "L2", "L3")}
        self.parent = {("L2", c): p["id"] for p in h["L1"] for c in p["children"]}
        self.parent.update({("L3", c): p["id"] for p in h["L2"] for c in p["children"]})

    def area_of_driver(self, d):
        return self.parent[("L2", self.parent[("L3", d)])]


def scopes_from_edits(base, rev):
    """Compare by ID -> (scopes, edits). A scope is ("L2", id), ("L1", id) or ("all",)."""
    scopes, edits = set(), []

    def scope_for(level, cid, tree):  # the parent of an edited category, in the tree where it lives
        if level == "L1":
            return ("all",)
        p = tree.parent[(level, cid)]
        up = "L1" if level == "L2" else "L2"
        if p in rev.ids[up]:
            return (up, p)
        return scope_for(up, p, base)  # the parent is gone too: one level up

    for lv in ("L1", "L2", "L3"):
        for cid in rev.ids[lv] - base.ids[lv]:
            s = scope_for(lv, cid, rev)
            scopes.add(s)
            edits.append({"edit": "added", "level": lv, "name": rev.name[lv][cid], "scope": s})
        for cid in base.ids[lv] - rev.ids[lv]:
            s = scope_for(lv, cid, base)
            scopes.add(s)
            edits.append({"edit": "removed or merged", "level": lv, "name": base.name[lv][cid], "scope": s})
    if ("all",) in scopes:
        return {("all",)}, edits
    areas = {s[1] for s in scopes if s[0] == "L1"}
    return {s for s in scopes if s[0] == "L1" or rev.parent[("L2", s[1])] not in areas}, edits


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default=ROOT / "feedback/result", help="folder with the reviewed hierarchy.json + labels.json")
    ap.add_argument("--base", default=step5_format.HIERARCHY, help="the hierarchy.json the review started from")
    ap.add_argument("--out", default=HERE / "result")
    ap.add_argument("--percentile", type=float, default=5,
                    help="a request without a reviewed driver needs review if its best match is below this "
                         "percentile of reviewed requests' similarity to their own driver")
    args = ap.parse_args()

    h = json.loads((Path(args.input) / "hierarchy.json").read_text(encoding="utf-8"))
    labels = json.loads((Path(args.input) / "labels.json").read_text(encoding="utf-8"))
    rev, base = Tree(h), Tree(json.loads(Path(args.base).read_text(encoding="utf-8")))
    requests = step5_format.load_requests()
    cluster_of = {(r["genuuid"], r["request_idx"]): r["cluster"] for r in requests}
    vec = embeddings_by_request()
    l3 = {c["id"]: c for c in h["L3"]}
    path = lambda d: (rev.name["L1"][rev.area_of_driver(d)], rev.name["L2"][rev.parent[("L3", d)]], rev.name["L3"][d])

    # the review's driver for each request (driver names can repeat; the step 2 cluster settles it)
    ids_by_name = defaultdict(list)
    for c in h["L3"]:
        ids_by_name[(rev.name["L2"][rev.parent[("L3", c["id"])]], c["name"])].append(c["id"])
    reviewed, text = {}, {}
    for r in labels:
        k = (r["genuuid"], r["request_idx"])
        text[k] = r["request"]
        if r["L3"]:
            ids = ids_by_name[(r["L2"], r["L3"])]
            reviewed[k] = cluster_of[k] if cluster_of[k] in ids else ids[0]

    # driver centres
    members = defaultdict(list)
    for k, d in reviewed.items():
        members[d].append(vec[k])
    centre = {d: (lambda m: m / np.linalg.norm(m))(np.mean(v, axis=0)) for d, v in members.items()}
    added = [d for d in l3 if d not in centre]
    if added:  # drivers with no requests: use their description, embedded like the requests
        from sentence_transformers import SentenceTransformer
        enc = SentenceTransformer(json.loads(step5_format.CLUSTERS.read_text(encoding="utf-8"))["model"])
        for d, v in zip(added, enc.encode([f"{l3[d]['name']}: {l3[d]['description']}" for d in added],
                                          normalize_embeddings=True)):
            centre[d] = v
    floor = float(np.percentile([vec[k] @ centre[d] for k, d in reviewed.items()], args.percentile))

    # which requests are reclustered, and among which drivers
    scopes, edits = scopes_from_edits(base, rev)

    def in_scope(scope, driver, tree):
        if scope == ("all",):
            return True
        lv, cid = scope
        return (tree.parent[("L3", driver)] == cid) if lv == "L2" else (tree.area_of_driver(driver) == cid)

    work = []  # (request keys, candidate drivers, scope)
    for s in sorted(scopes):
        drivers = [d for d in l3 if in_scope(s, d, rev)]
        keys = [k for k, d in reviewed.items() if d in drivers]
        keys += [k for k in text if k not in reviewed and cluster_of[k] in base.ids["L3"]
                 and in_scope(s, cluster_of[k], base)]  # requests of drivers removed inside this scope
        work.append((keys, drivers, s))
    taken = {k for keys, _, _ in work for k in keys}
    work.append(([k for k in text if cluster_of[k] == -1 and k not in taken], list(l3), "never clustered"))

    driver_of = dict(reviewed)
    changed, review = [], []
    for keys, drivers, s in work:
        ids = sorted(d for d in drivers if d in centre)
        if not ids or not keys:
            continue
        C = np.stack([centre[d] for d in ids])
        for k in keys:
            sims = C @ vec[k]
            d, sim = ids[int(np.argmax(sims))], float(sims.max())
            before = reviewed.get(k)
            if before is None and sim < floor:
                review.append({"genuuid": k[0], "request_idx": k[1], "request": text[k], "closest": l3[d]["name"],
                               "similarity": round(sim, 3), "scope": scope_name(s, rev)})
                continue
            driver_of[k] = d
            if before != d:
                old = path(before) if before is not None else (None, None, None)
                new = path(d)
                changed.append({"genuuid": k[0], "request_idx": k[1], "request": text[k], "similarity": round(sim, 3),
                                "scope": scope_name(s, rev),
                                "levels_changed": [lv for lv, a, b in zip(("L1", "L2", "L3"), old, new) if a != b],
                                "before": dict(zip(("L1", "L2", "L3"), old)), "after": dict(zip(("L1", "L2", "L3"), new))})

    # guard: requests outside every scope keep the review's driver
    if any(driver_of[k] != d for k, d in reviewed.items() if k not in taken):
        sys.exit("internal error: a request outside the reclustered scopes changed driver")

    # write in step 5's format
    live = {}
    for lv in ("L1", "L2", "L3"):
        for c in h[lv]:
            parent = None if lv == "L1" else f"{'L1' if lv == 'L2' else 'L2'}-{rev.parent[(lv, c['id'])]}"
            live[f"{lv}-{c['id']}"] = {"level": lv, "name": c["name"], "description": c["description"],
                                       "parent": parent, "coherence": c.get("coherence")}
    assign = {r["key"]: f"L3-{driver_of[(r['genuuid'], r['request_idx'])]}"
              if (r["genuuid"], r["request_idx"]) in driver_of else None for r in requests}
    had = [c for c in changed if c["before"]["L3"]]
    summary = {
        "scopes": [scope_name(s, rev) for s in sorted(scopes)],
        "edits": [{**e, "scope": scope_name(e["scope"], rev)} for e in edits],
        "requests_reclustered": len(taken), "untouched": sum(1 for k in reviewed if k not in taken),
        "changed_vs_review": {lv: sum(lv in c["levels_changed"] for c in had) for lv in ("L1", "L2", "L3")},
        "newly_placed": len(changed) - len(had), "needs_review": len(review),
        "similarity_floor": round(floor, 3), "added_drivers": [l3[d]["name"] for d in added],
    }
    out = Path(args.out)
    step5_format.write(live, assign, requests, out, f"{h['method']} + recluster",
                       {**h.get("review", {}), "recluster": summary})
    report = {**summary,
              "changed_requests": sorted(changed, key=lambda c: (-len(c["levels_changed"]), c["similarity"])),
              "needs_review_requests": sorted(review, key=lambda c: c["similarity"])}
    (out / "recluster_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    print("edits found (compared with the base):")
    for e in summary["edits"] or [{"edit": "none"}]:
        print(f"  {e['edit']} {LABEL.get(e.get('level'), '')} “{e.get('name', '')}” -> recluster {e.get('scope', '')}"
              if e["edit"] != "none" else "  none")
    print(f"reclustered: {len(taken)} requests in {len(scopes)} scope(s); untouched: {summary['untouched']}")
    ch = summary["changed_vs_review"]
    print(f"changed vs. review: driver (L3) {ch['L3']}, topic (L2) {ch['L2']}, area (L1) {ch['L1']}")
    print(f"without a driver before: {summary['newly_placed']} placed, {len(review)} need review (best match below {floor:.3f})")
    print(f"-> {out / 'hierarchy.json'}, {out / 'labels.json'}, {out / 'recluster_report.json'}")


def scope_name(s, rev):
    if s in (("all",), "all"):
        return "everything"
    if isinstance(s, str):
        return s
    return f"{LABEL[s[0]]} “{rev.name[s[0]][s[1]]}”"


if __name__ == "__main__":
    main()
