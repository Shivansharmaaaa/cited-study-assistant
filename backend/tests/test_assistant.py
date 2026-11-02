from pathlib import Path

import pytest

from app.assistant import answer
from app.evaluator import KeyPoint, evaluate
from app.retriever import BM25Retriever, split_sentences, tokenize

DATA = Path(__file__).resolve().parent.parent / "data" / "notes.json"


@pytest.fixture(scope="module")
def retriever():
    return BM25Retriever.from_file(DATA)


def test_tokenize_drops_stopwords():
    assert tokenize("What is the Preamble of India?") == ["preamble", "india"]


def test_split_sentences_keeps_initials_and_case_names_whole():
    assert split_sentences("Dr B. R. Ambedkar spoke. It was in Part III. Next one!") == [
        "Dr B. R. Ambedkar spoke.", "It was in Part III.", "Next one!"]
    assert len(split_sentences("Kesavananda Bharati v. State of Kerala was in 1973.")) == 1


@pytest.mark.parametrize(
    "question,expected_note",
    [
        ("Which articles cover Fundamental Rights?", "N01"),
        ("Which writs can the Supreme Court issue?", "N02"),
        ("Who laid down the basic structure doctrine?", "N06"),
        ("What did the 73rd Amendment do for Panchayati Raj?", "N07"),
        ("Which article gives the Election Commission control of elections?", "N08"),
        ("What is President's Rule?", "N09"),
        ("Which amendment added Fundamental Duties?", "N04"),
    ],
)
def test_top_hit_is_expected_note(retriever, question, expected_note):
    result = answer(question, retriever)
    assert result.answered
    assert result.citations[0].note_id == expected_note


def test_every_sentence_in_answer_has_a_citation(retriever):
    result = answer("What are Directive Principles of State Policy?", retriever)
    assert result.answered
    for c in result.citations:
        assert f"[{c.ref}]" in result.text


def test_weak_trailing_hits_are_not_cited(retriever):
    # "President" also appears in the Election Commission note; it must not be cited.
    result = answer("What is President's Rule?", retriever)
    assert result.citations
    assert all(c.note_id == "N09" for c in result.citations)


def test_abstains_on_out_of_scope_question(retriever):
    result = answer("How do I bake sourdough bread?", retriever)
    assert not result.answered
    assert result.citations == []


def test_answers_only_use_note_sentences(retriever):
    result = answer("Tell me about writs", retriever)
    all_sentences = {p.sentence for p in retriever.passages}
    assert all(c.sentence in all_sentences for c in result.citations)


def test_evaluator_full_and_partial_scores():
    rubric = [
        KeyPoint("Part III", ["part iii"]),
        KeyPoint("Articles 12-35", ["articles 12 to 35", "articles 12-35"]),
        KeyPoint("Article 32", ["article 32"]),
    ]
    full = evaluate("Part III, Articles 12 to 35; remedy under Article 32.", rubric)
    assert full.score == 1.0 and not full.missed
    partial = evaluate("They are in Part III.", rubric)
    assert partial.score == 0.33
    assert partial.missed == ["Articles 12-35", "Article 32"]


def test_evaluator_rejects_empty_rubric():
    with pytest.raises(ValueError):
        evaluate("anything", [])
