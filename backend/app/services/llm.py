"""LLM calls. Gemini uses google-genai; OpenAI-compatible and Anthropic use HTTP."""

import json
import os
import re
from typing import TypeVar

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.schemas import Review
from app.services.model_catalog import ModelRuntime

TModel = TypeVar("TModel", bound=BaseModel)

SYSTEM_PROMPT = """You are a careful code reviewer.

Review only the numbered source file. Extra context (specs, design notes, coding standards) is background: use it when it changes what is correct, but do not review the context itself.

Rules:
- Cite locations using the line numbers already printed on each source line (for example "12" or "12-18").
- Report real defects and concrete risks. Skip style nits that do not affect correctness, security, or clarity.
- severity is one of: critical, high, medium, low.
- category is one of: bug, edge_case, security, performance, readability.
- If the file looks fine, return an empty findings list and say so in the summary.
- Do not invent files, functions, or line numbers that are not in the source.
"""

CHAT_SYSTEM_PROMPT = """You help developers understand their codebase.

You receive retrieved snippets from the repository (code and docs). Answer the user's question using that material.

Rules:
- Prefer concrete answers grounded in the snippets. Mention file paths and line ranges when useful.
- If the snippets do not contain enough information, say what is missing instead of guessing.
- Do not invent files, APIs, or behavior that are not supported by the snippets or the conversation.
- Use markdown for code fences and short lists when it improves clarity.
"""

RAG_SYSTEM_PROMPT = """You are a careful code reviewer working inside a repository.

Review ONLY the numbered TARGET file. Related code and project standards are background context.

Rules:
- Every finding must cite a location in the TARGET file using its printed line numbers.
- Use related repo context to catch cross-file issues (wrong signatures, broken imports, API misuse, standards violations).
- When a finding depends on retrieved context, fill the optional evidence list with the supporting path and line ranges.
- severity is one of: critical, high, medium, low.
- category is one of: bug, edge_case, security, performance, readability.
- Do not invent files, functions, or line numbers.
- Do not report issues that exist only in the related context sections.
"""

_REVIEW_JSON_INSTRUCTION = """
Return ONLY valid JSON with this shape:
{"summary": string, "findings": [{"severity": "critical"|"high"|"medium"|"low", "category": "bug"|"edge_case"|"security"|"performance"|"readability", "location": string, "issue": string, "suggestion": string, "evidence": [{"path": string, "start_line": number, "end_line": number}] | null}]}
"""


class LLMError(Exception):
    """The model call failed or returned something we cannot use."""


def review_code(
    numbered_source: str,
    filename: str,
    context: str,
    runtime: ModelRuntime,
    related_code: str = "",
    related_docs: str = "",
    rag_mode: bool = False,
) -> Review:
    user_prompt = _build_user_prompt(
        filename,
        numbered_source,
        context,
        related_code=related_code,
        related_docs=related_docs,
        rag_mode=rag_mode,
    )
    system = RAG_SYSTEM_PROMPT if rag_mode else SYSTEM_PROMPT
    if runtime.provider == "gemini":
        return _gemini_review(runtime, system, user_prompt)
    text = _complete_text(runtime, system + _REVIEW_JSON_INSTRUCTION, [(None, user_prompt)], json_mode=True)
    return _parse_review(text)


def generate_structured(
    runtime: ModelRuntime,
    system: str,
    user_prompt: str,
    schema: type[TModel],
    temperature: float = 0.2,
) -> TModel:
    """Structured JSON call used by agentic pipeline nodes. Never logs prompts."""
    if runtime.provider == "gemini":
        return _gemini_structured(runtime, system, user_prompt, schema, temperature)
    instruction = (
        f"{system}\n\nReturn ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema.model_json_schema(), indent=2)}\n"
        "No markdown fences, no prose."
    )
    text = _complete_text(
        runtime,
        instruction,
        [(None, user_prompt)],
        json_mode=True,
    )
    return _parse_model(text, schema)


def chat_about_codebase(
    question: str,
    code_context: str,
    doc_context: str,
    history: list[tuple[str, str]],
    runtime: ModelRuntime,
) -> str:
    """Plain-text Q&A over retrieved repo chunks. history items are (role, content)."""
    parts: list[str] = []
    if code_context:
        parts.extend(["## Retrieved code", code_context])
    if doc_context:
        parts.extend(["", "## Retrieved docs / standards", doc_context])
    if not code_context and not doc_context:
        parts.append("(No matching snippets were retrieved for this question.)")
    parts.extend(["", "## Question", question])
    user_prompt = "\n".join(parts)
    text = _complete_text(runtime, CHAT_SYSTEM_PROMPT, history + [("user", user_prompt)], json_mode=False)
    if not text.strip():
        raise LLMError("The model returned an empty answer.")
    return text.strip()


def _gemini_client(runtime: ModelRuntime) -> genai.Client:
    api_key = runtime.api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("No Gemini API key is configured. Add one in Settings or set GEMINI_API_KEY.")
    return genai.Client(api_key=api_key)


def _gemini_review(runtime: ModelRuntime, system: str, user_prompt: str) -> Review:
    return _gemini_structured(runtime, system, user_prompt, Review, 0.2)


def _gemini_structured(
    runtime: ModelRuntime,
    system: str,
    user_prompt: str,
    schema: type[TModel],
    temperature: float,
) -> TModel:
    client = _gemini_client(runtime)
    try:
        response = client.models.generate_content(
            model=runtime.model_id,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    except Exception as exc:
        raise LLMError(f"Gemini request failed: {exc}") from exc

    parsed = response.parsed
    if isinstance(parsed, schema):
        return parsed
    if isinstance(parsed, dict):
        return schema.model_validate(parsed)
    if response.text:
        return _parse_model(response.text, schema)
    raise LLMError("Gemini returned an empty structured response.")


def _complete_text(
    runtime: ModelRuntime,
    system: str,
    turns: list[tuple[str | None, str]],
    json_mode: bool,
) -> str:
    if runtime.provider == "gemini":
        return _gemini_text(runtime, system, turns)
    if runtime.provider == "openai":
        return _openai_text(runtime, system, turns, json_mode)
    if runtime.provider == "anthropic":
        return _anthropic_text(runtime, system, turns)
    raise LLMError(f"Unsupported provider '{runtime.provider}'.")


def _gemini_text(runtime: ModelRuntime, system: str, turns: list[tuple[str | None, str]]) -> str:
    client = _gemini_client(runtime)
    contents: list[types.Content] = []
    for role, text in turns:
        gemini_role = "user" if role in (None, "user") else "model"
        contents.append(types.Content(role=gemini_role, parts=[types.Part(text=text)]))
    try:
        response = client.models.generate_content(
            model=runtime.model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.3,
            ),
        )
    except Exception as exc:
        raise LLMError(f"Gemini request failed: {exc}") from exc
    return (response.text or "").strip()


def _openai_text(
    runtime: ModelRuntime,
    system: str,
    turns: list[tuple[str | None, str]],
    json_mode: bool,
) -> str:
    if not runtime.api_key:
        raise LLMError("This OpenAI-compatible model has no API key. Add one in Settings.")
    base = (runtime.base_url or "https://api.openai.com/v1").rstrip("/")
    messages = [{"role": "system", "content": system}]
    for role, text in turns:
        messages.append({"role": "assistant" if role == "assistant" else "user", "content": text})
    payload: dict = {
        "model": runtime.model_id,
        "messages": messages,
        "temperature": 0.2 if json_mode else 0.3,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {runtime.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"] or "").strip()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"OpenAI-compatible request failed ({exc.response.status_code}): {exc.response.text[:400]}") from exc
    except Exception as exc:
        raise LLMError(f"OpenAI-compatible request failed: {exc}") from exc


def _anthropic_text(runtime: ModelRuntime, system: str, turns: list[tuple[str | None, str]]) -> str:
    if not runtime.api_key:
        raise LLMError("This Anthropic model has no API key. Add one in Settings.")
    messages = []
    for role, text in turns:
        messages.append({"role": "assistant" if role == "assistant" else "user", "content": text})
    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": runtime.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": runtime.model_id,
                "max_tokens": 4096,
                "system": system,
                "messages": messages,
                "temperature": 0.3,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        blocks = data.get("content") or []
        texts = [block.get("text", "") for block in blocks if block.get("type") == "text"]
        return "\n".join(texts).strip()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"Anthropic request failed ({exc.response.status_code}): {exc.response.text[:400]}") from exc
    except Exception as exc:
        raise LLMError(f"Anthropic request failed: {exc}") from exc


def _parse_review(text: str) -> Review:
    return _parse_model(text, Review)


def _parse_model(text: str, schema: type[TModel]) -> TModel:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return schema.model_validate_json(cleaned)
    except Exception:
        try:
            return schema.model_validate(json.loads(cleaned))
        except Exception as exc:
            raise LLMError(f"The model returned JSON that failed {schema.__name__} validation.") from exc


def _build_user_prompt(
    filename: str,
    numbered_source: str,
    context: str,
    related_code: str,
    related_docs: str,
    rag_mode: bool,
) -> str:
    parts = [f"TARGET file: {filename}", "", "Numbered source:", numbered_source]
    if rag_mode and related_code:
        parts.extend(["", "Related code from the repo (background only):", related_code])
    if rag_mode and related_docs:
        parts.extend(["", "Project standards / docs (background only):", related_docs])
    if context and not rag_mode:
        parts.extend(["", "Extra context. Use it as background. Do not review this text:", context])
    elif context and rag_mode and not related_docs:
        parts.extend(["", "Uploaded standards / docs:", context])
    return "\n".join(parts)
