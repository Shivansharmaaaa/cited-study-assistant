"""Compare BM25, dense and hybrid retrieval on the hand-labelled golden set.

    python -m eval.run_eval                     # hashing embedder, no download
    python -m eval.run_eval --embedder fastembed --out eval/results-fastembed.md

Reports recall@1, recall@3 and MRR per question group, plus how often the assistant
answered in-scope questions and abstained on out-of-scope ones. The thresholds were
set by hand on this same small set, so these numbers show behaviour, not generalisation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.assistant import evidence
from app.embeddings import make_embedder
from app.retriever import BM25Retriever, DenseRetriever, HybridRetriever

HERE = Path(__file__).resolve().parent
NOTES = HERE.parent / "data" / "notes.json"
GOLDEN = HERE / "golden.json"


def retrievers(backend: str) -> dict:
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    embedder = make_embedder(backend)
    return {"bm25": BM25Retriever(notes), "dense": DenseRetriever(notes, embedder),
            "hybrid": HybridRetriever(notes, embedder)}


def rank_metrics(retriever, items: list[dict]) -> dict:
    r1 = r3 = rr = 0.0
    for item in items:
        ranked = [h.note_id for h in retriever.search(item["q"], k=3)]
        if item["note"] in ranked:
            rank = ranked.index(item["note"]) + 1
            r1 += rank == 1
            r3 += 1
            rr += 1 / rank
    n = len(items)
    return {"recall@1": round(r1 / n, 3), "recall@3": round(r3 / n, 3), "mrr": round(rr / n, 3)}


def run(backend: str = "hash") -> dict:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    results = {}
    for name, retriever in retrievers(backend).items():
        in_scope = golden["direct"] + golden["paraphrase"]
        results[name] = {
            "direct": rank_metrics(retriever, golden["direct"]),
            "paraphrase": rank_metrics(retriever, golden["paraphrase"]),
            "answered_in_scope": round(sum(bool(evidence(i["q"], retriever)) for i in in_scope) / len(in_scope), 3),
            "abstained_out_of_scope": round(
                sum(not evidence(i["q"], retriever) for i in golden["out_of_scope"]) / len(golden["out_of_scope"]), 3),
        }
    return results


def to_markdown(results: dict, backend: str) -> str:
    lines = [f"Embedder: `{backend}`. Corpus: 9 notes. Golden set: 9 direct, 9 paraphrase, 7 out-of-scope.", "",
             "| Retriever | Direct R@1 | Direct R@3 | Direct MRR | Paraphrase R@1 | Paraphrase R@3 | Paraphrase MRR "
             "| Answered in-scope | Abstained out-of-scope |", "|---|---|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        d, p = r["direct"], r["paraphrase"]
        lines.append(f"| {name} | {d['recall@1']} | {d['recall@3']} | {d['mrr']} | {p['recall@1']} | {p['recall@3']} "
                     f"| {p['mrr']} | {r['answered_in_scope']} | {r['abstained_out_of_scope']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedder", default="hash", choices=["hash", "fastembed"])
    parser.add_argument("--out")
    args = parser.parse_args()
    report = to_markdown(run(args.embedder), args.embedder)
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
