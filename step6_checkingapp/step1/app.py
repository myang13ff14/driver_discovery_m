"""Small local app: browse the L1/L2/L3 drivers (step 5 clusters) and search their experience records.

Run: .venv/bin/python step6_checkingapp/step1/app.py [--port 8765], then open http://localhost:8765
"""

import argparse
import collections
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from openai import OpenAI

from extract_decisions import DEFAULT_CSV, DEFAULT_LABELS, HERE, ROOT, load_transcripts, number_lines
from search import Searcher, extract_situation, situation_text, to_agent

RESULT = HERE / "result"
LABELS = json.loads(DEFAULT_LABELS.read_text(encoding="utf-8"))
HIERARCHY = json.loads((DEFAULT_LABELS.parent / "hierarchy.json").read_text(encoding="utf-8"))
TRANSCRIPTS = load_transcripts(DEFAULT_CSV)
JOBS = {}  # "L3|name" -> {"state": "running"|"done"|"failed", "log": str}
SEARCHER = None  # loaded in main(); record embeddings come from result/embedding_cache.npz
SEARCH_LOCK = threading.Lock()  # one GPU encode at a time
LLM_MODEL = "gpt-5.6-luna"
LLM = None  # OpenAI client, created in main()
SITUATIONS = {}  # (driver, typed text) -> extracted situation, so repeated searches cost no LLM call


def driver_tree():
    """[{name, n, children: [{name, n, children: [{name, n}]}]}], largest first."""
    tree = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for x in LABELS:
        if x["L3"]:
            tree[x["L1"]][x["L2"]][x["L3"]] += 1
    out = []
    for l1, l2s in tree.items():
        kids = [{"name": l2, "n": sum(c.values()),
                 "children": [{"name": l3, "n": n} for l3, n in c.most_common()]} for l2, c in l2s.items()]
        kids.sort(key=lambda k: -k["n"])
        out.append({"name": l1, "n": sum(k["n"] for k in kids), "children": kids})
    return sorted(out, key=lambda k: -k["n"])


def cluster_info(level=None, name=None, examples=30):
    """Step 5's view of one driver (or of all drivers): description, size, children, request mix."""
    total = HIERARCHY["n_requests"]
    by_id = {lv: {c["id"]: c for c in HIERARCHY[lv]} for lv in ("L1", "L2", "L3")}
    below = {"L1": "L2", "L2": "L3"}
    if level:
        node = next((c for c in HIERARCHY[level] if c["name"] == name), None)
        if node is None:
            return None
        kids = [by_id[below[level]][i] for i in node.get("children", [])] if level in below else []
        reqs = [x for x in LABELS if x[level] == name]
        path = [] if level == "L1" else [{"level": "L1", "name": reqs[0]["L1"]}] if reqs else []
        if level == "L3" and reqs:
            path.append({"level": "L2", "name": reqs[0]["L2"]})
        size = node["size"]
    else:
        node, kids, path = None, HIERARCHY["L1"], []
        reqs = [x for x in LABELS if x["L1"]]
        size = len(reqs)
    child_level = below.get(level) if level else "L1"
    return {
        "level": level, "name": name, "size": size, "share": size / total, "total": total,
        "unclustered": HIERARCHY["unclustered"],
        "description": node["description"] if node else None,
        "coherence": node.get("coherence") if node else None,
        "validation": node.get("validation") if node else None,
        "rank": 1 + sorted((c["size"] for c in HIERARCHY[level]), reverse=True).index(size) if level else None,
        "siblings": len(HIERARCHY[level]) if level else None,
        "path": path,
        "children": [{"level": child_level, "name": c["name"], "description": c["description"],
                      "size": c["size"], "coherence": c.get("coherence")}
                     for c in sorted(kids, key=lambda c: -c["size"])],
        "request_type": collections.Counter(x["request_type"] for x in reqs).most_common(),
        "outcome": collections.Counter(x["outcome"] for x in reqs).most_common(),
        "examples": [{k: x[k] for k in ("genuuid", "request", "request_type", "outcome", "L3")}
                     for x in spread(reqs, examples)],
    }


def spread(reqs, k):
    """Up to k requests, taking turns across L3s (largest first) so one issue doesn't fill the list;
    within an L3, the call's main request comes first."""
    groups = collections.defaultdict(list)
    for x in sorted(reqs, key=lambda x: not x["is_primary"]):
        groups[x["L3"]].append(x)
    queues = sorted(groups.values(), key=len, reverse=True)
    out = []
    while len(out) < k and any(queues):
        for q in queues:
            if q and len(out) < k:
                out.append(q.pop(0))
    return out


def all_records():
    """Kept records from every extraction run, one per (call, request, step); newest run wins."""
    seen = {}
    for f in sorted(RESULT.glob("*/experience_records.jsonl"), key=lambda p: p.stat().st_mtime):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            s = r["source"]
            seen[(s["genuuid"], s["request_idx"], s["step"])] = r
    return list(seen.values())


def extracted_counts(records):
    c = collections.Counter()
    for r in records:
        for lv in ("L1", "L2", "L3"):
            c[f"{lv}|{r['source'][lv]}"] += 1
    return c


def run_extract(level, name):
    key = f"{level}|{name}"
    JOBS[key] = {"state": "running", "log": ""}
    p = subprocess.run([sys.executable, str(HERE / "extract_decisions.py"), "--level", level, "--name", name,
                        "--workers", "16"], capture_output=True, text=True)
    JOBS[key] = {"state": "done" if p.returncode == 0 else "failed", "log": (p.stdout + p.stderr)[-2000:]}


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype="application/json", code=200):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/":
            self.send((HERE / "index.html").read_bytes(), "text/html")
        elif url.path == "/api/drivers":
            self.send({"tree": driver_tree(), "extracted": extracted_counts(all_records()), "jobs": JOBS})
        elif url.path == "/api/cluster":
            info = cluster_info(q.get("level"), q.get("name"))
            self.send(info if info else {"error": "no such driver"}, code=200 if info else 404)
        elif url.path == "/api/records":
            level, name = q.get("level"), q.get("name")
            recs = [r for r in all_records() if not level or r["source"][level] == name]
            recs.sort(key=lambda r: (r["source"]["genuuid"], r["source"]["request_idx"], r["source"]["step"]))
            self.send(recs)
        elif url.path == "/api/search":
            # semantic search within one driver, or across all records when no driver is given;
            # this is the call an agent tool would make.
            # extract=1: the LLM first turns the typed text into a situation sentence, which is
            # then matched against the records' situations (still with BGE's retrieval prefix:
            # without it, the right record for "how long until I get my computer back" fell from 1st to 11th)
            level, name, text = q.get("level"), q.get("name"), q.get("q", "")
            if level and (level not in ("L1", "L2", "L3") or not name):
                return self.send({"error": "level must be L1, L2 or L3, with a name"}, code=400)
            pool = [r for r in all_records() if (not level or r["source"][level] == name)
                    and (q.get("known") != "1" or r["observed_result"] != "unknown")]
            situation = None
            if q.get("extract") == "1" and text.strip():
                key = (f"{level}|{name}" if level else "all", text)
                if key not in SITUATIONS:
                    try:
                        SITUATIONS[key] = extract_situation(LLM, LLM_MODEL, text, name or "unknown (any driver)")
                    except Exception as exc:  # noqa: BLE001 - shown to the user
                        return self.send({"error": f"situation extraction failed: {exc}"}, code=502)
                situation = SITUATIONS[key]
            with SEARCH_LOCK:
                hits = SEARCHER.search(situation or text, pool, k=int(q.get("k", 20)),
                                       min_similarity=float(q["min"]) if q.get("min") else None)
            if q.get("format") == "agent":
                results = [to_agent(r, info) for r, info in hits]
            else:
                results = [{**r, "match": info} for r, info in hits]
            self.send({"query": text, "extracted_situation": situation, "results": results})
        elif url.path == "/api/transcript":
            lines, _ = number_lines(TRANSCRIPTS.get(q.get("genuuid"), ""))
            self.send(lines)
        else:
            self.send({"error": "not found"}, code=404)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/api/extract":
            return self.send({"error": "not found"}, code=404)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        level, name = body.get("level"), body.get("name")
        if level not in ("L1", "L2", "L3") or not name:
            return self.send({"error": "level and name required"}, code=400)
        if JOBS.get(f"{level}|{name}", {}).get("state") != "running":
            threading.Thread(target=run_extract, args=(level, name), daemon=True).start()
        self.send({"started": True})

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    global SEARCHER, LLM
    load_dotenv(ROOT / ".env")
    LLM = OpenAI()
    print("Loading search model...")
    SEARCHER = Searcher()
    SEARCHER.embed([situation_text(r) for r in all_records()])
    print(f"Open http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
