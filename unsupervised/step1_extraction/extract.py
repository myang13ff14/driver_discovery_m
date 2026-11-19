"""Extract customer requests per transcript using extraction_prompt.md."""

import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]  # project root: .env, data/
PROMPT = (HERE / "extraction_prompt.md").read_text(encoding="utf-8")
DEFAULT_CSV = ROOT / "data/Polaris_Transcript_Only_Before_IVA_US_Oct_2025_random1000_deidentified.csv"
META = ["genuuid", "vcuuid", "agentid", "intent", "product", "start_time", "turns"]


def load_rows(path):
    csv.field_size_limit(10**9)
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_prompt(row):
    # .replace, not .format: the prompt contains literal JSON braces
    return (PROMPT.replace("{product}", row["product"])
                  .replace("{intent}", row["intent"])
                  .replace("{conversation}", row["conversation"]))


def snap_to_lines(chunk, conversation):
    """Replace each chunk line with the full transcript line containing it.

    The model tends to trim the first and last lines of a troubleshooting chunk;
    this restores them so the chunk is always whole raw lines. Lines it can't find
    (rare paraphrases) are kept as written.
    """
    src = conversation.split("\n")
    out = []
    for line in chunk.split("\n"):
        # match on the words after the speaker label; the trim can fall right after it
        text = re.sub(r"^\s*(Agent|User):\s*", "", line).strip()
        if text and text != "...":
            line = next((s for s in src if text in s), line)
        out.append(line)
    return "\n".join(out)


def extract(client, model, row):
    out = {k: row[k] for k in META}
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_prompt(row)}],
            response_format={"type": "json_object"},
        )
        out["requests"] = json.loads(resp.choices[0].message.content)["requests"]
        for r in out["requests"]:
            if r.get("troubleshooting_transcript"):
                r["troubleshooting_transcript"] = snap_to_lines(r["troubleshooting_transcript"],
                                                                row["conversation"])
        out["error"] = None
    except Exception as exc:  # noqa: BLE001 - recorded per row
        out["requests"] = []
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=HERE / "result/extractions.json")
    ap.add_argument("--refresh", action="store_true",
                    help="replace cached output by extracting from the CSV again")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists() and not args.refresh:
        try:
            cached = json.loads(out.read_text(encoding="utf-8"))
            calls = cached["calls"]
            if not isinstance(calls, list) or any(
                not isinstance(call, dict) or not isinstance(call.get("requests"), list)
                for call in calls
            ):
                raise ValueError("expected a calls list with requests lists")
            errors = sum(call.get("error") is not None for call in calls)
        except (ValueError, KeyError, TypeError) as exc:
            ap.error(f"Invalid extraction cache {out}: {exc}. Use --refresh to rebuild it.")
        print(f"Reusing cached extraction: {len(calls)} calls, {errors} errors -> {out}")
        print("CSV, limit and model options are ignored on a cache hit; use --refresh to re-extract.")
        return

    if not Path(args.csv).is_file():
        ap.error(f"Transcript CSV not found: {args.csv}. Copy an existing extraction cache "
                 f"to {out}, or provide --csv with a transcript file.")

    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    client = OpenAI()
    rows = load_rows(args.csv)[: args.limit]

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda r: extract(client, args.model, r), rows))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": args.model, "calls": results}, indent=1), encoding="utf-8")
    errors = sum(r["error"] is not None for r in results)
    print(f"{len(results)} calls, {errors} errors -> {out}")


if __name__ == "__main__":
    main()
