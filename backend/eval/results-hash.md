Embedder: `hash`. Corpus: 9 notes. Golden set: 9 direct, 9 paraphrase, 7 out-of-scope.

| Retriever | Direct R@1 | Direct R@3 | Direct MRR | Paraphrase R@1 | Paraphrase R@3 | Paraphrase MRR | Answered in-scope | Abstained out-of-scope |
|---|---|---|---|---|---|---|---|---|
| bm25 | 1.0 | 1.0 | 1.0 | 0.667 | 0.667 | 0.667 | 0.889 | 0.857 |
| dense | 0.889 | 1.0 | 0.944 | 0.444 | 0.667 | 0.556 | 0.833 | 0.857 |
| hybrid | 1.0 | 1.0 | 1.0 | 0.778 | 0.889 | 0.833 | 0.889 | 0.857 |
