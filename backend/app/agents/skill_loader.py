"""Load agent SKILL.md files (YAML frontmatter + markdown body as system prompt)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

AGENTS_ROOT = Path(__file__).resolve().parent
REQUIRED_AGENTS = ("analyser", "retriever", "reviewer", "critic")
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    model_tier: str  # cheap | strong
    instructions: str
    max_steps: int | None = None
    path: Path | None = None


class SkillLoadError(RuntimeError):
    """Missing or malformed SKILL.md — fail loudly at startup."""


def load_skill_file(path: Path) -> SkillDefinition:
    if not path.is_file():
        raise SkillLoadError(f"Missing skill file: {path}")
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if not match:
        raise SkillLoadError(f"SKILL.md must start with YAML frontmatter: {path}")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillLoadError(f"Invalid YAML frontmatter in {path}: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillLoadError(f"Frontmatter must be a mapping: {path}")

    name = meta.get("name")
    description = meta.get("description")
    model_tier = meta.get("model_tier", "cheap")
    if not name or not isinstance(name, str):
        raise SkillLoadError(f"Frontmatter missing string 'name': {path}")
    if not description or not isinstance(description, str):
        raise SkillLoadError(f"Frontmatter missing string 'description': {path}")
    if model_tier not in {"cheap", "strong"}:
        raise SkillLoadError(f"model_tier must be cheap|strong in {path}")

    max_steps = meta.get("max_steps")
    if max_steps is not None and not isinstance(max_steps, int):
        raise SkillLoadError(f"max_steps must be an int when set: {path}")

    body = match.group(2).strip()
    if not body:
        raise SkillLoadError(f"SKILL.md body (instructions) is empty: {path}")

    return SkillDefinition(
        name=name.strip(),
        description=description.strip(),
        model_tier=model_tier,
        instructions=body,
        max_steps=max_steps,
        path=path,
    )


def load_all_agent_skills(root: Path | None = None) -> dict[str, SkillDefinition]:
    """Load the four required agent skills; raises SkillLoadError if any are bad."""
    base = root or AGENTS_ROOT
    skills: dict[str, SkillDefinition] = {}
    for agent in REQUIRED_AGENTS:
        path = base / agent / "SKILL.md"
        skill = load_skill_file(path)
        if skill.name != agent:
            raise SkillLoadError(f"Skill name '{skill.name}' must match folder '{agent}' ({path})")
        skills[agent] = skill
    return skills


def language_skill_path(language: str, root: Path | None = None) -> Path:
    base = root or AGENTS_ROOT
    return base / "skills" / f"{language}-review" / "SKILL.md"


def load_language_skill(language: str, root: Path | None = None) -> SkillDefinition:
    """Load one language checklist; falls back to generic-review."""
    base = root or AGENTS_ROOT
    preferred = language_skill_path(language, base)
    if preferred.is_file():
        return load_skill_file(preferred)
    generic = language_skill_path("generic", base)
    return load_skill_file(generic)
