# Cited Study Assistant

> Independent project built by Shivansh Sharma for the AI test-prep / ed-tech domain. Not affiliated with or endorsed by any company. All study notes are original, short, synthetic notes written for this project.

A full-stack study app. Users sign up, ask questions that are answered **only from notes, with a citation on every sentence**, practise written answers scored against a rubric, and get a **spaced-repetition review queue** and **weak-topic stats** driven by their own history. Most of the work is in the backend.

```
React (Vite, TS)  ->  FastAPI  ->  SQLAlchemy  ->  SQLite (dev/tests) or PostgreSQL
                        |-- JWT auth, scrypt hashes, login throttle
                        |-- BM25 retriever + per-user index cache
                        |-- rubric evaluator
                        '-- SM-2-style scheduler
```

## What the backend does

| Area | Detail |
|---|---|
| Auth | `POST /auth/register`, `/auth/login`, `GET /me`. Passwords hashed with scrypt (per-hash salt). JWT (HS256, algorithm pinned, expiry enforced). |
| Brute-force control | Login throttle: 5 failures per email per 5 minutes returns 429. Unknown email and wrong password return the same response and cost the same hashing time. |
| Notes | Shared seed notes plus private per-user notes. A user can never read, retrieve from, or delete another user's notes. |
| Ask | `POST /ask` runs BM25 over the caller's visible notes, returns verbatim note sentences tagged `[n]`, and abstains when evidence is weak. |
| Practice | `POST /questions/{id}/attempts` scores an answer against the question's rubric, stores the attempt, and updates the review schedule **in one transaction**. |
| Review queue | `GET /review/due`: never-attempted questions first, then overdue ones. Each user has an independent schedule. |
| Stats | `GET /stats`: attempts, average, items due, per-topic averages, weakest topics. |
| Custom questions | Users create private questions with their own rubric (validated). |

## Design decisions (and trade-offs)

- **Extractive answers, not generated:** every claim is a real note sentence, so citations are exact and nothing is hallucinated. Cost: it cannot synthesise across notes.
- **BM25 from scratch:** deterministic, no model download, easy to test. Cost: lexical only (see limitations).
- **Index cache with a version counter:** an index is rebuilt only when notes change, not per request. Invalidation is exercised by a test (delete a note, the answer disappears).
- **SM-2 variant:** rubric score maps to quality 0-5. Below 3 the card lapses and returns tomorrow; otherwise intervals go 1, 6, then `previous x ease`, with an ease floor of 1.3.
- **Uniqueness enforced by the database:** registration relies on the unique index and handles `IntegrityError`, rather than check-then-insert, which races.
- **App factory:** `create_app(settings)` gives each test its own database.
- **Production guard:** with `APP_ENV=production` the app refuses to start without a `SECRET_KEY` of at least 32 characters.

## Run it

```bash
# backend
cd backend
pip install -r requirements.txt
python -m pytest -q                                   # 33 tests
uvicorn app.main:get_app --factory --reload           # http://localhost:8000/docs

# frontend (dev server proxies /api to the backend)
cd frontend
npm install && npm run dev                            # http://localhost:5173
```

Docker (Postgres + API + nginx-served client):

```bash
cp .env.example .env     # set real values
docker compose up --build   # http://localhost:8080
```

## Testing status (honest)

- **Verified:** 33 backend tests (auth, throttle window, token forgery/expiry/`alg=none`, tenant isolation, scoring, scheduling, per-user queues, stats, validation); frontend type-checks and builds; the live server was smoke-tested end to end (register, login, ask, attempt, stats, 401 without a token).
- **Not verified:** `docker compose` and the **PostgreSQL** path were written but **not run** in the environment this was built in. SQL is standard SQLAlchemy and should be portable, but treat Postgres as untested until you run it.
- The frontend has no automated tests.
- No `package-lock.json` is committed, so CI and the frontend Dockerfile use `npm install` and dependency versions float within the ranges in `package.json`. Commit a lockfile and switch to `npm ci` for reproducible builds.

## Limitations

- Retrieval is **lexical**: paraphrases with no shared words will miss. Next step: hybrid with dense embeddings and a reranker.
- The corpus is nine short notes. No accuracy or scale benchmark is claimed.
- The abstain threshold and relevance cutoff were set by hand against the test questions, not tuned on held-out data.
- The rubric evaluator is keyword matching and cannot judge reasoning or paraphrase.
- Schema is created with `create_all`; there are **no migrations** (Alembic is the next step).
- The login throttle and index cache are **in-process**: with several workers you would move them to Redis or a database counter.
- JWTs are stored in `localStorage` for simplicity; an httpOnly cookie plus CSRF protection would be safer. There is no token refresh or revocation.

## Likely interview questions

1. Why check-then-insert is racy for registration, and how does the unique index fix it?
2. How does the login path avoid leaking which emails exist (response shape and timing)?
3. Why pin the JWT algorithm, and what is the `alg=none` attack?
4. Walk through SM-2: what happens on a lapse, and why is there an ease floor?
5. Why must the attempt row and the review state commit together? What breaks otherwise?
6. How would the in-memory throttle and index cache behave with 4 workers, and what replaces them?
7. How would you evaluate retrieval quality (recall@k, MRR) and calibrate the abstain threshold properly?
8. Where would N+1 queries appear here, and how does `/review/due` avoid them?
9. localStorage vs httpOnly cookie for the token: trade-offs?
10. How would you add Alembic migrations to a live database?

## Layout

```
backend/app/        main.py (factory), config, models, security, srs, index_cache, seed
backend/app/routers auth, notes, study
backend/app/        retriever.py, assistant.py, evaluator.py
backend/tests/      33 tests
backend/data/       synthetic notes and rubric questions
frontend/           Vite + React + TypeScript client
.github/workflows/  CI (pytest, frontend build)
docker-compose.yml  Postgres + API + web
```
