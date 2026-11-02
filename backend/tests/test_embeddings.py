import json
from pathlib import Path

import numpy as np
import pytest

from app.embeddings import CachingEmbedder, HashingEmbedder, make_embedder
from app.retriever import RRF_K, BM25Retriever, DenseRetriever, HybridRetriever

NOTES = json.loads((Path(__file__).resolve().parent.parent / "data" / "notes.json").read_text(encoding="utf-8"))


def test_hashing_embedder_is_deterministic_and_unit_length():
    a, b = HashingEmbedder(), HashingEmbedder()
    va, vb = a.embed_query("Fundamental Rights"), b.embed_query("Fundamental Rights")
    assert np.array_equal(va, vb)
    assert float(np.linalg.norm(va)) == pytest.approx(1.0, abs=1e-5)


def test_hashing_embedder_scores_shared_stems_above_unrelated_text():
    e = HashingEmbedder()
    query = e.embed_query("amendments")
    assert float(query @ e.embed_query("amendment")) > float(query @ e.embed_query("sourdough"))


def test_embed_documents_handles_empty_input():
    assert HashingEmbedder().embed_documents([]).shape == (0, 2048)
    assert make_embedder("hash").embed_documents([]).shape == (0, 2048)


def test_caching_embedder_embeds_each_text_once():
    class Counting(HashingEmbedder):
        calls: list[str] = []

        def embed_documents(self, texts):
            self.calls.extend(texts)
            return super().embed_documents(texts)

    inner = Counting()
    cached = CachingEmbedder(inner)
    first = cached.embed_documents(["a note", "b note"])
    second = cached.embed_documents(["b note", "a note", "c note"])
    assert inner.calls == ["a note", "b note", "c note"]
    assert np.array_equal(first[0], second[1])


def test_unknown_embedder_backend_is_rejected():
    with pytest.raises(ValueError):
        make_embedder("nope")


def test_rrf_rewards_appearing_in_both_rankings():
    hybrid = HybridRetriever(NOTES, HashingEmbedder())
    top = hybrid.search("Who laid down the basic structure doctrine?", k=1)[0]
    assert top.note_id == "N06"
    assert top.bm25 > 0 and top.dense > 0
    assert top.score == pytest.approx(2 / (RRF_K + 1), abs=1e-4)  # ranked first by both


def test_hybrid_finds_a_stem_match_that_bm25_misses():
    notes = [{"id": "A", "title": "Topic", "text": "Parliament passed several amendments."},
             {"id": "B", "title": "Other", "text": "Rivers flow towards the sea."}]
    assert BM25Retriever(notes).search("amendment", k=1) == []
    assert HybridRetriever(notes, HashingEmbedder()).search("amendment", k=1)[0].note_id == "A"


def test_retrievers_return_nothing_for_stopword_only_or_empty_corpus():
    assert HybridRetriever(NOTES, HashingEmbedder()).search("what is the", k=3) == []
    assert HybridRetriever([], HashingEmbedder()).search("anything at all", k=3) == []
    assert DenseRetriever([], HashingEmbedder()).search("anything at all", k=3) == []
