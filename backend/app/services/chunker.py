"""Split source and docs into embeddable chunks. No LLM calls here."""

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import (
    CHUNK_MAX_CHARS,
    CHUNK_WINDOW_LINES,
    CHUNK_WINDOW_OVERLAP,
    DOC_CHUNK_TARGET_CHARS,
    LANGUAGE_BY_EXT,
)

try:
    from tree_sitter_language_pack import get_parser

    _TREE_SITTER = True
except ImportError:
    _TREE_SITTER = False


@dataclass
class ChunkDraft:
    path: str
    start_line: int
    end_line: int
    symbol_name: str | None
    kind: str
    source_type: str  # code | doc
    content: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return LANGUAGE_BY_EXT.get(suffix, "text")


def chunk_file(path: str, text: str, source_type: str) -> list[ChunkDraft]:
    if not text.strip():
        return []
    if source_type == "doc":
        return _chunk_doc(path, text)
    language = language_for_path(path)
    if language == "python":
        drafts = _chunk_python(path, text)
        if drafts:
            return _enforce_max_size(drafts)
    if _TREE_SITTER and language in {"javascript", "typescript", "java", "go", "cpp", "c", "rust"}:
        drafts = _chunk_tree_sitter(path, text, language)
        if drafts:
            return _enforce_max_size(drafts)
    return _enforce_max_size(_chunk_window(path, text, kind="window"))


def _chunk_python(path: str, text: str) -> list[ChunkDraft]:
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _chunk_window(path, text, kind="window")

    drafts: list[ChunkDraft] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            drafts.append(_ast_node_chunk(path, lines, node, "function", node.name))
        elif isinstance(node, ast.ClassDef):
            drafts.append(_ast_node_chunk(path, lines, node, "class", node.name))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    drafts.append(
                        _ast_node_chunk(path, lines, child, "method", f"{node.name}.{child.name}")
                    )
    if not drafts:
        return _chunk_window(path, text, kind="module")
    return drafts


def _ast_node_chunk(path: str, lines: list[str], node: ast.AST, kind: str, symbol: str) -> ChunkDraft:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    body = "\n".join(lines[start - 1 : end])
    header = f"# path: {path} | {kind}: {symbol}"
    return ChunkDraft(
        path=path,
        start_line=start,
        end_line=end,
        symbol_name=symbol,
        kind=kind,
        source_type="code",
        content=f"{header}\n{body}",
    )


def _chunk_tree_sitter(path: str, text: str, language: str) -> list[ChunkDraft]:
    parser = get_parser(language)
    tree = parser.parse(text.encode("utf-8"))
    lines = text.splitlines()
    drafts: list[ChunkDraft] = []

    def walk(node):
        if node.type in {"function_declaration", "function_definition", "method_definition", "class_declaration"}:
            start_row = node.start_point[0]
            end_row = node.end_point[0]
            symbol = _node_name(node) or node.type
            kind = "class" if "class" in node.type else "function"
            body = "\n".join(lines[start_row : end_row + 1])
            header = f"// path: {path} | {kind}: {symbol}"
            drafts.append(
                ChunkDraft(
                    path=path,
                    start_line=start_row + 1,
                    end_line=end_row + 1,
                    symbol_name=symbol,
                    kind=kind,
                    source_type="code",
                    content=f"{header}\n{body}",
                )
            )
            return
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return drafts


def _node_name(node) -> str | None:
    for child in node.children:
        if child.type in {"identifier", "type_identifier", "property_identifier"}:
            return child.text.decode("utf-8")
    return None


def _chunk_window(path: str, text: str, kind: str) -> list[ChunkDraft]:
    lines = text.splitlines()
    if not lines:
        return []
    drafts: list[ChunkDraft] = []
    step = max(CHUNK_WINDOW_LINES - CHUNK_WINDOW_OVERLAP, 1)
    index = 0
    while index < len(lines):
        window = lines[index : index + CHUNK_WINDOW_LINES]
        start = index + 1
        end = index + len(window)
        header = f"# path: {path} | window: {start}-{end}"
        drafts.append(
            ChunkDraft(
                path=path,
                start_line=start,
                end_line=end,
                symbol_name=None,
                kind=kind,
                source_type="code",
                content=f"{header}\n" + "\n".join(window),
            )
        )
        index += step
    return drafts


def _chunk_doc(path: str, text: str) -> list[ChunkDraft]:
    sections = re.split(r"(?m)^(?=#{1,3}\s+)", text)
    if len(sections) <= 1:
        return _chunk_doc_paragraphs(path, text)
    drafts: list[ChunkDraft] = []
    line_offset = 1
    for section in sections:
        section = section.strip()
        if not section:
            continue
        section_lines = section.splitlines()
        start = line_offset
        end = line_offset + len(section_lines) - 1
        line_offset = end + 2
        title = section_lines[0].lstrip("# ").strip() if section_lines else "section"
        header = f"# path: {path} | doc_section: {title}"
        content = f"{header}\n{section}"
        if len(content) > CHUNK_MAX_CHARS:
            drafts.extend(_chunk_doc_paragraphs(path, section))
        else:
            drafts.append(
                ChunkDraft(
                    path=path,
                    start_line=start,
                    end_line=end,
                    symbol_name=title,
                    kind="doc_section",
                    source_type="doc",
                    content=content,
                )
            )
    return drafts or _chunk_doc_paragraphs(path, text)


def _chunk_doc_paragraphs(path: str, text: str) -> list[ChunkDraft]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return []
    drafts: list[ChunkDraft] = []
    buffer = ""
    buffer_start = 1
    line_no = 1
    for paragraph in paragraphs:
        para_lines = paragraph.count("\n") + 1
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) > DOC_CHUNK_TARGET_CHARS and buffer:
            drafts.append(
                ChunkDraft(
                    path=path,
                    start_line=buffer_start,
                    end_line=line_no - 1,
                    symbol_name=None,
                    kind="doc_section",
                    source_type="doc",
                    content=f"# path: {path} | doc_section\n{buffer}",
                )
            )
            buffer = paragraph
            buffer_start = line_no
        else:
            buffer = candidate
        line_no += para_lines + 1
    if buffer:
        drafts.append(
            ChunkDraft(
                path=path,
                start_line=buffer_start,
                end_line=line_no,
                symbol_name=None,
                kind="doc_section",
                source_type="doc",
                content=f"# path: {path} | doc_section\n{buffer}",
            )
        )
    return drafts


def _enforce_max_size(drafts: list[ChunkDraft]) -> list[ChunkDraft]:
    out: list[ChunkDraft] = []
    for draft in drafts:
        if len(draft.content) <= CHUNK_MAX_CHARS:
            out.append(draft)
            continue
        # Oversized symbol: fall back to windows on the chunk body only.
        body_lines = draft.content.splitlines()[1:]
        sub = _chunk_window(draft.path, "\n".join(body_lines), kind="window")
        out.extend(sub)
    return out
