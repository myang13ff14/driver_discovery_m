# Supervised: recluster where the review changed something

The unsupervised steps produce a taxonomy (L1 area → L2 topic → L3 driver). A person edits it (`feedback/`). `recluster.py` then finds which levels the edits changed and reclusters **only inside the parent of each changed category**; everything else keeps the driver the review gave it.

```bash
.venv/bin/python supervised/recluster.py [--input feedback/result] [--out supervised/result]
                                         [--base unsupervised/step5_hierarchy/result/hierarchy.json]
```

## What gets reclustered

The reviewed `hierarchy.json` is compared with `--base` (what the review started from, step 5 by default) by category ID.

| Edit | Reclustered |
|---|---|
| Driver (L3) added, removed or merged | its **topic**: that topic's requests, re-sorted among that topic's drivers |
| Topic (L2) added, removed or merged | its **area**: that area's requests, re-sorted among all its drivers |
| Area (L1) added, removed or merged | **everything** |
| Rename, description edit, move | nothing (a moved category takes its requests with it) |

If an edited category's parent was removed too, the scope goes one level up (e.g. the driver of a deleted topic → the topic's area). A topic inside an area that is already being reclustered is covered by the area. Requests never clustered are sorted across the whole taxonomy.

**Re-sorting** = each request goes to the nearest driver centre among the scope's drivers (cosine between step 2 request embeddings and each driver's mean request embedding; a driver added in review has no requests, so its embedded "name: description"). A request that had no driver after review is left for review if its best match is below the 5th percentile of reviewed requests' similarity to their own driver (`--percentile`); requests that had a driver always get one.

| | |
|---|---|
| Input | `feedback/result/hierarchy.json` + `labels.json` (from the review app; `--input feedback/excel` for the Excel import, with `--base` set to the file the sheet was made from)<br>`unsupervised/step2_clustering/result/clusters_request.npz` |
| Output | `result/hierarchy.json` + `result/labels.json` (step 5's format; `method` ends in `+ recluster`, summary under `review.recluster`)<br>`result/recluster_report.json`: the edits found and their scopes, requests reclustered and untouched, every request whose L1/L2/L3 changed (before → after), and the needs-review requests |
| Runtime | Under a second; no LLM calls |

## Checks (2026-11-18)

- **The review (3 drivers removed):** reclustered only topics "Power and Charging" and "Setup and Data Migration" (143 requests); 931 untouched; 2 reviewed requests changed driver, none changed topic or area.
- **Topic deleted ("Printer Support"):** reclustered area "Connectivity & Peripherals"; its 8 printer requests fit no remaining driver and were left for review rather than forced in.
- **Area added:** reclustered everything.
- A guard stops the run if any request outside the scopes would change driver.

## Known limitation: added drivers stay empty

A driver added in review has only its description, and requests sit much closer to other drivers' request centres than to any description, so it is never the nearest. Filling added drivers needs an LLM that reads the request and the candidate drivers' descriptions, or example requests chosen by the reviewer.
