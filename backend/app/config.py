"""Limits and the model name. Change the model here (or via GEMINI_MODEL)."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load before reading MODEL_NAME. Repo root first, then backend/.env.
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")
load_dotenv()

# Models the UI may offer. Edit this list to add or rename options.
# id -> short label shown in the dropdown.
AVAILABLE_MODELS: dict[str, str] = {
    "gemini-3.8-flash": "Gemini 3.8 Flash",
    "gemini-3.7-flash": "Gemini 3.7 Flash",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
}

# Default when the client omits `model`, or when GEMINI_MODEL is unset.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
if DEFAULT_MODEL not in AVAILABLE_MODELS:
    # Keep startup simple: fall back to the first allowlisted model.
    DEFAULT_MODEL = next(iter(AVAILABLE_MODELS))

# Kept for older imports / docs. Prefer DEFAULT_MODEL + AVAILABLE_MODELS.
MODEL_NAME = DEFAULT_MODEL


def resolve_model(choice: str | None) -> str:
    """Return an allowlisted model id, or raise ValueError."""
    model = (choice or DEFAULT_MODEL).strip()
    if model not in AVAILABLE_MODELS:
        allowed = ", ".join(AVAILABLE_MODELS)
        raise ValueError(f"Unsupported model '{model}'. Choose one of: {allowed}.")
    return model

# Postgres. Create the database in pgAdmin first, then point this URL at it.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/code_reviewer",
)

# Sign JWTs. Change this in .env before any real use.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-me")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days
JWT_ALGORITHM = "HS256"

# Original single-file limit, kept for every source file.
CODE_MAX_BYTES = 200 * 1024

# PDFs and Word docs are binary, so they get a larger cap than source files.
CONTEXT_MAX_BYTES = 2 * 1024 * 1024

ZIP_MAX_BYTES = 5 * 1024 * 1024
# Uncompressed total, so a tiny zip cannot expand into a huge review.
ZIP_MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
ZIP_MAX_MEMBERS = 500
# How many source files we will actually send to the model in one request.
MAX_REVIEW_FILES = 20
MAX_UPLOADS = 20

# Extra context is pasted into the prompt in Phase 1 (no retrieval yet).
MAX_CONTEXT_CHARS = 30_000

# Vite's default dev server. Both hosts so localhost and 127.0.0.1 work.
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Extensions we treat as source and review one-by-one.
CODE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".java", ".go", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh",
    ".cs", ".rb", ".php", ".rs", ".kt", ".kts", ".swift", ".scala",
    ".sql", ".sh", ".bash", ".html", ".css", ".scss", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml", ".xml",
}

# Specs, design notes, and standards. Text is extracted and passed as context.
CONTEXT_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}

# Directory names dropped from zip archives. We never want dependencies or VCS.
JUNK_DIR_NAMES = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "__MACOSX", ".svn", ".hg", "dist", "build",
}

# --- Phase 2: embeddings + RAG ---
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
EMBEDDING_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "5"))

MAX_PROJECT_FILES = int(os.getenv("MAX_PROJECT_FILES", "300"))
MAX_PROJECT_CHUNKS = int(os.getenv("MAX_PROJECT_CHUNKS", "3000"))
PROJECT_ZIP_MAX_BYTES = int(os.getenv("PROJECT_ZIP_MAX_BYTES", str(10 * 1024 * 1024)))
PROJECT_ZIP_MAX_UNCOMPRESSED_BYTES = int(os.getenv("PROJECT_ZIP_MAX_UNCOMPRESSED_BYTES", str(20 * 1024 * 1024)))

CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "6000"))
CHUNK_WINDOW_LINES = int(os.getenv("CHUNK_WINDOW_LINES", "60"))
CHUNK_WINDOW_OVERLAP = int(os.getenv("CHUNK_WINDOW_OVERLAP", "10"))
DOC_CHUNK_TARGET_CHARS = int(os.getenv("DOC_CHUNK_TARGET_CHARS", "3000"))

RETRIEVAL_CODE_TOP_K = int(os.getenv("RETRIEVAL_CODE_TOP_K", "8"))
RETRIEVAL_DOC_TOP_N = int(os.getenv("RETRIEVAL_DOC_TOP_N", "3"))
RETRIEVAL_CONTEXT_MAX_CHARS = int(os.getenv("RETRIEVAL_CONTEXT_MAX_CHARS", "24000"))
CHAT_RETRIEVAL_TOP_K = int(os.getenv("CHAT_RETRIEVAL_TOP_K", "12"))
CHAT_HISTORY_MAX_TURNS = int(os.getenv("CHAT_HISTORY_MAX_TURNS", "8"))

# --- Phase 3: agentic pipeline ---
AGENT_LLM_CALL_BUDGET = int(os.getenv("AGENT_LLM_CALL_BUDGET", "10"))
AGENT_NODE_TIMEOUT_SECONDS = float(os.getenv("AGENT_NODE_TIMEOUT_SECONDS", "90"))
AGENT_EVIDENCE_MAX_CHARS = int(os.getenv("AGENT_EVIDENCE_MAX_CHARS", "24000"))
# model_tier -> model id (provider/key still come from the selected ModelRuntime)
AGENT_CHEAP_MODEL = os.getenv("AGENT_CHEAP_MODEL", "gemini-3.8-flash")
AGENT_STRONG_MODEL = os.getenv("AGENT_STRONG_MODEL", "gemini-2.5-pro")

LANGUAGE_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".rs": "rust",
    ".kt": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".php": "php",
    ".sql": "sql",
    ".sh": "shell",
    ".md": "markdown",
    ".txt": "text",
}
