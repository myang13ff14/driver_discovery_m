"""Merge step 4's named clusters bottom-up into L2 and L1 categories, then validate.

Each level is built one of two ways:
  llm  (default): the LLM reads every child's name, description and size, proposes
       parent categories (choosing how many) and assigns each child to one parent.
  ward: embed children's "name: description" with BGE, Ward-cluster them into a
       fixed number of groups, and have the LLM name each group and flag misfits.
Validation compares every L2 with step 1's free-text `category` and with the
top-down reference taxonomy from step 3.
"""

import argparse
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering

HERE = Path(__file__).parent
ROOT = HERE.parents[1]  # project root: .env, data/
STAGE = HERE.parent    # unsupervised/
PROMPT = (HERE / "parent_prompt.md").read_text(encoding="utf-8")
GROUP_PROMPT = (HERE / "group_prompt.md").read_text(encoding="utf-8")
NAMES = STAGE / "step4_naming/result/cluster_names.json"
CLUSTERS = STAGE / "step2_clustering/result/clusters_request.json"
REFERENCE = STAGE / "step3_taxonomy/result/taxonomy.json"

COUNT_HINTS = {
    "L2": "for a support-operations reporting level this is usually 12–25",
    "L1": "for an executive reporting level this is usually 3–6",
}

LEVELS = {
    "L2": ("L2, the product or service area used for operational reporting",
           "2–5 words naming the product or service area (e.g. \"Display\", \"Power & Charging\", "
           "\"Repair Case Follow-up\")."),
    "L1": ("L1, the top-level domain used for executive reporting",
           "1–3 words naming a broad domain."),
}


def group_children(children, k, encoder):
    """Ward clustering of children's name+description embeddings into k groups."""
    texts = [f"{c['name']}: {c['description']}" for c in children]
    E = encoder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    k = min(k, len(children))
    return AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(E)


def name_groups(client, model, level, groups, batch):
    """groups: {gid: [child, ...]} -> {gid: {name, description, misfits}}"""
    level_text, name_rule = LEVELS[level]
    ids = sorted(groups)

    def call(chunk):
        blocks = []
        for gid in chunk:
            kids = sorted(groups[gid], key=lambda c: -c["size"])
            lines = [f"## Group id {gid} ({sum(c['size'] for c in kids)} requests)"]
            lines += [f"- child id {c['id']} ({c['size']}): {c['name']}: {c['description']}"
                      for c in kids]
            blocks.append("\n".join(lines))
        prompt = (PROMPT.replace("{n}", str(len(chunk))).replace("{level}", level_text)
                        .replace("{name_rule}", name_rule).replace("{groups}", "\n\n".join(blocks)))
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"})
        got = {int(g["id"]): g for g in json.loads(resp.choices[0].message.content)["groups"]}
        missing = [g for g in chunk if g not in got]
        if missing:
            raise ValueError(f"{level}: model skipped group ids {missing}")
        return got

    chunks = [ids[i:i + batch] for i in range(0, len(ids), batch)]
    with ThreadPoolExecutor(8) as pool:
        named = {}
        for part in pool.map(call, chunks):
            named.update(part)
    return named


def reassign_misfits(client, model, level, parents, children):
    """Move each flagged misfit child to the parent the LLM picks from the full list."""
    by_id = {c["id"]: c for c in children}
    misfits = [(m, p["id"]) for p in parents for m in p["misfits"]]
    if not misfits:
        return []
    plist = "\n".join(f"- parent id {p['id']}: {p['name']}: {p['description']}" for p in parents)
    clist = "\n".join(f"- child id {m}: {by_id[m]['name']}: {by_id[m]['description']}"
                      for m, _ in misfits)
    prompt = (f"These {level} parent categories exist for Lenovo PC support call drivers:\n{plist}\n\n"
              f"Assign each child category below to the single parent it fits best.\n{clist}\n\n"
              'Return valid JSON only: {"assign": {"<child id>": <parent id>}}')
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"})
    assign = {int(k): int(v) for k, v in json.loads(resp.choices[0].message.content)["assign"].items()}
    pmap = {p["id"]: p for p in parents}
    moves = []
    for m, old in misfits:
        new = assign.get(m, old)
        if new not in pmap or new == old:
            continue
        pmap[old]["children"].remove(m)
        pmap[new]["children"].append(m)
        moves.append({"child": by_id[m]["name"], "from": pmap[old]["name"], "to": pmap[new]["name"]})
    for p in parents:
        p["children"].sort(key=lambda c: -by_id[c]["size"])
        p["size"] = sum(by_id[c]["size"] for c in p["children"])
        p["misfits"] = []
    return moves


def assign_missing(client, model, level, parents, children, ids):
    """Ask the LLM to place children the grouping call left out; returns {child id: parent index}."""
    by_id = {c["id"]: c for c in children}
    plist = "\n".join(f"- parent id {i}: {p['name']}: {p['description']}" for i, p in enumerate(parents))
    clist = "\n".join(f"- child id {i}: {by_id[i]['name']}: {by_id[i]['description']}" for i in ids)
    prompt = (f"These {level} parent categories exist for Lenovo PC support call drivers:\n{plist}\n\n"
              f"Assign each child category below to the single parent it fits best.\n{clist}\n\n"
              'Return valid JSON only: {"assign": {"<child id>": <parent id>}}')
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"})
    got = {int(k): int(v) for k, v in json.loads(resp.choices[0].message.content)["assign"].items()}
    return {k: v for k, v in got.items() if k in ids and 0 <= v < len(parents)}


def build_level_llm(children, level, client, model):
    """LLM proposes parents (its own count) and assigns every child to one of them."""
    _, name_rule = LEVELS[level]
    kids = sorted(children, key=lambda c: -c["size"])
    clist = "\n".join(f"- id {c['id']} ({c['size']}): {c['name']}: {c['description']}" for c in kids)
    prompt = (GROUP_PROMPT.replace("{level}", LEVELS[level][0]).replace("{n}", str(len(kids)))
                          .replace("{count_hint}", COUNT_HINTS[level])
                          .replace("{name_rule}", name_rule).replace("{children}", clist))
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"})
    proposed = json.loads(resp.choices[0].message.content)["parents"]

    by_id = {c["id"]: c for c in children}
    seen, parents = set(), []
    for p in proposed:
        mine = [int(i) for i in p["children"] if int(i) in by_id and int(i) not in seen]
        seen.update(mine)  # a child listed twice stays with its first parent
        parents.append({"name": p["name"], "description": p["description"], "children": mine})
    missing = [i for i in by_id if i not in seen]
    if missing:
        print(f"  {level}: {len(missing)} children left unassigned by grouping call; assigning")
        for cid, pi in assign_missing(client, model, level, parents, children, missing).items():
            parents[pi]["children"].append(cid)
    still = [i for i in by_id if not any(i in p["children"] for p in parents)]
    if still:
        raise ValueError(f"{level}: children never assigned: {still}")

    parents = [p for p in parents if p["children"]]
    for i, p in enumerate(parents):
        p["children"].sort(key=lambda c: -by_id[c]["size"])
        p.update(id=i, size=sum(by_id[c]["size"] for c in p["children"]), misfits=[])
    return sorted(parents, key=lambda p: -p["size"]), []


def build_level(children, k, level, client, model, encoder, batch):
    """Group children into k parents and name them. Children: dicts with id/name/description/size."""
    labels = group_children(children, k, encoder)
    groups = defaultdict(list)
    for child, g in zip(children, labels):
        groups[int(g)].append(child)
    named = name_groups(client, model, level, groups, batch)
    parents = []
    for gid, kids in groups.items():
        n = named[gid]
        parents.append({
            "id": gid, "name": n["name"], "description": n["description"],
            "size": sum(c["size"] for c in kids),
            "children": [c["id"] for c in sorted(kids, key=lambda c: -c["size"])],
            "misfits": [int(m) for m in n.get("misfits", []) if int(m) in {c["id"] for c in kids}],
        })
    moves = reassign_misfits(client, model, level, parents, children)
    for mv in moves:
        print(f"  {level} move: {mv['child']}  [{mv['from']} -> {mv['to']}]")
    parents = [p for p in parents if p["children"]]
    return sorted(parents, key=lambda p: -p["size"]), moves


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["llm", "ward"], default="llm",
                    help="llm: LLM proposes and assigns parents; ward: embedding clustering + LLM naming")
    ap.add_argument("--l2", type=int, default=20, help="ward only: number of L2 categories")
    ap.add_argument("--l1", type=int, default=5, help="ward only: number of L1 categories")
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--encoder", default="BAAI/bge-large-en-v1.5")
    ap.add_argument("--batch", type=int, default=5, help="groups named per LLM call")
    ap.add_argument("--names", default=NAMES, help="step 4 cluster names")
    ap.add_argument("--clusters", default=CLUSTERS, help="step 2 clusters (for per-request labels)")
    ap.add_argument("--out", default=HERE / "result/hierarchy.json")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    client = OpenAI()

    l3 = [{"id": c["cluster"], "name": c["name"], "description": c["description"],
           "size": c["size"], "coherence": c["coherence"]}
          for c in json.loads(Path(args.names).read_text(encoding="utf-8"))["clusters"]]
    if args.method == "llm":
        l2, moves2 = build_level_llm(l3, "L2", client, args.model)
        l1, moves1 = build_level_llm(l2, "L1", client, args.model)
    else:
        encoder = SentenceTransformer(args.encoder)
        l2, moves2 = build_level(l3, args.l2, "L2", client, args.model, encoder, args.batch)
        l1, moves1 = build_level(l2, args.l1, "L1", client, args.model, encoder, args.batch)

    # per-request labels
    l3_by_id = {c["id"]: c for c in l3}
    l2_of = {cid: p for p in l2 for cid in p["children"]}
    l1_of = {p["id"]: g for g in l1 for p in [x for x in l2 if x["id"] in g["children"]]}
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    ref_map = reference["mapping"]

    labels, cat_by_l2, ref_by_l2 = [], defaultdict(Counter), defaultdict(Counter)
    for c in json.loads(Path(args.clusters).read_text(encoding="utf-8"))["clusters"]:
        for m in c["members"]:
            row = {k: m[k] for k in ("genuuid", "request_idx", "request", "category",
                                     "request_type", "is_primary", "outcome")}
            if c["cluster"] == -1:
                row.update(L3=None, L2=None, L1=None)
            else:
                p2 = l2_of[c["cluster"]]
                row.update(L3=l3_by_id[c["cluster"]]["name"], L2=p2["name"],
                           L1=l1_of[p2["id"]]["name"])
                cat = m["category"].strip().lower()
                cat_by_l2[p2["name"]][cat] += 1
                ref_by_l2[p2["name"]][ref_map.get(cat, "?")] += 1
            labels.append(row)

    total = len(labels)
    for p in l2:
        n = sum(cat_by_l2[p["name"]].values())
        ref_top, ref_n = ref_by_l2[p["name"]].most_common(1)[0]
        p["validation"] = {
            "top_step1_categories": dict(cat_by_l2[p["name"]].most_common(5)),
            "reference_category": ref_top,
            "reference_agreement": round(ref_n / n, 2),
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": args.model, "method": args.method, "n_requests": total,
                               "unclustered": sum(r["L1"] is None for r in labels),
                               "moves": {"L2": moves2, "L1": moves1},
                               "L1": l1, "L2": l2, "L3": l3}, indent=1), encoding="utf-8")
    (out.parent / out.name.replace("hierarchy", "labels")).write_text(json.dumps(labels, indent=1), encoding="utf-8")
    write_markdown(l1, l2, l3_by_id, total, sum(r["L1"] is None for r in labels),
                   out.with_suffix(".md"))
    print(f"L1={len(l1)} L2={len(l2)} L3={len(l3)} -> {out} (+ .md, labels.json)")


def write_markdown(l1, l2, l3_by_id, total, unclustered, path):
    l2_by_id = {p["id"]: p for p in l2}
    lines = ["# Call-driver hierarchy (bottom-up)", "",
             f"{total} requests; {total - unclustered} clustered, {unclustered} unclustered (noise).",
             "Percentages are of all requests. `ref` = the step 3 top-down category most L2 requests map to, "
             "with the share that agrees.", ""]
    for g in l1:
        lines.append(f"## {g['name']} — {g['size']} ({g['size'] / total:.1%})")
        lines.append(f"_{g['description']}_")
        lines.append("")
        for pid in g["children"]:
            p = l2_by_id[pid]
            v = p["validation"]
            flag = " ⚠ misfit L2" if pid in g["misfits"] else ""
            lines.append(f"### {p['name']} — {p['size']} ({p['size'] / total:.1%}){flag}")
            lines.append(f"{p['description']}  ")
            lines.append(f"ref: {v['reference_category']} ({v['reference_agreement']:.0%}) · "
                         f"step 1 categories: " +
                         ", ".join(f"{k} ({n})" for k, n in v["top_step1_categories"].items()))
            lines.append("")
            for cid in p["children"]:
                c = l3_by_id[cid]
                mark = " ⚠ misfit" if cid in p["misfits"] else ""
                low = " (low coherence)" if c["coherence"] == "low" else ""
                lines.append(f"- {c['name']} — {c['size']}{low}{mark}")
            lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
