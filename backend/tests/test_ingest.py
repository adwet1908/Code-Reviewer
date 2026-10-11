"""Ingest rules that do not need a model call."""

import io
import zipfile

import pytest

from app.services.ingest import IngestError, format_context, ingest_bytes, number_lines
from app.services.ingest import TextDocument


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_number_lines_prefixes_each_line():
    numbered = number_lines("alpha\nbeta")
    assert numbered == "1 | alpha\n2 | beta"


def test_rejects_unknown_extension():
    with pytest.raises(IngestError, match="Unsupported file type"):
        ingest_bytes("notes.rtf", b"hello")


def test_rejects_non_utf8_source():
    with pytest.raises(IngestError, match="not valid UTF-8"):
        ingest_bytes("app.py", b"\xff\xfe hello")


def test_rejects_oversize_source():
    payload = b"x" * (200 * 1024 + 1)
    with pytest.raises(IngestError, match="limit"):
        ingest_bytes("app.py", payload)


def test_zip_skips_junk_and_binaries_and_keeps_code_and_context():
    data = _zip({
        "src/app.py": b"print('ok')\n",
        "README.md": b"# spec\n",
        "node_modules/leftpad/index.js": b"module.exports = 1\n",
        ".git/config": b"git\n",
        "pkg/__pycache__/app.pyc": b"binary",
        "assets/logo.png": b"\x89PNG\r\n",
    })
    docs = ingest_bytes("repo.zip", data)
    names = {doc.name: doc.kind for doc in docs}
    assert names == {"src/app.py": "code", "README.md": "context"}


def test_zip_slip_is_rejected():
    data = _zip({
        "../secrets.py": b"password = 'x'\n",
        "src/ok.py": b"x = 1\n",
    })
    with pytest.raises(IngestError, match="unsafe path"):
        ingest_bytes("repo.zip", data)


def test_zip_skips_empty_source_files():
    data = _zip({
        "pkg/__init__.py": b"",
        "pkg/app.py": b"x = 1\n",
    })
    docs = ingest_bytes("repo.zip", data)
    assert [doc.name for doc in docs] == ["pkg/app.py"]


def test_direct_empty_source_is_rejected():
    with pytest.raises(IngestError, match="empty"):
        ingest_bytes("app.py", b"   \n")


def test_bad_zip():
    with pytest.raises(IngestError, match="not a valid zip"):
        ingest_bytes("repo.zip", b"this is not a zip")


def test_context_is_truncated(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.ingest.MAX_CONTEXT_CHARS", 24)
    doc = TextDocument("standards.md", "abcdefghij" * 10, "context")
    text = format_context([doc])
    assert text.startswith("### standards.md")
    assert "[truncated]" in text
