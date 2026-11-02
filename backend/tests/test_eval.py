from eval.run_eval import run, to_markdown


def test_eval_harness_reports_all_retrievers_and_hybrid_is_not_worse_on_this_set():
    results = run("hash")
    assert set(results) == {"bm25", "dense", "hybrid"}
    assert results["hybrid"]["direct"]["recall@3"] == 1.0
    assert results["hybrid"]["paraphrase"]["recall@3"] >= results["bm25"]["paraphrase"]["recall@3"]
    assert "| hybrid |" in to_markdown(results, "hash")
