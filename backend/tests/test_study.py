import pytest

from app.srs import SrsState, next_state, quality_from_score
from tests.conftest import register_and_login


# ---- spaced repetition (pure logic) ----

def test_quality_mapping_bounds():
    assert quality_from_score(1.0) == 5 and quality_from_score(0.0) == 0
    with pytest.raises(ValueError):
        quality_from_score(1.2)


def test_interval_grows_one_six_then_by_ease():
    s = SrsState()
    s = next_state(s, 5); assert (s.interval_days, s.repetitions) == (1, 1)
    s = next_state(s, 5); assert (s.interval_days, s.repetitions) == (6, 2)
    # ease after two perfect recalls is 2.5 + 0.1 + 0.1 = 2.7, so 6 * 2.7 -> 16 days
    s = next_state(s, 5); assert (s.interval_days, s.repetitions) == (16, 3)


def test_lapse_resets_streak_and_keeps_ease_floor():
    s = SrsState(ease=1.35, interval_days=20, repetitions=5)
    lapsed = next_state(s, 1)
    assert (lapsed.interval_days, lapsed.repetitions) == (1, 0)
    low = next_state(SrsState(ease=1.3, interval_days=6, repetitions=2), 3)
    assert low.ease >= 1.3


# ---- notes + retrieval isolation ----

def test_private_notes_are_isolated_and_searchable_by_owner_only(client):
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    note = client.post("/notes", headers=alice, json={
        "title": "Zebra Facts", "text": "The quagga hypothesis concerns striped equids in savannah herds."})
    assert note.status_code == 201
    q = {"question": "What is the quagga hypothesis?"}
    mine = client.post("/ask", headers=alice, json=q).json()
    theirs = client.post("/ask", headers=bob, json=q).json()
    assert mine["answered"] and "quagga" in mine["text"].lower()
    assert not theirs["answered"]  # Bob cannot retrieve Alice's private note
    assert client.delete(f"/notes/{note.json()['id']}", headers=bob).status_code == 404
    assert client.delete(f"/notes/{note.json()['id']}", headers=alice).status_code == 204
    assert not client.post("/ask", headers=alice, json=q).json()["answered"]  # cache invalidated


def test_shared_seed_notes_visible_but_not_deletable(client, auth):
    notes = client.get("/notes", headers=auth).json()
    shared = [n for n in notes if n["shared"]]
    assert len(shared) == 9
    assert client.delete(f"/notes/{shared[0]['id']}", headers=auth).status_code == 404


def test_ask_requires_auth_and_validates(client, auth):
    assert client.post("/ask", json={"question": "anything"}).status_code == 401
    assert client.post("/ask", headers=auth, json={"question": "hi"}).status_code == 422


# ---- practice, scheduling, stats ----

def _question_id(client, headers, topic):
    return next(q["id"] for q in client.get("/questions", headers=headers).json() if q["topic"] == topic)


def test_attempt_scores_against_rubric_and_schedules_review(client, auth):
    qid = _question_id(client, auth, "Writs")
    full = client.post(f"/questions/{qid}/attempts", headers=auth, json={
        "answer": "Habeas corpus, mandamus, prohibition, certiorari and quo warranto."})
    assert full.status_code == 201
    body = full.json()
    assert body["score"] == 1.0 and body["missed"] == [] and body["interval_days"] == 1

    part = client.post(f"/questions/{qid}/attempts", headers=auth, json={"answer": "Habeas corpus and mandamus"})
    assert part.json()["score"] == 0.4
    assert part.json()["interval_days"] == 1  # lapse: quality 2 < 3
    assert set(part.json()["missed"]) == {"Prohibition", "Certiorari", "Quo warranto"}


def test_due_queue_new_first_then_excludes_scheduled(client, auth):
    due = client.get("/review/due?limit=50", headers=auth).json()
    assert len(due) == 8
    qid = due[0]["id"]
    client.post(f"/questions/{qid}/attempts", headers=auth, json={"answer": "x"})
    # an attempt always schedules at least a day out, so it leaves today's queue
    after = [q["id"] for q in client.get("/review/due?limit=50", headers=auth).json()]
    assert qid not in after and len(after) == 7


def test_users_have_independent_schedules_and_stats(client):
    a = register_and_login(client, "a@example.com")
    b = register_and_login(client, "b@example.com")
    qid = _question_id(client, a, "Election Commission")
    client.post(f"/questions/{qid}/attempts", headers=a, json={"answer": "Article 324"})
    assert client.get("/stats", headers=a).json()["total_attempts"] == 1
    assert client.get("/stats", headers=b).json()["total_attempts"] == 0
    assert len(client.get("/review/due?limit=50", headers=b).json()) == 8


def test_stats_surface_weak_topics(client, auth):
    writs = _question_id(client, auth, "Writs")
    ec = _question_id(client, auth, "Election Commission")
    client.post(f"/questions/{writs}/attempts", headers=auth, json={"answer": "no idea"})
    client.post(f"/questions/{ec}/attempts", headers=auth, json={"answer": "Article 324"})
    s = client.get("/stats", headers=auth).json()
    assert s["total_attempts"] == 2 and s["average_score"] == 0.5
    assert s["weakest_topics"] == ["Writs"]
    assert s["topics"][0]["topic"] == "Writs"  # weakest first


def test_custom_question_is_private_and_attemptable(client):
    a = register_and_login(client, "a@example.com")
    b = register_and_login(client, "b@example.com")
    r = client.post("/questions", headers=a, json={
        "topic": "Mine", "prompt": "Name the capital of France.",
        "rubric": [{"label": "Paris", "variants": ["paris"]}]})
    assert r.status_code == 201
    qid = r.json()["id"]
    assert client.post(f"/questions/{qid}/attempts", headers=a, json={"answer": "Paris"}).json()["score"] == 1.0
    assert client.post(f"/questions/{qid}/attempts", headers=b, json={"answer": "Paris"}).status_code == 404
    assert client.post("/questions/999999/attempts", headers=a, json={"answer": "x"}).status_code == 404


def test_question_rubric_validation(client, auth):
    bad = client.post("/questions", headers=auth, json={"topic": "T", "prompt": "Valid prompt?", "rubric": []})
    assert bad.status_code == 422
    bad2 = client.post("/questions", headers=auth, json={
        "topic": "T", "prompt": "Valid prompt?", "rubric": [{"label": "x", "variants": []}]})
    assert bad2.status_code == 422
