"""Recommend a call-driver category list from step 1's free-text categories."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

HERE = Path(__file__).parent
ROOT = HERE.parents[1]  # project root: .env, data/
STAGE = HERE.parent    # unsupervised/
PROMPT = (HERE / "taxonomy_prompt.md").read_text(encoding="utf-8")
DEFAULT_IN = STAGE / "step1_extraction/result/extractions.json"


def category_table(path, n_examples):
    """One line per observed category: name | count | example requests."""
    calls = json.loads(Path(path).read_text(encoding="utf-8"))["calls"]
    counts, examples = Counter(), defaultdict(list)
    for call in calls:
        for r in call["requests"]:
            cat = r["category"].strip().lower()
            counts[cat] += 1
            if len(examples[cat]) < n_examples:
                examples[cat].append(r["request"])
    lines = [f"{c} | {n} | {' ;; '.join(examples[c])}" for c, n in counts.most_common()]
    return "\n".join(lines), counts


def remap_missing(client, model, result, counts, table):
    """Ask again for observed categories the first answer left out of the mapping."""
    missing = sorted(set(counts) - set(result["mapping"]))
    if not missing:
        return
    names = [c["name"] for c in result["categories"]]
    rows = [line for line in table.splitlines() if line.split(" | ")[0] in missing]
    prompt = ("Map each observed category below to exactly one of these call-driver categories. "
              "Use only these names, exactly as written:\n" + "\n".join(f"- {n}" for n in names) +
              "\n\nObserved categories (<category> | <count> | <example requests>):\n" +
              "\n".join(rows) +
              '\n\nReturn valid JSON only: {"mapping": {"<observed category>": "<category name>"}}')
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"})
    extra = json.loads(resp.choices[0].message.content)["mapping"]
    result["mapping"].update({k: v for k, v in extra.items() if k in missing})


def write_markdown(result, counts, path):
    per_cat = Counter()
    for raw, cat in result["mapping"].items():
        per_cat[cat] += counts.get(raw, 0)
    total = sum(counts.values())
    lines = ["# Recommended call-driver categories", "",
             f"{total} requests from step 1, {len(counts)} observed categories.", "",
             "| Category | Requests | % | Definition | Subcategories | Observed categories mapped in |",
             "|---|---|---|---|---|---|"]
    by_cat = defaultdict(list)
    for raw, cat in result["mapping"].items():
        by_cat[cat].append(f"{raw} ({counts.get(raw, 0)})")
    for c in sorted(result["categories"], key=lambda c: -per_cat[c["name"]]):
        n = per_cat[c["name"]]
        name = c["name"] + ("" if c.get("observed", True) else " *(not observed)*")
        lines.append(f"| {name} | {n} | {n / total:.1%} | {c['definition']} | "
                     f"{', '.join(c['subcategories'])} | {', '.join(by_cat[c['name']])} |")
    lines += ["", "## Notes", ""] + [f"- {n}" for n in result.get("notes", [])]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_IN)
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--examples", type=int, default=3, help="example requests per category")
    ap.add_argument("--out", default=HERE / "result/taxonomy.json")
    args = ap.parse_args()

    table, counts = category_table(args.input, args.examples)
    load_dotenv(ROOT / ".env")
    client = OpenAI()
    resp = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": PROMPT.replace("{table}", table)}],
        response_format={"type": "json_object"},
    )
    result = json.loads(resp.choices[0].message.content)
    remap_missing(client, args.model, result, counts, table)

    names = {c["name"] for c in result["categories"]}
    unmapped = sorted(set(counts) - set(result["mapping"]))
    unknown = sorted({v for v in result["mapping"].values() if v not in names})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": args.model, "input": str(args.input),
                               "observed_counts": dict(counts.most_common()), **result},
                              indent=1), encoding="utf-8")
    write_markdown(result, counts, out.with_suffix(".md"))
    print(f"{len(result['categories'])} categories -> {out} (+ .md)")
    print(f"unmapped observed categories: {unmapped or 'none'}")
    print(f"mapped to undefined category names: {unknown or 'none'}")


if __name__ == "__main__":
    main()
