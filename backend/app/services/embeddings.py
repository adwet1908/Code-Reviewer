"""All Gemini embedding calls live here."""

import os
import time

from google import genai
from google.genai import types

from app.config import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIM,
    EMBEDDING_MAX_RETRIES,
    EMBEDDING_MODEL,
)
from app.services.vectors import l2_normalize


class EmbeddingError(Exception):
    pass


def embed_documents(texts: list[str]) -> list[list[float]]:
    return _embed_batch(texts, task_type="RETRIEVAL_DOCUMENT")


def embed_query(text: str) -> list[float]:
    vectors = _embed_batch([text], task_type="RETRIEVAL_QUERY")
    return vectors[0]


def _embed_batch(texts: list[str], task_type: str) -> list[list[float]]:
    if not texts:
        return []
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EmbeddingError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=api_key)
    results: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        results.extend(_call_with_retry(client, batch, task_type))
    return results


def _call_with_retry(client: genai.Client, batch: list[str], task_type: str) -> list[list[float]]:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(EMBEDDING_MAX_RETRIES):
        try:
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=EMBEDDING_DIM,
                ),
            )
            vectors: list[list[float]] = []
            for item in response.embeddings or []:
                values = list(item.values)
                vectors.append(l2_normalize(values))
            if len(vectors) != len(batch):
                raise EmbeddingError("Embedding API returned an unexpected number of vectors.")
            return vectors
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            if "429" in message or "resource_exhausted" in message or "quota" in message:
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc
    raise EmbeddingError(f"Embedding quota exceeded after retries: {last_error}")
