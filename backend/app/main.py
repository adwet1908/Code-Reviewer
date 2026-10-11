"""FastAPI app. Auth first, then review routes."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import CORS_ORIGINS, DEFAULT_MODEL
from app.db import get_db, init_db
from app.deps import get_current_user, get_optional_user
from app.routes.projects import router as projects_router
from app.routes.settings import router as settings_router
from app.models import User
from app.services.model_catalog import list_models_for_user, resolve_runtime
from app.schemas import (
    FileReview,
    LoginRequest,
    ModelsResponse,
    RegisterRequest,
    ReviewResponse,
    TokenResponse,
    UserOut,
)
from app.services.auth import AuthError, authenticate_user, create_access_token, register_user
from app.services.ingest import IngestError, format_context, ingest_uploads, number_lines
from app.services.llm import LLMError, review_code


@asynccontextmanager
async def lifespan(_: FastAPI):
    import logging

    log = logging.getLogger("uvicorn.error")
    try:
        log.info("Starting database setup…")
        init_db()
        # Fail loudly if Phase 3 agent SKILL.md files are missing/malformed.
        from app.agents.skill_loader import load_all_agent_skills, load_language_skill

        load_all_agent_skills()
        load_language_skill("generic")
        log.info("Agent skills loaded.")
    except Exception as exc:
        log.error("Startup failed during database setup: %s", exc)
        raise
    yield


app = FastAPI(title="AI Code Reviewer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(settings_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        user = register_user(db, body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        user = authenticate_user(db, body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@app.get("/models", response_model=ModelsResponse)
def list_models(user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)) -> ModelsResponse:
    """Built-in models plus the signed-in user's custom models."""
    return list_models_for_user(db, user)


@app.post("/review", response_model=ReviewResponse)
def review(
    files: list[UploadFile] = File(...),
    model: str = Form(DEFAULT_MODEL),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewResponse:
    # Sync on purpose: the Gemini client call is blocking.
    # `user` is required so anonymous callers cannot spend API quota.
    try:
        runtime = resolve_runtime(db, user, model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        batch = ingest_uploads(files)
    except IngestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    context = format_context(batch.context_docs)
    reviews: list[FileReview] = []
    for code_file in batch.code_files:
        numbered = number_lines(code_file.text)
        try:
            result = review_code(numbered, code_file.name, context, runtime)
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        reviews.append(FileReview(filename=code_file.name, review=result))
    return ReviewResponse(files=reviews, model=runtime.model_id)
