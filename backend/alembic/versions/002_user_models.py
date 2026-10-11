"""Per-user custom models and default model.

Revision ID: 002_user_models
Revises: 001_phase2_rag
Create Date: 2026-10-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_user_models"
down_revision: Union[str, None] = "001_phase2_rag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("default_model", sa.String(length=128), nullable=True))
    op.create_table(
        "user_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("api_key_hint", sa.String(length=8), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_user_models_user_id", "user_models", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_models_user_id", table_name="user_models")
    op.drop_table("user_models")
    op.drop_column("users", "default_model")
