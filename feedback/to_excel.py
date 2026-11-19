"""Turn a taxonomy (step 5's hierarchy.json) into an Excel sheet a reviewer can edit freely.

Run: .venv/bin/python feedback/to_excel.py [--input …/hierarchy.json] [--out feedback/excel/taxonomy.xlsx]

One row per category (area, topic, driver) with its name, description and parent. Request counts and
example requests are included for reference only. Read the edited sheet back with from_excel.py.
"""

import argparse
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

import step5_format

HERE = Path(__file__).parent
DEFAULT_IN = HERE.parent / "unsupervised/step5_hierarchy/result/hierarchy.json"
LEVEL_NAME = {"L1": "Area", "L2": "Topic", "L3": "Driver"}
COLUMNS = [("Level", 10), ("Name", 46), ("Description", 80), ("Parent", 34),
           ("ID", 7), ("Requests", 10), ("Example requests (for reference)", 70)]
EDITABLE = 4  # Level, Name, Description, Parent; the rest is reference only

HOW_TO = [
    ("How to edit", ""),
    ("", "Edit the Taxonomy sheet freely. Only Level, Name, Description and Parent are read back."),
    ("Rename or redefine", "Change Name or Description."),
    ("Move", "Change Parent: a topic's parent is an area name; a driver's parent is a topic name (exact spelling)."),
    ("Add", "Insert a row anywhere. Fill Level (Area / Topic / Driver), Name, Description and Parent. Leave ID empty."),
    ("Delete", "Delete the row. Delete or move a topic's drivers too, or the import will report them."),
    ("Merge", "Delete one of the two rows and widen the other's description so it covers both."),
    ("Don't", "Don't change or copy the ID column: it links a category to the requests it was discovered from."),
    ("", ""),
    ("Then run", ".venv/bin/python feedback/from_excel.py  →  feedback/excel/hierarchy.json and labels.json"),
    ("", "The import checks the sheet and lists what changed. Requests and examples are refreshed by the next step."),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default=DEFAULT_IN, help="hierarchy.json in step 5's format")
    ap.add_argument("--out", default=HERE / "excel/taxonomy.xlsx")
    ap.add_argument("--examples", type=int, default=3, help="example requests per driver")
    args = ap.parse_args()

    h = json.loads(Path(args.input).read_text(encoding="utf-8"))
    by = {lv: {c["id"]: c for c in h[lv]} for lv in ("L1", "L2", "L3")}
    # examples by driver ID (= the step 2 cluster it came from), so drivers with the same name stay apart
    examples = {}
    for r in sorted(step5_format.load_requests(), key=lambda r: not r["is_primary"]):  # main request first
        examples.setdefault(r["cluster"], []).append(r["request"])

    wb = Workbook()
    ws = wb.active
    ws.title = "Taxonomy"
    ws.append([c for c, _ in COLUMNS])
    for i, (_, width) in enumerate(COLUMNS, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    grey = PatternFill("solid", fgColor="F2F2F2")
    head = PatternFill("solid", fgColor="D9E1F2")
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True), head

    def row(lv, c, parent, indent):
        ex = examples.get(c["id"], [])[:args.examples] if lv == "L3" else []
        ws.append([LEVEL_NAME[lv], c["name"], c["description"], parent or "", c["id"], c["size"],
                   "\n".join(f"• {e}" for e in ex)])
        r = ws.max_row
        for col in range(1, len(COLUMNS) + 1):
            ws.cell(r, col).alignment = Alignment(wrap_text=True, vertical="top", indent=indent if col == 2 else 0)
            if col > EDITABLE:
                ws.cell(r, col).fill = grey
        if lv != "L3":
            for col in (1, 2):
                ws.cell(r, col).font = Font(bold=True)

    for a in h["L1"]:  # area, then each topic followed by its drivers
        row("L1", a, None, 0)
        for t in (by["L2"][i] for i in a["children"]):
            row("L2", t, a["name"], 2)
            for d in (by["L3"][i] for i in t["children"]):
                row("L3", d, t["name"], 4)

    dv = DataValidation(type="list", formula1='"Area,Topic,Driver"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"A2:A{ws.max_row + 500}")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{chr(64 + len(COLUMNS))}{ws.max_row}"

    info = wb.create_sheet("How to edit")
    for a, b in HOW_TO:
        info.append([a, b])
    info.column_dimensions["A"].width, info.column_dimensions["B"].width = 20, 110
    info["A1"].font = Font(bold=True, size=13)
    for r in range(2, info.max_row + 1):
        info.cell(r, 1).font = Font(bold=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    n = {lv: len(h[lv]) for lv in ("L1", "L2", "L3")}
    print(f"{n['L1']} areas, {n['L2']} topics, {n['L3']} drivers -> {out}")


if __name__ == "__main__":
    main()
