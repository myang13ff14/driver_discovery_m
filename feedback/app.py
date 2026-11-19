"""Review app: browse step 5's call-driver clusters, edit them, and save the reviewed taxonomy.

Run: .venv/bin/python feedback/app.py [--port 8766], then open http://localhost:8766

Edits are saved to result/review_state.json (the app's working state) and written out as
result/hierarchy.json and result/labels.json, in the same format as step 5, for the supervised step.
"""

import argparse
import csv
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import step5_format

HERE = Path(__file__).parent
ROOT = HERE.parent
STAGE = ROOT / "unsupervised"
HIERARCHY = STAGE / "step5_hierarchy/result/hierarchy.json"
CLUSTERS = STAGE / "step2_clustering/result/clusters_request.json"
CSV = ROOT / "data/Polaris_Transcript_Only_Before_IVA_US_Oct_2025_random1000_deidentified.csv"
RESULT = HERE / "result"
STATE = RESULT / "review_state.json"
RECLUSTER_OUT = ROOT / "supervised/result"
LEVELS = ("L1", "L2", "L3")


def load_source():
    """Step 5's categories and step 2's request membership, as the starting point for review."""
    h = json.loads(HIERARCHY.read_text(encoding="utf-8"))
    cats = {}
    for lv in LEVELS:
        for c in h[lv]:
            cats[f"{lv}-{c['id']}"] = {"level": lv, "name": c["name"], "description": c["description"],
                                       "parent": None, "reviewed": False, "merged_into": None,
                                       "coherence": c.get("coherence")}
    for lv, below in (("L1", "L2"), ("L2", "L3")):
        for c in h[lv]:
            for child in c["children"]:
                cats[f"{below}-{child}"]["parent"] = f"{lv}-{c['id']}"
    requests, assign = [], {}
    for cl in json.loads(CLUSTERS.read_text(encoding="utf-8"))["clusters"]:
        for m in cl["members"]:
            key = f"{m['genuuid']}|{m['request_idx']}"
            requests.append({"key": key, **{k: m[k] for k in (
                "genuuid", "request_idx", "request", "category", "customer_quote", "agent_quote", "solution",
                "request_type", "outcome", "is_primary")}})
            assign[key] = None if cl["cluster"] == -1 else f"L3-{cl['cluster']}"
    return {"categories": cats, "requests": requests, "assign": assign,
            "n_requests": h["n_requests"], "unclustered": h["unclustered"]}


def load_transcripts():
    csv.field_size_limit(10**9)
    with open(CSV, newline="", encoding="utf-8-sig") as f:
        return {r["genuuid"]: r["conversation"] for r in csv.DictReader(f)}


SOURCE = load_source()
TRANSCRIPTS = load_transcripts()
REQUESTS = {r["key"]: r for r in SOURCE["requests"]}


def export(state):
    """Write the reviewed result as hierarchy.json and labels.json in step 5's format (step5_format.py)."""
    cats, assign = state["categories"], state["assign"]
    live = {k: c for k, c in cats.items() if not c["merged_into"] and not c.get("removed")}
    names = lambda pick: {lv: [c["name"] for k, c in live.items() if c["level"] == lv and pick(k, c)] for lv in LEVELS}
    review = {
        "reviewed": names(lambda k, c: c["reviewed"]),
        "added": names(lambda k, c: "-new-" in k),
        "merged": [{"level": c["level"], "name": c["name"], "into": cats[c["merged_into"]]["name"]}
                   for c in cats.values() if c["merged_into"]],
        "removed": [{"level": c["level"], "name": c["name"]} for c in cats.values() if c.get("removed")],
        "edits": len(state.get("log", [])),
    }
    step5_format.write(live, assign, SOURCE["requests"], RESULT, "llm + human review", review)


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
        elif url.path == "/api/source":
            saved = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else None
            self.send({**SOURCE, "saved": saved})
        elif url.path == "/api/recluster":
            self.send(recluster_report())
        elif url.path == "/api/transcript":
            text = TRANSCRIPTS.get(q.get("genuuid"), "")
            self.send([line for line in text.splitlines() if line.strip()])
        else:
            self.send({"error": "not found"}, code=404)

    def do_POST(self):
        url = urlparse(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        RESULT.mkdir(parents=True, exist_ok=True)
        if url.path == "/api/state":
            tmp = STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(body), encoding="utf-8")
            tmp.replace(STATE)
            export(body)
            self.send({"saved": True})
        elif url.path == "/api/recluster":
            # the page saves first, so this reclusters the review as it is now
            p = subprocess.run([sys.executable, str(ROOT / "supervised/recluster.py"), "--input", str(RESULT),
                                "--out", str(RECLUSTER_OUT)], capture_output=True, text=True)
            if p.returncode:
                return self.send({"error": (p.stdout + p.stderr)[-1500:]}, code=500)
            self.send(recluster_report())
        elif url.path == "/api/reset":
            STATE.unlink(missing_ok=True)
            self.send({"reset": True})
        else:
            self.send({"error": "not found"}, code=404)

    def log_message(self, *args):
        pass


def recluster_report():
    """The last recluster's report, and whether the review changed after it ran."""
    f = RECLUSTER_OUT / "recluster_report.json"
    if not f.exists():
        return {"report": None}
    review = RESULT / "hierarchy.json"
    return {"report": json.loads(f.read_text(encoding="utf-8")), "ran": f.stat().st_mtime * 1000,
            "stale": review.exists() and review.stat().st_mtime > f.stat().st_mtime}


def main():
    global RESULT, STATE, RECLUSTER_OUT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--result", default=RESULT, help="where the review is saved (use another folder for test runs)")
    ap.add_argument("--recluster-out", default=RECLUSTER_OUT, help="where the Recluster tab writes its output")
    args = ap.parse_args()
    RESULT = Path(args.result)
    RECLUSTER_OUT = Path(args.recluster_out)
    STATE = RESULT / "review_state.json"
    print(f"Open http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
