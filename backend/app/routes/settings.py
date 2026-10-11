"""User settings: custom models and default model."""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User, UserModel
from app.schemas import DefaultModelRequest, UserModelCreate, UserModelOut, UserModelUpdate
from app.services.model_catalog import (
    MAX_CUSTOM_MODELS,
    PROVIDERS,
    custom_selection_id,
    set_default_model,
)
from app.services.secrets import encrypt_secret, key_hint

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/models", response_model=list[UserModelOut])
def list_user_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[UserModelOut]:
    rows = db.scalars(select(UserModel).where(UserModel.user_id == user.id).order_by(UserModel.id)).all()
    return [_to_out(row) for row in rows]


@router.post("/models", response_model=UserModelOut)
def create_user_model(
    body: UserModelCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserModelOut:
    count = len(db.scalars(select(UserModel.id).where(UserModel.user_id == user.id)).all())
    if count >= MAX_CUSTOM_MODELS:
        raise HTTPException(status_code=400, detail=f"You can save at most {MAX_CUSTOM_MODELS} custom models.")
    row = UserModel(
        user_id=user.id,
        label=body.label.strip(),
        provider=_validate_provider(body.provider),
        model_id=body.model_id.strip(),
        api_key_encrypted=encrypt_secret(body.api_key.strip()),
        api_key_hint=key_hint(body.api_key),
        base_url=_validate_base_url(body.provider, body.base_url),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.patch("/models/{model_pk}", response_model=UserModelOut)
def update_user_model(
    model_pk: int,
    body: UserModelUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserModelOut:
    row = _owned_model(db, user.id, model_pk)
    if body.label is not None:
        row.label = body.label.strip()
    if body.provider is not None:
        row.provider = _validate_provider(body.provider)
    if body.model_id is not None:
        row.model_id = body.model_id.strip()
    if body.api_key is not None:
        row.api_key_encrypted = encrypt_secret(body.api_key.strip())
        row.api_key_hint = key_hint(body.api_key)
    if body.base_url is not None:
        row.base_url = _validate_base_url(row.provider, body.base_url)
    elif body.provider is not None:
        row.base_url = _validate_base_url(row.provider, row.base_url)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/models/{model_pk}", response_model=UserModelOut)
def delete_user_model(
    model_pk: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserModelOut:
    row = _owned_model(db, user.id, model_pk)
    out = _to_out(row)
    if user.default_model == custom_selection_id(row.id):
        user.default_model = None
    db.delete(row)
    db.commit()
    return out


@router.put("/default-model")
def update_default_model(
    body: DefaultModelRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        selected = set_default_model(db, user, body.model.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"default": selected}


def _owned_model(db: Session, user_id: int, model_pk: int) -> UserModel:
    row = db.scalar(select(UserModel).where(UserModel.id == model_pk, UserModel.user_id == user_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Custom model not found.")
    return row


def _validate_provider(provider: str) -> str:
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Provider must be gemini, openai, or anthropic.")
    return provider


def _validate_base_url(provider: str, base_url: str | None) -> str | None:
    value = (base_url or "").strip() or None
    if provider != "openai":
        return None
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Base URL must be an http(s) URL, for example https://api.openai.com/v1")
    return value.rstrip("/")


def _to_out(row: UserModel) -> UserModelOut:
    return UserModelOut(
        id=row.id,
        selection_id=custom_selection_id(row.id),
        label=row.label,
        provider=row.provider,
        model_id=row.model_id,
        api_key_hint=row.api_key_hint,
        base_url=row.base_url,
    )
