"""Cut the calls of one call driver into decision-point experience records (decision_prompt.md)."""

import argparse
import collections
import csv
import difflib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
PROMPT = (HERE / "decision_prompt.md").read_text(encoding="utf-8")
DEFAULT_CSV = ROOT / "data/Polaris_Transcript_Only_Before_IVA_US_Oct_2025_random1000_deidentified.csv"
DEFAULT_LABELS = ROOT / "unsupervised/step5_hierarchy/result/labels.json"
DEFAULT_EXTRACTIONS = ROOT / "unsupervised/step1_extraction/result/extractions.json"

# Per-language strings filled into the prompt; the example mirrors the one in the task spec
LANG = {
    "zh": {
        "lang": "Simplified Chinese",
        "unknown": "未知",
        "ex_situation_1": "客户查询保修，提供SN后纠正了其中一位。",
        "ex_known_1": "已收到修正，但客户尚未确认完整修正值。",
        "ex_action_1": "客服复述修正后的完整SN，请客户确认。",
        "ex_result_1": "客户确认复述正确。",
        "ex_situation_2": "客户查询保修，修正后的SN已经客户确认。",
        "ex_known_2": "SN已确认；保修状态尚未查询。",
        "ex_action_2": "客服表示要帮客户查一下。",
        "ex_result_2": "客服告知设备在保，保修期到明年三月。",
        "intent": r"客服(正在|已经)?(准备|打算|即将|将要|将|想要|计划)",
    },
    "en": {
        "lang": "English",
        "unknown": "unknown",
        "ex_situation_1": "Customer asks about warranty and corrects one character of the serial number.",
        "ex_known_1": "Correction received, but the customer has not confirmed the full corrected value.",
        "ex_action_1": "Agent reads back the full corrected serial number and asks the customer to confirm.",
        "ex_result_1": "Customer confirms the read-back is correct.",
        "ex_situation_2": "Customer asks about warranty; the corrected serial number has been confirmed.",
        "ex_known_2": "Serial number confirmed; warranty status not yet looked up.",
        "ex_action_2": "Agent says they will check.",
        "ex_result_2": "Agent reports the device is covered until next March.",
        "intent": r"(?i)agent (is )?(about to|preparing to|prepares to|plans? to|intends? to|is going to|will)\b",
    },
}


def load_transcripts(path):
    csv.field_size_limit(10**9)
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["genuuid"]: r["conversation"] for r in csv.DictReader(f)}


def list_drivers(labels):
    tree = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for x in labels:
        if x["L3"]:
            tree[x["L1"]][x["L2"]][x["L3"]] += 1
    for l1, l2s in sorted(tree.items(), key=lambda kv: -sum(sum(c.values()) for c in kv[1].values())):
        print(f"L1 {l1} ({sum(sum(c.values()) for c in l2s.values())})")
        for l2, l3s in sorted(l2s.items(), key=lambda kv: -sum(kv[1].values())):
            print(f"  L2 {l2} ({sum(l3s.values())})")
            for l3, n in l3s.most_common():
                print(f"    L3 {l3} ({n})")


def select_requests(labels, level, name):
    picked = [x for x in labels if x[level] and x[level].lower() == name.lower()]
    if not picked:
        names = sorted({x[level] for x in labels if x[level]})
        close = [n for n in names if name.lower() in n.lower()] or names
        raise SystemExit(f"No {level} named {name!r}. Candidates:\n  " + "\n  ".join(close))
    return picked


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def number_lines(conversation):
    lines = [ln for ln in conversation.splitlines() if ln.strip()]
    return lines, "\n".join(f"[{i}] {ln}" for i, ln in enumerate(lines))


def build_prompt(req, transcript, lang):
    p = PROMPT
    for k, v in LANG[lang].items():
        if k != "intent":
            p = p.replace("{" + k + "}", v)
    # .replace, not .format: the prompt contains literal JSON braces
    return (p.replace("{request}", req["request"])
             .replace("{customer_quote}", req.get("customer_quote", ""))
             .replace("{transcript}", transcript))


def _norm(s):
    return re.sub(r"[^a-z0-9\[\]]+", " ", s.lower()).strip()


def repair_quote(text, line, min_ratio=0.8):
    """Closest word span of `line` to a lightly edited quote (dropped "uh", "gonna" -> "will"), or None."""
    words, q = line.split(), _norm(text)
    n, best, best_ratio = len(text.split()), None, min_ratio
    for size in range(max(1, n - 3), n + 4):
        for start in range(0, max(1, len(words) - size + 1)):
            span = " ".join(words[start:start + size])
            r = difflib.SequenceMatcher(None, q, _norm(span)).ratio()
            if r > best_ratio:
                best, best_ratio = span, r
    return best


def check(decision, lines, unknown, intent):
    """Mechanical checks of the three extraction rules; returns a list of issue strings.

    Quotes that nearly match their cited line are replaced by the exact span (issue `quote_repaired`).
    """
    issues = []
    # the agent's intention to act is the action leaking into the pre-decision state
    if re.search(intent, decision.get("situation", "") + decision.get("known_at_decision", "")):
        issues.append("action_intent_in_state")
    ev = decision.get("evidence") or []
    for e in ev:
        i, text = e.get("line"), _norm(e.get("text", ""))
        if not isinstance(i, int) or not 0 <= i < len(lines):
            issues.append(f"bad_line:{i}")
        elif text not in _norm(lines[i]):
            hits = [j for j, ln in enumerate(lines) if text and text in _norm(ln)]
            fixed = None if hits else repair_quote(e.get("text", ""), lines[i].split(":", 1)[-1])
            if fixed:
                e["text"] = fixed
                issues.append(f"quote_repaired:{i}")
            else:
                issues.append(f"wrong_line:{i}->{hits[0]}" if hits else f"not_verbatim:{i}")
    action = [e for e in ev if e.get("role") == "action" and isinstance(e.get("line"), int)]
    if not action:
        return issues + ["no_action_evidence"]
    a = min(x["line"] for x in action)
    first_action = _norm(" ".join(x["text"] for x in action if x["line"] == a))
    for e in ev:
        if e.get("role") != "context" or not isinstance(e.get("line"), int) or e["line"] < a:
            continue
        # context may be an earlier part of the action line itself
        line = _norm(lines[e["line"]]) if e["line"] < len(lines) else ""
        c, act = line.find(_norm(e.get("text", ""))), line.find(first_action)
        if e["line"] > a or c < 0 or act < 0 or c + len(_norm(e["text"])) > act:
            issues.append("context_after_action")
            break
    action = [x["line"] for x in action]
    if any(e.get("role") == "result" and isinstance(e.get("line"), int) and e["line"] <= max(action) for e in ev):
        issues.append("result_not_after_action")
    has_result = any(e.get("role") == "result" for e in ev)
    is_unknown = decision.get("observed_result", "").strip().rstrip("。.") == unknown
    if is_unknown and has_result:
        issues.append("unknown_result_with_evidence")
    if not is_unknown and not has_result:
        issues.append("result_without_evidence")
    return issues


def extract(client, model, req, conversation, lang):
    lines, numbered = number_lines(conversation)
    out = {"genuuid": req["genuuid"], "request_idx": req["request_idx"], "decisions": [], "error": None}
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_prompt(req, numbered, lang)}],
            response_format={"type": "json_object"},
        )
        out["decisions"] = json.loads(resp.choices[0].message.content)["decisions"]
    except Exception as exc:  # noqa: BLE001 - recorded per request
        out["error"] = f"{type(exc).__name__}: {exc}"
    for d in out["decisions"]:
        d["_issues"] = check(d, lines, LANG[lang]["unknown"], LANG[lang]["intent"])
        for e in d.get("evidence") or []:
            i = e.get("line")
            if isinstance(i, int) and 0 <= i < len(lines):
                e["speaker"] = lines[i].split(":", 1)[0].strip()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print the L1/L2/L3 drivers with request counts and exit")
    ap.add_argument("--level", choices=["L1", "L2", "L3"], default="L3")
    ap.add_argument("--name", help="driver name at --level (case-insensitive exact match)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N requests, for spot checks")
    ap.add_argument("--lang", choices=sorted(LANG), default="en", help="language of the prose fields")
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--labels", default=DEFAULT_LABELS)
    ap.add_argument("--extractions", default=DEFAULT_EXTRACTIONS)
    ap.add_argument("--out-dir", default=None, help="default: result/<level>_<driver slug>")
    args = ap.parse_args()

    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    if args.list:
        return list_drivers(labels)
    if not args.name:
        ap.error("--name is required (use --list to see the drivers)")

    picked = select_requests(labels, args.level, args.name)[: args.limit]
    calls = {c["genuuid"]: c for c in json.loads(Path(args.extractions).read_text(encoding="utf-8"))["calls"]}
    reqs = [{**x, "customer_quote": calls[x["genuuid"]]["requests"][x["request_idx"]].get("customer_quote", "")}
            for x in picked]
    transcripts = load_transcripts(args.csv)

    load_dotenv(ROOT / ".env")
    client = OpenAI()
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(
            lambda r: extract(client, args.model, r, transcripts[r["genuuid"]], args.lang), reqs))

    out_dir = Path(args.out_dir or HERE / "result" / f"{args.level}_{slug(picked[0][args.level])}")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Better too few than wrong: a record failing any check goes to rejected_records.jsonl, not the deliverable
    kept, rejected, issue_counts = [], [], collections.Counter()
    for req, res in zip(reqs, results):
        for step, d in enumerate(res["decisions"]):
            issues = d.pop("_issues")
            d.pop("action_line", None)
            issue_counts.update(i.split(":")[0] for i in issues)
            issues = [i for i in issues if not i.startswith("quote_repaired")]
            rec = {
                "situation": d.get("situation", ""),
                "known_at_decision": d.get("known_at_decision", ""),
                "observed_next_action": d.get("observed_next_action", ""),
                "observed_result": d.get("observed_result", ""),
                "evidence": d.get("evidence", []),
                "status": "observed",
                "source": {"genuuid": req["genuuid"], "request_idx": req["request_idx"], "step": step,
                           "request": req["request"], "L1": req["L1"], "L2": req["L2"], "L3": req["L3"]},
            }
            (rejected if issues else kept).append({**rec, "issues": issues} if issues else rec)

    def write(name, prefix, recs):
        with open(out_dir / name, "w", encoding="utf-8") as f:
            for i, rec in enumerate(recs, 1):
                f.write(json.dumps({"example_id": f"{prefix}_{i:04d}", **rec}, ensure_ascii=False) + "\n")

    write("experience_records.jsonl", "example", kept)
    write("rejected_records.jsonl", "rejected", rejected)
    report = {"model": args.model, "level": args.level, "name": picked[0][args.level], "lang": args.lang,
              "requests": len(reqs), "kept": len(kept), "rejected": len(rejected),
              "errors": [{"genuuid": r["genuuid"], "error": r["error"]} for r in results if r["error"]],
              "issue_counts": dict(issue_counts)}
    (out_dir / "check_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(reqs)} requests -> {len(kept)} kept, {len(rejected)} rejected, {len(report['errors'])} errors "
          f"{dict(issue_counts)} -> {out_dir}")

if __name__ == "__main__":
    main()
