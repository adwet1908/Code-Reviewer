"""Pick the language checklist skill from a file path."""

from pathlib import Path

from app.agents.skill_loader import SkillDefinition, load_language_skill
from app.config import LANGUAGE_BY_EXT

# Map LANGUAGE_BY_EXT values -> skill folder stem (before -review).
_SKILL_ALIAS = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "javascript",
    "java": "java",
    "cpp": "cpp",
    "c": "cpp",
}


def language_key_for_path(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    lang = LANGUAGE_BY_EXT.get(ext, "")
    return _SKILL_ALIAS.get(lang, "generic")


def language_skill_for_path(file_path: str) -> SkillDefinition:
    return load_language_skill(language_key_for_path(file_path))
