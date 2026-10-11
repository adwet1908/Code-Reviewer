"""Use an in-memory SQLite DB for tests so Postgres is not required."""

import os

# Must run before app modules read config / create the engine.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-not-for-production-32b"
os.environ.setdefault("GEMINI_API_KEY", "test-key")
