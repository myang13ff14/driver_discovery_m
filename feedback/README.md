# Feedback: review and edit the call-driver clusters

The unsupervised steps produce a taxonomy (step 5's `hierarchy.json`: areas → topics → drivers, with descriptions). A person reviews and edits it, and the edited taxonomy, in the same JSON format, is the input for the supervised step:

```text
step 5 hierarchy.json ──► to_excel.py ──► taxonomy.xlsx ──► edit freely in Excel ──► from_excel.py ──► hierarchy.json + labels.json ──► supervised step
```

## Edit in Excel (the main way)

```bash
.venv/bin/python feedback/to_excel.py      # -> feedback/excel/taxonomy.xlsx
# edit the Taxonomy sheet in Excel and save
.venv/bin/python feedback/from_excel.py    # -> feedback/excel/hierarchy.json and labels.json
```

The sheet has one row per category: **Level** (Area / Topic / Driver), **Name**, **Description**, **Parent** (an area for a topic, a topic for a driver), and, for reference only, **ID**, **Requests** and **Example requests**. A "How to edit" sheet explains the rules. Anything goes:

| Change | In the sheet |
|---|---|
| Rename or redefine | Change Name or Description |
| Move | Change Parent (exact name of an area or topic in the sheet) |
| Add | Insert a row; fill Level, Name, Description, Parent; leave ID empty |
| Delete | Delete the row (and its drivers, if it is a topic) |
| Merge | Delete one row and widen the other's description |

Leave the ID column alone: it links a category to the requests it was discovered from.

`from_excel.py` checks the sheet first (valid levels, every parent exists, area and topic names unique) and writes nothing if there are errors; it lists each problem with its row number. It warns about duplicate driver names and empty topics. Then it prints what changed compared with step 5 (added, deleted, renamed, description changed, moved) and writes the result in step 5's format (see "Output format" below; the changes are stored under `review`).

Requests keep the driver they were discovered in while that driver's row (ID) is in the sheet, so `labels.json` carries the clustering's labels where they still apply; requests of deleted drivers, and new drivers, have none. The supervised step relabels every request against the edited taxonomy.

For a second round, start from the edited result: `to_excel.py --input feedback/excel/hierarchy.json`, then `from_excel.py --base feedback/excel/hierarchy.json`.

With an unedited sheet, the output is identical to step 5's files (apart from `method` and `review`).

## Edit in the browser (review app)

The same free editing as the Excel sheet, in a local web page that also shows each driver's requests and transcripts. The taxonomy is edited freely: rename, redefine, move, add, remove (with everything under it) and merge. Individual requests are not moved; the supervised step assigns requests to the reviewed categories, including added ones, which start with none.

```bash
.venv/bin/python feedback/app.py [--port 8766] [--result DIR]   # then open http://localhost:8766
# --result: save somewhere other than feedback/result/, e.g. for a test run that must not touch a real review
```

| | |
|---|---|
| Input | `unsupervised/step5_hierarchy/result/hierarchy.json` (L1/L2/L3 names, descriptions, structure)<br>`unsupervised/step2_clustering/result/clusters_request.json` (which requests are in each driver, with quotes)<br>the transcript CSV in `data/` |
| Output | `result/hierarchy.json` and `result/labels.json`: the reviewed result in **exactly step 5's format**, the input for the supervised step (see below)<br>`result/review_state.json`: the app's working state (categories, request assignments, edit history) |

## Layout

- **Left:** Overview and the L1 → L2 → L3 tree with request counts. ✓ marks reviewed categories. The search box filters by name.
- **Middle (read-only):** the selected category. For an area or topic: its description and child categories with sizes. For a driver: every request with the customer's quote, request type and outcome, and a **transcript** link (the quoted line is highlighted).
- **Right:** edit the selected category.

The header has five tabs (the fifth, **Recluster**, is described below). **Table** (opens first) is the editor: one row per category, area → topics → drivers. Type into **Name** and **Description** (saved when you leave the box), pick a **Parent** to move a category, ＋ links add a driver to a topic, a topic to an area, or a new area, and ✕ removes a category and everything under it (after a confirmation). A filter box narrows the rows. **Review** is the three panels described above; **Flowchart** and **Result** are below.

**Flowchart** draws the hierarchy as boxes joined by lines (area → topic → driver), with request counts; drivers start folded (▸ opens a topic, "Open all" opens everything). Click a box to edit it in the right panel. Hover a box for **＋** (add a topic under an area, or a driver under a topic) and **✕** (a dialog to merge it into another one, or remove it). Drag a box onto another box at the same level to merge them (a dialog asks first), or onto a box one level up (a driver onto a topic, a topic onto an area) to move it there. "＋ Add a business area" adds a new area.

**Result** Result shows the reviewed taxonomy as it will go to the supervised step, compared with the automatic results: before → after counts, categories added, merged away and removed, the full L1 → L2 → L3 tree with each category's request count and change (+/−), labels for what changed (new driver, renamed, description edited, merged from), and the full edit history. Tick "show only changed categories" to hide the rest.

**Recluster** runs `supervised/recluster.py` on the review as it is now (it saves first) and shows the result: the edits found and what each one reclusters (a driver's topic, a topic's area, or everything), counts of requests reclustered and untouched, requests that changed driver/topic/area (before → after, grouped by scope, with transcript links), requests placed for the first time, and requests left for review. A banner says when you have edited the review since the last run. Output goes to `supervised/result/` (`--recluster-out` to change it).

## Edits

| Edit | How |
|---|---|
| Rename, rewrite description | Right panel → Save (or Ctrl+Enter) |
| Merge into another category of the same level | Right panel → choose → Merge. The chosen category keeps its name; the merged one's requests (or children) move into it, and it is recorded in `merged_from` |
| Add a driver | Table → ＋ Add a driver to “topic”. Or Flowchart → ＋ on a topic |
| Add a topic or area | Flowchart → ＋ on an area (adds a topic), or ＋ Add a business area |
| Merge by dragging | Flowchart → drag a box onto another box at the same level → Merge |
| Move | Table → pick a Parent. Or Flowchart → drag a driver onto a topic (or a topic onto an area) |
| Remove | Table → ✕, or Flowchart → ✕ → Remove. Everything under it is removed too; the requests of removed drivers are left out, like unclustered ones. Listed under `review.removed` in `hierarchy.json` |
| Mark reviewed | Right panel → Mark as reviewed |
| Mark everything reviewed | Header → Mark all reviewed (asks first; becomes Unmark all reviewed). Undo reverses it in one step |
| Undo | ↶ Undo or Ctrl+Z (outside text boxes). Works back to the start of the session |
| Start over | Header → Start over: deletes the saved state and reloads the step 5 results |

Every edit saves immediately (the header shows "Saved …") and is listed under Recent edits. The undo history is per browser session; the saved state and edit list persist across restarts.

Rerunning step 2 or step 5 changes the category IDs, so a saved review no longer matches. Start over after a rerun.

## Output format

Both paths write `hierarchy.json` and `labels.json` (the Excel import to `excel/`, the app to `result/` after every edit) in the same format as `unsupervised/step5_hierarchy/result/`, so anything that reads step 5's output can read the reviewed version by pointing at these files (e.g. `plot_hierarchy.py --input`, `plot_l2_scatter.py --hierarchy … --labels …`).

- `hierarchy.json`: `model`, `method` (`"llm + human review"`, or `"llm + human review (excel)"`), `n_requests`, `unclustered`, `moves`, and `L1` / `L2` / `L3` lists with the same fields as step 5 (`id`, `name`, `description`, `children`, `size`, `misfits`; `validation` on L2, recomputed; `coherence` on L3, `null` for added drivers). Step 5's integer IDs are kept; added categories get the next free ID at their level.
- An extra top-level `review` key records what changed (Excel: added, deleted, renamed, description changed, moved; app: reviewed, added, merged, removed, number of edits). Step 5 consumers ignore it.
- `labels.json`: one row per request (all 1183), same fields as step 5. `L1`/`L2`/`L3` are `null` for requests in no driver: the ones the clustering did not group, and the ones in deleted or removed drivers. The supervised step trains only on rows with labels.
- With no edits, the two files are identical to step 5's (apart from `method` and `review`).
- Categories added in review start with 0 requests; their L2 `validation` has `null` reference values.

