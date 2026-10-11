"""Phase 3 Pass 1 tests — fake LLM only, no provider calls."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.agents.language import language_key_for_path
from app.agents.schemas import AgentFinding, AgentReviewDraft, AnalysisResult, CritiqueItem, CritiqueResult
from app.agents.skill_loader import SkillLoadError, load_all_agent_skills, load_skill_file
from app.db import SessionLocal, init_db
from app.models import Chunk, Project, User
from app.services.agentic_pipeline import PipelineContext, build_graph, run_agentic_review
from app.services.model_catalog import ModelRuntime

AGENTS_ROOT = Path(__file__).resolve().parents[1] / "app" / "agents"


def setup_module() -> None:
    init_db()


def _runtime() -> ModelRuntime:
    return ModelRuntime(
        selection_id="gemini-3.8-flash",
        model_id="gemini-3.8-flash",
        provider="gemini",
        api_key="test-key",
    )


def _seed_project(db: Session) -> tuple[int, str]:
    import uuid

    user = User(email=f"agentic-{uuid.uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    db.flush()
    project = Project(user_id=user.id, name="p", status="ready", file_count=1, chunk_count=1)
    db.add(project)
    db.flush()
    db.add(
        Chunk(
            project_id=project.id,
            file_id=None,
            source_type="code",
            path="src/lib.cpp",
            start_line=1,
            end_line=10,
            symbol_name="findBook",
            kind="function",
            content="Book* findBook(int id);",
            content_hash="h1",
            embedding=None,
        )
    )
    db.commit()
    return project.id, "src/main.cpp"


class FakeLLM:
    """Returns scripted structured objects; records call order by schema name."""

    def __init__(self, scripts: list):
        self.scripts = list(scripts)
        self.calls: list[str] = []

    def __call__(self, runtime, system, user_prompt, schema, temperature=0.2):
        self.calls.append(schema.__name__)
        if not self.scripts:
            raise AssertionError(f"Unexpected LLM call for {schema.__name__}")
        value = self.scripts.pop(0)
        if isinstance(value, schema):
            return value
        return schema.model_validate(value)


def test_skill_loader_loads_required_agents():
    skills = load_all_agent_skills(AGENTS_ROOT)
    assert set(skills) == {"analyser", "retriever", "reviewer", "critic"}
    assert skills["reviewer"].model_tier == "strong"
    assert "TARGET" in skills["reviewer"].instructions or "target" in skills["reviewer"].instructions.lower()


def test_skill_loader_missing_file(tmp_path: Path):
    with pytest.raises(SkillLoadError, match="Missing skill file"):
        load_skill_file(tmp_path / "nope.md")


def test_skill_loader_bad_frontmatter(tmp_path: Path):
    path = tmp_path / "SKILL.md"
    path.write_text("no frontmatter here\njust body\n", encoding="utf-8")
    with pytest.raises(SkillLoadError, match="frontmatter"):
        load_skill_file(path)


def test_skill_loader_bad_tier(tmp_path: Path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: x\ndescription: y\nmodel_tier: medium\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillLoadError, match="model_tier"):
        load_skill_file(path)


def test_language_skill_selection_by_extension():
    assert language_key_for_path("a/b/library.cpp") == "cpp"
    assert language_key_for_path("app.py") == "python"
    assert language_key_for_path("x.ts") == "javascript"
    assert language_key_for_path("Main.java") == "java"
    assert language_key_for_path("readme.md") == "generic"


def test_graph_order_and_critic_loop_at_most_once():
    fake = FakeLLM(
        [
            AnalysisResult(
                purpose="entry",
                external_symbols_used=["findBook"],
                risk_hypotheses=["null deref"],
                retrieval_queries=["findBook definition"],
            ),
            AgentReviewDraft(
                summary="draft",
                findings=[
                    AgentFinding(
                        severity="high",
                        category="bug",
                        location="12",
                        issue="findBook may be null",
                        suggestion="check null",
                        evidence_chunk_ids=[1],
                    ),
                    AgentFinding(
                        severity="medium",
                        category="bug",
                        location="20",
                        issue="off by one",
                        suggestion="use >=",
                    ),
                ],
            ),
            CritiqueResult(
                items=[
                    CritiqueItem(
                        finding_index=0,
                        verdict="needs_more_context",
                        reason="need definition",
                        retrieval_query="findBook",
                    ),
                    CritiqueItem(finding_index=1, verdict="keep", reason="ok"),
                ]
            ),
            CritiqueResult(
                items=[
                    CritiqueItem(finding_index=0, verdict="keep", reason="confirmed"),
                ]
            ),
        ]
    )
    numbered = "\n".join(f"{i}| x" for i in range(1, 25))
    with SessionLocal() as db:
        project_id, path = _seed_project(db)
        result = run_agentic_review(
            db,
            project_id,
            path,
            numbered,
            _runtime(),
            generate=fake,
            skills=load_all_agent_skills(AGENTS_ROOT),
        )

    # analyser, reviewer, critic, critic (no second reviewer)
    assert fake.calls == ["AnalysisResult", "AgentReviewDraft", "CritiqueResult", "CritiqueResult"]
    assert result.call_count == 4
    assert len(result.review.findings) == 2
    assert not any(d.verdict == "needs_more_context" for d in result.dropped_findings)


def test_call_budget_enforced():
    fake = FakeLLM([AnalysisResult(purpose="p", retrieval_queries=[])])
    numbered = "1| int x = 0;\n2| return x;\n"
    with SessionLocal() as db:
        project_id, path = _seed_project(db)
        skills = load_all_agent_skills(AGENTS_ROOT)
        from app.agents.language import language_skill_for_path

        ctx = PipelineContext(
            db=db,
            runtime=_runtime(),
            skills=skills,
            language_skill=language_skill_for_path(path),
            generate=fake,
            call_budget=1,
        )
        final = build_graph(ctx).invoke(
            {
                "project_id": project_id,
                "file_path": path,
                "file_text": numbered,
                "analysis": {},
                "evidence": [],
                "draft_findings": [],
                "draft_summary": "",
                "verified_findings": [],
                "dropped_findings": [],
                "critique_round": 0,
                "call_count": 0,
                "pending_queries": [],
                "re_critique_only": False,
                "warning": "",
                "budget_exceeded": False,
            }
        )

    # Analyser uses the only allowed call; reviewer must not call the LLM.
    assert fake.calls == ["AnalysisResult"]
    assert final["call_count"] == 1
    assert final.get("budget_exceeded") is True or "budget" in (final.get("warning") or "").lower()
    assert final.get("draft_findings") == []


def test_progress_callback_reports_running_agents():
    fake = FakeLLM(
        [
            AnalysisResult(purpose="p"),
            AgentReviewDraft(summary="s", findings=[]),
            CritiqueResult(items=[]),
        ]
    )
    seen: list[tuple[str, str]] = []
    numbered = "1| a\n2| b\n"

    def on_progress(agent: str, status: str, detail: str | None = None) -> None:
        seen.append((agent, status))

    with SessionLocal() as db:
        project_id, path = _seed_project(db)
        run_agentic_review(
            db,
            project_id,
            path,
            numbered,
            _runtime(),
            generate=fake,
            skills=load_all_agent_skills(AGENTS_ROOT),
            on_progress=on_progress,
        )

    running = [agent for agent, status in seen if status == "running"]
    assert running[0] == "analyser"
    assert "reviewer" in running
    assert "critic" in running
    assert "reporter" in running
    assert ("reviewer", "done") in seen


def test_dropped_findings_recorded():
    fake = FakeLLM(
        [
            AnalysisResult(purpose="p"),
            AgentReviewDraft(
                summary="s",
                findings=[
                    AgentFinding(
                        severity="low",
                        category="readability",
                        location="999",
                        issue="invented line",
                        suggestion="n/a",
                    ),
                    AgentFinding(
                        severity="high",
                        category="bug",
                        location="2",
                        issue="real issue",
                        suggestion="fix",
                    ),
                ],
            ),
            CritiqueResult(
                items=[
                    CritiqueItem(finding_index=0, verdict="keep", reason="wrongly kept"),
                    CritiqueItem(finding_index=1, verdict="drop", reason="duplicate of another"),
                ]
            ),
        ]
    )
    numbered = "1| a\n2| b\n3| c\n"
    with SessionLocal() as db:
        project_id, path = _seed_project(db)
        result = run_agentic_review(
            db,
            project_id,
            path,
            numbered,
            _runtime(),
            generate=fake,
            skills=load_all_agent_skills(AGENTS_ROOT),
        )
    assert any("do not exist" in d.reason.lower() or "999" in d.location for d in result.dropped_findings)
    assert any("duplicate" in d.reason.lower() for d in result.dropped_findings)
