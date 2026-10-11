import pytest

from app.services.chunker import chunk_file


def test_python_function_chunk():
    source = "def add(a, b):\n    return a + b\n"
    chunks = chunk_file("app/math.py", source, "code")
    assert len(chunks) == 1
    assert chunks[0].symbol_name == "add"
    assert "function: add" in chunks[0].content


def test_empty_file_returns_no_chunks():
    assert chunk_file("empty.py", "   \n", "code") == []


def test_syntax_error_falls_back_to_window():
    source = "def broken(:\n    pass\n" + "\n".join(f"x = {i}" for i in range(80))
    chunks = chunk_file("broken.py", source, "code")
    assert chunks
    assert any(chunk.kind == "window" for chunk in chunks)


def test_huge_function_is_split():
    body = "\n".join(f"    value = {i}" for i in range(400))
    source = f"def huge():\n{body}\n"
    chunks = chunk_file("big.py", source, "code")
    assert len(chunks) > 1


def test_markdown_doc_chunks():
    text = "# Title\n\nIntro paragraph.\n\n## Section\n\nMore text here.\n"
    chunks = chunk_file("docs/spec.md", text, "doc")
    assert chunks
    assert all(chunk.source_type == "doc" for chunk in chunks)
