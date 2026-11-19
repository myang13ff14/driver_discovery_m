# Step 6.1: Decision-point extraction (`step6_checkingapp/step1/`)

Pick one call driver (L1, L2 or L3 from step 5). For every request labelled with that driver, cut its call into **decision points**: the moment just before the agent takes a meaningful action. Each one is recorded as a historical observation, not a rule.

| | |
|---|---|
| Input | `unsupervised/step5_hierarchy/result/labels.json` (which requests belong to the driver)<br>`unsupervised/step1_extraction/result/extractions.json` (request text and customer quote)<br>the transcript CSV |
| Method | One LLM call per request, using `decision_prompt.md`. Transcript lines are numbered, and evidence cites them. The script then checks every record mechanically (see below). |
| Model | `gpt-5.6-luna` |
| Output | `result/<level>_<driver>/experience_records.jsonl`: the deliverable, one record per line, only records that pass every check<br>`result/<level>_<driver>/rejected_records.jsonl`: records that failed a check, with their `issues`, for review only<br>`result/<level>_<driver>/check_report.json`: counts per issue |

**Fewer but correct (宁缺毋滥).** A record that fails any check is left out of the deliverable. The prompt also tells the model to skip a decision point it cannot back with evidence.

Run:

```bash
.venv/bin/python step6_checkingapp/step1/extract_decisions.py --list                      # show drivers
.venv/bin/python step6_checkingapp/step1/extract_decisions.py --level L3 \
    --name "Built-in camera not detected or working" [--limit 5] [--lang en|zh] [--workers 16]
```

## Record

```json
{"example_id": "example_0001",
 "situation": "...", "known_at_decision": "...",
 "observed_next_action": "...", "observed_result": "... or unknown",
 "evidence": [{"role": "context|action|result", "line": 12, "text": "<verbatim>", "speaker": "Agent"}],
 "status": "observed",
 "source": {"genuuid": "...", "request_idx": 0, "step": 0, "request": "...", "L1": "...", "L2": "...", "L3": "..."}}
```

`line` is the 0-based index among the transcript's non-empty lines. Prose fields are in English by default (`--lang zh` for Chinese, where an unknown result is `未知`). Evidence is always verbatim from the transcript.

## Rules and how they are checked

| Rule | Check in `check()` | Issue code |
|---|---|---|
| situation and known_at_decision do not state the agent's intention to act ("the agent is about to…", "客服准备…") | regex on those two fields | `action_intent_in_state` |
| situation and known_at_decision use only information from before the action | every `context` line is before the first `action` line (or an earlier part of the same line) | `context_after_action` |
| observed_result comes from later lines; with no evidence it is `unknown` | every `result` line is after the `action` lines; a result other than `unknown` needs result evidence, and `unknown` must have none | `result_not_after_action`, `result_without_evidence`, `unknown_result_with_evidence` |
| evidence is verbatim with its position | the quote is found in the cited line | `not_verbatim`, `wrong_line`, `bad_line` |
| evidence is verbatim (repair) | a quote that nearly matches its cited line (dropped "uh", "gonna" → "will") is replaced by the exact span | `quote_repaired` (fixed automatically, not flagged) |

The checks cannot catch invented tool or API calls in `observed_next_action`; the prompt forbids them, so check that by spot-reading.

## Prompt iterations (rounds 1–3: spot checks on 5 camera requests; round 4: spot-reading the full run)

| Round | Records | Flagged | Common errors found → change |
|---|---|---|---|
| 1 | 46 | 17 | Context taken from later lines (ASR turns out of order); quotes cleaned up ("uh" dropped, "gonna" → "I'll"); action leaking into situation ("客服准备结束通话"); several actions merged → defined before/after by line number, required exact quotes, one action per record |
| 2 | 38 | 11 | A result with no evidence written as an explanation instead of `未知`; context on the same line as the action counted as wrong → required exactly `未知`, allowed earlier spans on the action line |
| 3 | 50 | 14 | Remaining quote edits → automatic quote repair. `context_after_action` remains (mostly a customer reply one line after the agent's question, because of interleaved ASR turns) → failing records rejected; prompt says to skip doubtful decision points |
| 4 | 217 kept (Chinese) | About 20 kept records stated the agent's intention in the state ("客服准备进一步核实设备信息") → banned in the prompt, plus the `action_intent_in_state` check. Default language then switched to English |

## Results

L3 "Built-in camera not detected or working" (English): 27 requests → **191 kept**, 21 rejected (17 `context_after_action`), 0 API errors. 19 kept records have result `unknown`. Spot-reading found no invented tools or APIs and no agent-intention wording in the state fields.

## Known limitations

- **Interleaved transcripts.** The customer's answer to a question often appears one or more lines after the agent's next turn. The strict line-order check rejects these, so some correct decision points are lost. That is the intended trade-off.
- **Same-request scope.** Decision points are limited to the request in focus; actions for other requests in the same call are skipped, but the boundary is the model's judgement.

## Search app (`app.py` + `index.html`)

A local page for browsing the drivers and searching their records. It uses the standard library only.

```bash
.venv/bin/python step6_checkingapp/step1/app.py [--port 8765]   # then open http://localhost:8765
```

- **Left:** the L1 → L2 → L3 tree (L1s open, so all L2s show). ▸/▾ opens a level, the name selects it; **Expand all / Collapse all** at the top; **«** hides the panel and **☰ Drivers** brings it back. Each driver shows its request count and, in blue, how many records have been extracted. Click any level to select it; L1 and L2 show the records of all their L3 children.
- **Right, Cluster tab (default):** what step 5 found for the selected driver: its description, size and share of all requests, rank among its level, and a path back to its parents. L2s also show the reference check (agreement with the step 3 category and the most common free-text categories). Below that: its child clusters with descriptions, sizes and share bars (click one to open it), the request-type and outcome mix, and up to 30 example requests, taken in turn from each L3 so one issue doesn't fill the list. **All drivers** shows the same for the 6 L1 domains. Data comes from `hierarchy.json` and `labels.json` via `GET /api/cluster?level=…&name=…`. The URL hash links to a driver, e.g. `#L2/Power%20and%20Charging`.
- **Right, Search and Showcase tabs:** search **within the selected driver only** (the box is disabled until you pick one). Type a situation in plain words; the top 20 records come back ranked (see below). With an empty box, the page lists the driver's records in call order. Tick "only known results" to hide `unknown`. Tick **agent view (JSON)** to see the top 5 exactly as an agent tool would receive them (`to_agent()` in `search.py`). Each card has **evidence** (quotes with line numbers) and **transcript** (the full call with the evidence lines highlighted).
- **No records yet:** the page offers an **Extract records** button. It runs `extract_decisions.py` for that driver in the background (one LLM call per request) and refreshes when it finishes.

The app reads every `result/*/experience_records.jsonl`. If two runs cover the same call, request and step, the newest file wins.

Record embeddings are saved in `result/embedding_cache.npz` (git-ignored), keyed by situation text and model name. The first start embeds every record (about 20 s); later starts load the file and only embed records added since. Delete the file to rebuild it. The BGE model is loaded from the local Hugging Face cache without contacting the Hub, and downloaded only if it is missing.

### How search works (`search.py`, `GET /api/search?q=…&level=…&name=…&k=20&known=0|1[&format=agent]`)

The agent is assumed to know the call's driver already, so `level` and `name` are required (HTTP 400 without them) and only that driver's records are searched.

**Optional LLM step (`extract=1`, the "LLM → situation" box, on by default).** What you typed is first turned into one `situation` sentence by `gpt-5.6-luna` with `situation_prompt.md`. The prompt applies the extraction rule for situations: only what the text says, no agent intention, generic, same style as the stored situations. That sentence is then matched instead of the raw text and is shown above the results; results are cached per driver and text. In this mode the page searches on Enter (one LLM call per search); with the box off it searches as you type. Test: for "how long until I get my computer back", the record where the agent gives the 7–10-day repair time ranked 11th–13th from the raw text and 1st from the extracted situation.

Search is **semantic only**: BGE (`bge-large-en-v1.5`, as in step 2) embeds each record's `situation`, and the query, which is usually what the customer said, is ranked by cosine similarity to it. The query gets BGE's retrieval instruction ("Represent this sentence for searching relevant passages: "); on five customer-style test queries it ranked slightly better than no prefix. Results below similarity 0.70 are not returned (`min=` parameter, or the "min similarity" box). In tests, relevant matches scored about 0.72–0.84. known_at_decision, the action, the result and the evidence are returned, not matched.

An earlier version also used BM25 keywords; it was removed because typed queries are customer speech, whose wording rarely matches the third-person situation summaries.

Each result carries its `similarity`. Records are returned with `status: "observed"`: what agents did, not a rule. An agent tool can call the same endpoint, or `Searcher.search()` directly. Embeddings are cached in memory by text, so new extraction runs only embed new records. The model loads in a few seconds at startup.
