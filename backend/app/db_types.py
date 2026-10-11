"""Embedding column type: pgvector in Postgres, JSON float list in SQLite tests."""

import json

from sqlalchemy import JSON, TypeDecorator
from sqlalchemy.types import UserDefinedType

from app.config import DATABASE_URL, EMBEDDING_DIM


class _SqliteEmbedding(TypeDecorator):
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return list(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value


def embedding_column():
    if DATABASE_URL.startswith("sqlite"):
        return _SqliteEmbedding()
    from pgvector.sqlalchemy import Vector

    return Vector(EMBEDDING_DIM)
