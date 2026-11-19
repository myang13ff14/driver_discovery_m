"""Write a reviewed taxonomy as hierarchy.json + labels.json in exactly step 5's format.

Used by the review app (app.py) and the Excel import (from_excel.py), so anything that reads
step 5's output (the supervised step and the step 5 plots) can read the reviewed version.

Categories are keyed "L3-33" (step 5's level and ID) or "L3-new-<anything>" (added in review).
Step 5's integer IDs are kept; added categories get the next free ID at their level.
"""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
STAGE = ROOT / "unsupervised"
HIERARCHY = STAGE / "step5_hierarchy/result/hierarchy.json"
CLUSTERS = STAGE / "step2_clustering/result/clusters_request.json"
REFERENCE = STAGE / "step3_taxonomy/result/taxonomy.json"
LEVELS = ("L1", "L2", "L3")


def load_requests():
    """Every request with its step 2 cluster (-1 = not grouped), in step 5's label order."""
    out = []
    for cl in json.loads(CLUSTERS.read_text(encoding="utf-8"))["clusters"]:
        for m in cl["members"]:
            out.append({"key": f"{m['genuuid']}|{m['request_idx']}", "cluster": cl["cluster"], **m})
    return out


def write(live, assign, requests, out_dir, method, review):
    """live: {key: {level, name, description, parent, coherence}} for the categories that exist now.
    assign: {request key: L3 key or None}. review: extra notes stored under hierarchy["review"]."""
    src = json.loads(HIERARCHY.read_text(encoding="utf-8"))
    ids = {}
    for lv in LEVELS:
        kept = [int(k.split("-")[1]) for k in live if live[k]["level"] == lv and "-new-" not in k]
        nxt = 1 + max([c["id"] for c in src[lv]] + kept)
        for k in sorted(k for k in live if live[k]["level"] == lv):
            if "-new-" in k:
                ids[k], nxt = nxt, nxt + 1
            else:
                ids[k] = int(k.split("-")[1])
    size = {k: 0 for k in live}
    for l3 in assign.values():
        k = l3
        while k:  # count the request at its L3 and every ancestor
            size[k] += 1
            k = live[k]["parent"]
    # equal sizes keep step 5's order (its position in the level list, or among its parent's children)
    pos = {f"{lv}-{c['id']}": i for lv in LEVELS for i, c in enumerate(src[lv])}
    pos_child = {f"{below}-{ch}": i for lv, below in (("L1", "L2"), ("L2", "L3")) for c in src[lv]
                 for i, ch in enumerate(c["children"])}
    by_size = lambda keys: sorted(keys, key=lambda k: (-size[k], pos.get(k, 10**6), ids[k]))
    kids = {k: sorted((x for x in live if live[x]["parent"] == k),
                      key=lambda x: (-size[x], pos_child.get(x, 10**6), ids[x])) for k in live}

    # labels: one row per request, as step 5 writes them; null where the request is in no driver
    ref_map = json.loads(REFERENCE.read_text(encoding="utf-8"))["mapping"]
    labels, cat_by_l2, ref_by_l2 = [], {}, {}
    for r in requests:
        row = {k: r[k] for k in ("genuuid", "request_idx", "request", "category", "request_type",
                                 "is_primary", "outcome")}
        l3 = assign.get(r["key"])
        if l3 is None:
            row.update(L3=None, L2=None, L1=None)
        else:
            l2 = live[l3]["parent"]
            row.update(L3=live[l3]["name"], L2=live[l2]["name"], L1=live[live[l2]["parent"]]["name"])
            cat = r["category"].strip().lower()
            cat_by_l2.setdefault(l2, Counter())[cat] += 1
            ref_by_l2.setdefault(l2, Counter())[ref_map.get(cat, "?")] += 1
        labels.append(row)

    def validation(k):  # same check as step 5: agreement with the step 3 reference taxonomy
        if not cat_by_l2.get(k):
            return {"top_step1_categories": {}, "reference_category": None, "reference_agreement": None}
        ref_top, ref_n = ref_by_l2[k].most_common(1)[0]
        return {"top_step1_categories": dict(cat_by_l2[k].most_common(5)), "reference_category": ref_top,
                "reference_agreement": round(ref_n / sum(cat_by_l2[k].values()), 2)}

    level = lambda lv: by_size(k for k in live if live[k]["level"] == lv)
    node = lambda k: {"name": live[k]["name"], "description": live[k]["description"],
                      "children": [ids[x] for x in kids[k]], "id": ids[k], "size": size[k], "misfits": []}
    hierarchy = {
        "model": src["model"], "method": method,
        "n_requests": src["n_requests"], "unclustered": sum(r["L3"] is None for r in labels),
        "moves": src["moves"],
        "L1": [node(k) for k in level("L1")],
        "L2": [{**node(k), "validation": validation(k)} for k in level("L2")],
        "L3": [{"id": ids[k], "name": live[k]["name"], "description": live[k]["description"],
                "size": size[k], "coherence": live[k].get("coherence")} for k in level("L3")],
        "review": review,
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hierarchy.json").write_text(json.dumps(hierarchy, indent=1), encoding="utf-8")
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=1), encoding="utf-8")
    return hierarchy, ids
