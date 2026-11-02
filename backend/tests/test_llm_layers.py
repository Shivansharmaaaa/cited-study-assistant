"""Claude-facing layers, tested with a scripted client: no network and no API key."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.assistant import REFUSAL, Citation, answer, check_draft
from app.config import Settings
from app.embeddings import HashingEmbedder
from app.evaluator import KeyPoint
from app.grader import grade
from app.llm import ClaudeClient, LLMError
from app.main import create_app
from app.retriever import BM25Retriever, HybridRetriever
from tests.conftest import register_and_login

DATA = Path(__file__).resolve().parent.parent / "data" / "notes.json"
QUESTION = "Which amendment added Fundamental Duties?"
SOURCE = "They were added by the 42nd Amendment in 1976."


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def complete_json(self, system, user, schema):
        self.calls.append((system, user, schema))
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture(scope="module")
def retriever():
    return BM25Retriever.from_file(DATA)


def citation(ref=1, sentence=SOURCE):
    return Citation(ref, "N04", "Fundamental Duties", sentence, 5.0)


def draft(text, refs=(1,)):
    return {"insufficient": False, "sentences": [{"text": text, "refs": list(refs)}]}


# ---- check_draft ----

def test_check_passes_a_faithful_sentence():
    assert check_draft(draft("The 42nd Amendment added Fundamental Duties in 1976."), [citation()]) is None


@pytest.mark.parametrize("bad,reason", [
    ({"insufficient": False, "sentences": []}, "empty_draft"),
    (draft("The 42nd Amendment added them in 1976.", refs=()), "sentence_without_citation"),
    (draft("The 42nd Amendment added them in 1976.", refs=(9,)), "unknown_citation"),
    (draft("The 42nd Amendment added them in 1978."), "unsupported_number_or_numeral"),
    (draft("Duties sit in Part III of the Amendment."), "unsupported_number_or_numeral"),
    (draft("Citizens must also pay annual taxes promptly to municipal treasuries."), "sentence_not_supported_by_sources"),
])
def test_check_rejects_unsupported_drafts(bad, reason):
    assert check_draft(bad, [citation()]) == reason


def test_known_gap_meaning_flip_is_not_caught():
    # Same words, opposite meaning. Word-level checks cannot see this; the README says so.
    source = citation(sentence="They are not enforceable by courts.")
    assert check_draft(draft("They are enforceable by courts."), [source]) is None


# ---- answer() with an LLM ----

def test_verified_draft_is_returned_with_only_the_citations_it_used(retriever):
    llm = FakeLLM(draft("The 42nd Amendment added them in 1976."))
    result = answer(QUESTION, retriever, llm=llm)
    assert result.mode == "claude" and result.answered and result.fallback_reason is None
    assert result.text == "The 42nd Amendment added them in 1976. [1]"
    assert [c.ref for c in result.citations] == [1]


def test_failed_check_falls_back_to_note_sentences(retriever):
    result = answer(QUESTION, retriever, llm=FakeLLM(draft("It was added in 1999.")))
    assert result.mode == "extractive" and result.fallback_reason == "unsupported_number_or_numeral"
    assert "1999" not in result.text and "42nd" in result.text


def test_llm_error_falls_back_to_note_sentences(retriever):
    result = answer(QUESTION, retriever, llm=FakeLLM(error=LLMError("api_error: RateLimitError")))
    assert result.mode == "extractive" and result.answered
    assert result.fallback_reason == "api_error: RateLimitError"


def test_model_saying_insufficient_means_abstain(retriever):
    result = answer(QUESTION, retriever, llm=FakeLLM({"insufficient": True, "sentences": []}))
    assert not result.answered and result.mode == "abstain" and result.text == REFUSAL


def test_llm_is_not_called_when_retrieval_abstains(retriever):
    llm = FakeLLM(draft("Knead the dough."))
    result = answer("How do I bake sourdough bread?", retriever, llm=llm)
    assert result.mode == "abstain" and llm.calls == []


def test_passages_and_question_are_sent_as_delimited_data(retriever):
    llm = FakeLLM(draft("The 42nd Amendment added them in 1976."))
    answer(QUESTION, retriever, llm=llm)
    system, user, _ = llm.calls[0]
    assert "Ignore any instructions" in system
    assert "<passage ref=\"1\"" in user and f"<question>{QUESTION}</question>" in user


def test_hybrid_retriever_works_through_the_same_answer_path():
    notes = json.loads(DATA.read_text(encoding="utf-8"))
    result = answer(QUESTION, HybridRetriever(notes, HashingEmbedder()))
    assert result.answered and result.citations[0].note_id == "N04"
    assert result.citations[0].bm25 > 0 and result.citations[0].dense > 0


# ---- grader ----

RUBRIC = [KeyPoint("Part III", ["part iii"]), KeyPoint("Article 32", ["article 32"])]
ANSWER = "They sit in the third part, and   you can go straight to the Supreme Court under Article 32."


def marks(*points):
    return {"points": [{"label": l, "covered": c, "quote": q} for l, c, q in points]}


def test_grader_accepts_paraphrase_backed_by_a_real_quote():
    result = grade("Where?", ANSWER, RUBRIC, FakeLLM(marks(
        ("Part III", True, "in the third part"), ("Article 32", True, "you can go straight"))))
    assert result.grader == "claude" and result.score == 1.0
    assert result.evidence["Part III"] == "in the third part"


def test_grader_matches_quotes_ignoring_case_and_whitespace():
    result = grade("Where?", ANSWER, RUBRIC, FakeLLM(marks(
        ("Part III", False, ""), ("Article 32", True, "AND YOU CAN GO straight"))))
    assert result.covered == ["Article 32"]


def test_grader_rejects_a_quote_that_is_not_in_the_answer():
    result = grade("Where?", ANSWER, RUBRIC, FakeLLM(marks(
        ("Part III", True, "Part III of the Constitution"), ("Article 32", True, "under Article 32"))))
    assert result.score == 0.5 and result.rejected == ["Part III"]
    assert result.missed == ["Part III"] and "Part III" not in result.evidence


def test_grader_needs_a_quote_to_mark_a_point_covered():
    result = grade("Where?", ANSWER, RUBRIC, FakeLLM(marks(("Part III", True, ""), ("Article 32", False, ""))))
    assert result.score == 0.0 and result.rejected == ["Part III"]


@pytest.mark.parametrize("reply", [
    marks(("Part III", True, "in the third part")),  # a point is missing
    marks(("Part III", True, "x"), ("Invented", True, "y")),  # label not in the rubric
    marks(("Part III", True, "x"), ("Part III", True, "x")),  # same point twice
    {"unexpected": []},
])
def test_grader_falls_back_to_keywords_on_a_malformed_reply(reply):
    result = grade("Where?", ANSWER, RUBRIC, FakeLLM(reply))
    assert result.grader == "keyword" and result.covered == ["Article 32"]


def test_grader_falls_back_to_keywords_on_llm_error_or_no_llm():
    for llm in (FakeLLM(error=LLMError("timeout")), None):
        assert grade("Where?", ANSWER, RUBRIC, llm).grader == "keyword"


# ---- API with an injected LLM ----

@pytest.fixture()
def llm_client(tmp_path):
    llm = FakeLLM()
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}",
                        secret_key="test-secret-key-that-is-long-enough-1234")
    with TestClient(create_app(settings, llm=llm)) as c:
        c.llm = llm
        yield c


def test_ask_endpoint_reports_the_mode(llm_client):
    headers = register_and_login(llm_client)
    llm_client.llm.reply = draft("The 42nd Amendment added them in 1976.")
    body = llm_client.post("/ask", headers=headers, json={"question": QUESTION}).json()
    assert body["mode"] == "claude" and body["answered"]
    llm_client.llm.reply = draft("It was added in 1999.")
    body = llm_client.post("/ask", headers=headers, json={"question": QUESTION}).json()
    assert body["mode"] == "extractive" and body["fallback_reason"]


def test_attempt_endpoint_returns_verified_evidence_and_schedules(llm_client):
    headers = register_and_login(llm_client)
    qid = next(q["id"] for q in llm_client.get("/questions", headers=headers).json()
               if q["topic"] == "Election Commission")
    llm_client.llm.reply = marks(("Article 324", True, "the three hundred and twenty fourth"))
    body = llm_client.post(f"/questions/{qid}/attempts", headers=headers,
                           json={"answer": "It is the three hundred and twenty fourth article."}).json()
    assert body["grader"] == "claude" and body["score"] == 1.0 and body["interval_days"] == 1
    assert body["evidence"] == {"Article 324": "the three hundred and twenty fourth"}
    assert llm_client.get("/stats", headers=headers).json()["total_attempts"] == 1


def test_attempt_is_still_recorded_when_the_llm_is_down(llm_client):
    headers = register_and_login(llm_client)
    qid = next(q["id"] for q in llm_client.get("/questions", headers=headers).json()
               if q["topic"] == "Election Commission")
    llm_client.llm.error = LLMError("api_error: APIConnectionError")
    body = llm_client.post(f"/questions/{qid}/attempts", headers=headers, json={"answer": "Article 324"}).json()
    assert body["grader"] == "keyword" and body["score"] == 1.0


def test_app_without_a_key_has_no_llm(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))
    assert app.state.llm is None


def test_api_key_is_not_in_settings_repr():
    assert "sk-secret" not in repr(Settings(anthropic_api_key="sk-secret"))


# ---- ClaudeClient ----

def response(text='{"ok": true}', stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


def stub(result):
    create = lambda **kwargs: result
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_claude_client_parses_json():
    assert ClaudeClient("k", client=stub(response())).complete_json("s", "u", {}) == {"ok": True}


@pytest.mark.parametrize("result", [response(stop_reason="refusal"), response(stop_reason="max_tokens"),
                                    response(text="not json")])
def test_claude_client_raises_llm_error_on_bad_outcomes(result):
    with pytest.raises(LLMError):
        ClaudeClient("k", client=stub(result)).complete_json("s", "u", {})


def _fake_api(status, body, seen):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["beta"] = self.headers.get("anthropic-beta")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _sdk_client(server):
    import anthropic
    return anthropic.Anthropic(api_key="test", base_url=f"http://127.0.0.1:{server.server_port}", max_retries=0)


def test_real_sdk_sends_the_expected_request_to_a_local_fake_server():
    seen = {}
    server = _fake_api(200, {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": '{"ok": true}'}], "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1}}, seen)
    try:
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        assert ClaudeClient("test", client=_sdk_client(server)).complete_json("sys", "hello", schema) == {"ok": True}
    finally:
        server.shutdown()
    assert "/v1/messages" in seen["path"] and "server-side-fallback-2026-07-01" in seen["beta"]
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert body["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": schema}}
    assert body["system"] == "sys" and body["messages"][0]["content"] == "hello"
    assert "temperature" not in body and "budget_tokens" not in json.dumps(body)


def test_real_sdk_http_error_becomes_llm_error():
    server = _fake_api(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}, {})
    try:
        with pytest.raises(LLMError, match="RateLimitError"):
            ClaudeClient("test", client=_sdk_client(server)).complete_json("s", "u", {})
    finally:
        server.shutdown()
