"""Application factory. Each app owns its engine, so tests get isolated databases."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .config import Settings, load_settings
from .embeddings import make_embedder
from .index_cache import IndexCache
from .llm import ClaudeClient, LLMClient
from .models import Base
from .retriever import BM25Retriever, HybridRetriever
from .routers import auth, notes, study
from .security import LoginThrottle
from .seed import seed_if_empty


def _index_builder(settings: Settings):
    if settings.retrieval == "bm25":
        return BM25Retriever
    embedder = make_embedder(settings.embedder)
    return lambda notes: HybridRetriever(notes, embedder)


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    if llm is None and settings.anthropic_api_key:
        llm = ClaudeClient(settings.anthropic_api_key, settings.anthropic_model)
    connect_args, kwargs = {}, {}
    if settings.database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if ":memory:" in settings.database_url:
            kwargs["poolclass"] = StaticPool  # one shared connection for the in-memory DB
    engine = create_engine(settings.database_url, connect_args=connect_args, **kwargs)
    Base.metadata.create_all(engine)  # no Alembic yet; see README "Limitations"
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        seed_if_empty(db)

    app = FastAPI(title="Cited Study Assistant API")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.index_cache = IndexCache(_index_builder(settings))
    app.state.llm = llm
    app.state.throttle = LoginThrottle()
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(notes.router)
    app.include_router(study.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


def get_app() -> FastAPI:  # for `uvicorn app.main:get_app --factory`
    return create_app()
