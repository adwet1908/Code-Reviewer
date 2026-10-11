"""Built-in Gemini models plus per-user custom endpoints."""

import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AVAILABLE_MODELS, DEFAULT_MODEL
from app.models import User, UserModel
from app.schemas import ModelOption, ModelsResponse
from app.services.secrets import decrypt_secret

CUSTOM_PREFIX = "custom:"
MAX_CUSTOM_MODELS = 20
PROVIDERS = ("gemini", "openai", "anthropic")


@dataclass(frozen=True)
class ModelRuntime:
    selection_id: str
    model_id: str
    provider: str
    api_key: str
    base_url: str | None = None


def custom_selection_id(model_pk: int) -> str:
    return f"{CUSTOM_PREFIX}{model_pk}"


def list_models_for_user(db: Session, user: User | None) -> ModelsResponse:
    models = [
        ModelOption(id=model_id, label=label, source="builtin", provider="gemini")
        for model_id, label in AVAILABLE_MODELS.items()
    ]
    allowed = {item.id for item in models}
    if user is not None:
        rows = db.scalars(select(UserModel).where(UserModel.user_id == user.id).order_by(UserModel.id)).all()
        for row in rows:
            sid = custom_selection_id(row.id)
            models.append(
                ModelOption(
                    id=sid,
                    label=row.label,
                    source="custom",
                    provider=row.provider,
                )
            )
            allowed.add(sid)
    default = DEFAULT_MODEL
    if user and user.default_model and user.default_model in allowed:
        default = user.default_model
    return ModelsResponse(default=default, models=models)


def resolve_runtime(db: Session, user: User, choice: str | None) -> ModelRuntime:
    catalog = list_models_for_user(db, user)
    selected = (choice or catalog.default or DEFAULT_MODEL).strip()
    if selected in AVAILABLE_MODELS:
        api_key = os.getenv("GEMINI_API_KEY") or ""
        return ModelRuntime(
            selection_id=selected,
            model_id=selected,
            provider="gemini",
            api_key=api_key,
        )
    if selected.startswith(CUSTOM_PREFIX):
        try:
            pk = int(selected.removeprefix(CUSTOM_PREFIX))
        except ValueError as exc:
            raise ValueError(f"Unsupported model '{selected}'.") from exc
        row = db.scalar(select(UserModel).where(UserModel.id == pk, UserModel.user_id == user.id))
        if row is None:
            raise ValueError(f"Unsupported model '{selected}'.")
        return ModelRuntime(
            selection_id=selected,
            model_id=row.model_id,
            provider=row.provider,
            api_key=decrypt_secret(row.api_key_encrypted),
            base_url=row.base_url,
        )
    allowed = ", ".join(item.id for item in catalog.models)
    raise ValueError(f"Unsupported model '{selected}'. Choose one of: {allowed}.")


def set_default_model(db: Session, user: User, selection_id: str) -> str:
    catalog = list_models_for_user(db, user)
    allowed = {item.id for item in catalog.models}
    if selection_id not in allowed:
        raise ValueError("That model is not available.")
    user.default_model = selection_id
    db.commit()
    return selection_id
