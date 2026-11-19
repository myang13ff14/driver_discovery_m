"""Semantic search over experience records: BGE cosine similarity between the query and each `situation`.

The query is typically what the customer said; the agent gets back what agents did next in the most
similar past situations.
"""

import json
from pathlib import Path

import numpy as np

MODEL = "BAAI/bge-large-en-v1.5"
# BGE's instruction for short-query -> passage retrieval; "" gives plain symmetric similarity
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MIN_SIMILARITY = 0.7  # better too few than wrong: in tests, relevant matches scored about 0.72-0.84
CACHE = Path(__file__).parent / "result/embedding_cache.npz"  # record embeddings, so restarts skip re-encoding


def situation_text(r):
    return r["situation"]


class Searcher:
    """Embeddings are cached by text, in memory and in CACHE on disk, so a restart or a new
    extraction run only embeds records not seen before."""

    def __init__(self, query_prefix=QUERY_PREFIX, min_similarity=MIN_SIMILARITY, cache_path=CACHE):
        from sentence_transformers import SentenceTransformer
        try:  # use the local copy without asking the Hugging Face Hub; download only the first time
            self.model = SentenceTransformer(MODEL, local_files_only=True)
        except OSError:
            self.model = SentenceTransformer(MODEL)
        self.cache_path = Path(cache_path)
        self.cache = self._load()
        self.query_prefix, self.min_similarity = query_prefix, min_similarity

    def _load(self):
        try:
            d = np.load(self.cache_path, allow_pickle=False)
        except (OSError, ValueError):
            return {}
        if str(d["model"]) != MODEL:  # vectors from another model are not comparable
            return {}
        return dict(zip(d["texts"].tolist(), d["vectors"]))

    def _save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp.npz")
        np.savez(tmp, model=MODEL, texts=np.array(list(self.cache), dtype=str),
                 vectors=np.stack(list(self.cache.values())))
        tmp.replace(self.cache_path)

    def embed(self, texts):
        new = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if new:
            for t, v in zip(new, self.model.encode(new, normalize_embeddings=True, batch_size=64)):
                self.cache[t] = v
            self._save()
        return np.stack([self.cache[t] for t in texts]) if texts else np.zeros((0, 1024))

    def search(self, query, records, k=20, min_similarity=None):
        """records: the candidate pool (already filtered). Returns [(record, info)] best first."""
        floor = self.min_similarity if min_similarity is None else min_similarity
        if not records or not query.strip():
            return []
        q = self.model.encode([self.query_prefix + query], normalize_embeddings=True)[0]
        sim = self.embed([situation_text(r) for r in records]) @ q
        return [(records[i], {"similarity": round(float(sim[i]), 3)})
                for i in np.argsort(-sim)[:k] if sim[i] >= floor]


def to_agent(record, info):
    """What an agent tool returns: the past decision point, its evidence, and how close it is."""
    s = record["source"]
    return {
        "example_id": record["example_id"],
        "status": "observed",  # historical practice, not a rule; check current policy before acting on it
        "situation": record["situation"],
        "known_at_decision": record["known_at_decision"],
        "observed_next_action": record["observed_next_action"],
        "observed_result": record["observed_result"],
        "evidence": [f"[{e['line']}] {e.get('speaker', '')} ({e['role']}): {e['text']}" for e in record["evidence"]],
        "driver": s["L3"],
        "call": f"{s['genuuid']} step {s['step']}",
        "similarity": info["similarity"],
    }


SITUATION_PROMPT = (Path(__file__).parent / "situation_prompt.md").read_text(encoding="utf-8")


def extract_situation(client, model, text, driver):
    """LLM: what the customer typed -> one situation sentence in the records' style."""
    prompt = SITUATION_PROMPT.replace("{driver}", driver).replace("{text}", text)
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}],
                                          response_format={"type": "json_object"})
    return json.loads(resp.choices[0].message.content)["situation"].strip()
