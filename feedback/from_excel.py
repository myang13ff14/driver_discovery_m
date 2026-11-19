"""Read an edited taxonomy sheet (from to_excel.py) back into step 5's format, for the supervised step.

Run: .venv/bin/python feedback/from_excel.py [--input feedback/excel/taxonomy.xlsx] [--out feedback/excel]
                                             [--base …/hierarchy.json]

Checks the sheet (levels, parents, names), prints what changed compared with --base (step 5 by default),
and writes hierarchy.json and labels.json. Nothing is written if the sheet has errors.

Requests keep the driver they were discovered in when that driver's row (ID) is still in the sheet;
requests of deleted drivers get null labels. The supervised step relabels everything against the new taxonomy.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

import step5_format

HERE = Path(__file__).parent
LEVELS = {"area": "L1", "topic": "L2", "driver": "L3"}
LABEL = {"L1": "area", "L2": "topic", "L3": "driver"}


def read_sheet(path):
    """-> (rows, errors, warnings); rows: {row, lv, name, description, parent, id}"""
    ws = load_workbook(path, data_only=True)["Taxonomy"]
    header = [str(c.value or "").strip() for c in ws[1]]
    missing = [h for h in ("Level", "Name", "Description", "Parent", "ID") if h not in header]
    if missing:
        return [], [f"the Taxonomy sheet is missing column(s): {', '.join(missing)}"], []
    col = {h: header.index(h) for h in header}
    rows, errors, warnings = [], [], []
    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        get = lambda h: str(r[col[h]]).strip() if col[h] < len(r) and r[col[h]] is not None else ""
        level, name, desc, parent, id_ = (get(h) for h in ("Level", "Name", "Description", "Parent", "ID"))
        if not (level or name or desc or parent):
            continue  # blank row
        lv = LEVELS.get(level.lower())
        if not lv:
            errors.append(f"row {i}: Level must be Area, Topic or Driver (got “{level}”)")
            continue
        if not name:
            errors.append(f"row {i}: {LABEL[lv]} has no name")
            continue
        try:
            id_ = int(float(id_)) if id_ else None
        except ValueError:
            warnings.append(f"row {i}: ID “{id_}” is not a number; treated as a new {LABEL[lv]}")
            id_ = None
        rows.append({"row": i, "lv": lv, "name": name, "description": desc, "parent": parent, "id": id_})

    # areas and topics are referred to by name, so their names must be unique
    for lv in ("L1", "L2"):
        for name, n in Counter(r["name"] for r in rows if r["lv"] == lv).items():
            if n > 1:
                errors.append(f"{n} {LABEL[lv]}s are named “{name}”; names of {LABEL[lv]}s must be unique")
    for (parent, name), n in Counter((r["parent"], r["name"]) for r in rows if r["lv"] == "L3").items():
        if n > 1:
            warnings.append(f"{n} drivers in “{parent}” are named “{name}”; consider merging or renaming them")
    names = {lv: {r["name"] for r in rows if r["lv"] == lv} for lv in ("L1", "L2")}
    for r in rows:
        if r["lv"] == "L1" and r["parent"]:
            warnings.append(f"row {r['row']}: an area has no parent; “{r['parent']}” is ignored")
        if r["lv"] == "L2" and r["parent"] not in names["L1"]:
            errors.append(f"row {r['row']}: topic “{r['name']}” has parent “{r['parent']}”, which is not an area in the sheet")
        if r["lv"] == "L3" and r["parent"] not in names["L2"]:
            errors.append(f"row {r['row']}: driver “{r['name']}” has parent “{r['parent']}”, which is not a topic in the sheet")
    for lv, below in (("L1", "L2"), ("L2", "L3")):
        for name in names[lv] - {r["parent"] for r in rows if r["lv"] == below}:
            warnings.append(f"{LABEL[lv]} “{name}” has no {LABEL[below]}s")
    return rows, errors, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default=HERE / "excel/taxonomy.xlsx")
    ap.add_argument("--out", default=HERE / "excel", help="where hierarchy.json and labels.json are written")
    ap.add_argument("--base", default=step5_format.HIERARCHY,
                    help="the hierarchy.json the sheet was made from (IDs and the change list refer to it)")
    args = ap.parse_args()

    rows, errors, warnings = read_sheet(args.input)
    for w in warnings:
        print("warning:", w)
    if errors:
        for e in errors:
            print("ERROR:", e)
        sys.exit(f"{len(errors)} error(s) in {args.input}; nothing written. Fix the sheet and run again.")

    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    base_by = {lv: {c["id"]: c for c in base[lv]} for lv in ("L1", "L2", "L3")}
    base_parent = {(below, ch): p["id"] for lv, below in (("L1", "L2"), ("L2", "L3"))
                   for p in base[lv] for ch in p["children"]}

    # key each row: its ID if it is a known, unused ID at that level; otherwise a new category
    used, key_of = set(), {}
    for r in rows:
        k = f"{r['lv']}-{r['id']}"
        if r["id"] is not None and r["id"] in base_by[r["lv"]] and k not in used:
            used.add(k)
        else:
            if r["id"] is not None:
                print(f"warning: row {r['row']}: ID {r['id']} is unknown or used twice; treated as a new {LABEL[r['lv']]}")
            k = f"{r['lv']}-new-{r['row']:05d}"
        key_of[r["row"]] = k
    by_name = {(r["lv"], r["name"]): key_of[r["row"]] for r in rows if r["lv"] != "L3"}
    up = {"L2": "L1", "L3": "L2"}
    live = {key_of[r["row"]]: {
        "level": r["lv"], "name": r["name"], "description": r["description"],
        "parent": by_name[(up[r["lv"]], r["parent"])] if r["lv"] != "L1" else None,
        "coherence": base_by["L3"][r["id"]].get("coherence") if r["lv"] == "L3" and "-new-" not in key_of[r["row"]] else None,
    } for r in rows}

    # what changed, compared with the base
    nm = lambda k: live[k]["name"]
    changes = {"added": [], "deleted": [], "renamed": [], "description_changed": [], "moved": []}
    for k, c in live.items():
        lv = c["level"]
        if "-new-" in k:
            changes["added"].append(f"{LABEL[lv]} “{c['name']}”")
            continue
        old = base_by[lv][int(k.split("-")[1])]
        if old["name"] != c["name"]:
            changes["renamed"].append(f"{LABEL[lv]} “{old['name']}” → “{c['name']}”")
        if old["description"] != c["description"]:
            changes["description_changed"].append(f"{LABEL[lv]} “{c['name']}”")
        if lv != "L1":
            was = base_parent.get((lv, old["id"]))
            now = c["parent"]
            if now != f"{up[lv]}-{was}":
                changes["moved"].append(f"{LABEL[lv]} “{c['name']}”: “{base_by[up[lv]][was]['name']}” → “{nm(now)}”")
    for lv in ("L1", "L2", "L3"):
        for i, old in base_by[lv].items():
            if f"{lv}-{i}" not in live:
                changes["deleted"].append(f"{LABEL[lv]} “{old['name']}” ({old['size']} requests)")

    requests = step5_format.load_requests()
    assign = {r["key"]: f"L3-{r['cluster']}" if f"L3-{r['cluster']}" in live else None for r in requests}
    review = {"source": str(args.input), **changes}
    h, _ = step5_format.write(live, assign, requests, args.out, "llm + human review (excel)", review)

    print(f"\n{len(h['L1'])} areas, {len(h['L2'])} topics, {len(h['L3'])} drivers; "
          f"{h['n_requests'] - h['unclustered']} of {h['n_requests']} requests carry a driver from the clustering")
    for what, items in changes.items():
        print(f"{what.replace('_', ' ')}: {len(items)}")
        for x in items[:20]:
            print("   ", x)
        if len(items) > 20:
            print(f"    … and {len(items) - 20} more")
    print(f"-> {Path(args.out) / 'hierarchy.json'}, {Path(args.out) / 'labels.json'}")


if __name__ == "__main__":
    main()
