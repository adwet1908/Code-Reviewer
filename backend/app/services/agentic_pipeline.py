"""Phase 3 Pass 1: LangGraph agentic review skeleton (no tool loop / no trace UI)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.language import language_skill_for_path
from app.agents.schemas import (
    AgentFinding,
    AgentReviewDraft,
    AnalysisResult,
    CritiqueResult,
)
from app.agents.skill_loader import SkillDefinition, load_all_agent_skills
from app.config import (
    AGENT_CHEAP_MODEL,
    AGENT_EVIDENCE_MAX_CHARS,
    AGENT_LLM_CALL_BUDGET,
    AGENT_NODE_TIMEOUT_SECONDS,
    AGENT_STRONG_MODEL,
)
from app.models import Chunk
from app.schemas import DroppedFinding, Review
from app.services.llm import LLMError, generate_structured
from app.services.model_catalog import ModelRuntime
from app.services.retrieval import RetrievedChunk, retrieve_for_file, retrieve_for_question

logger = logging.getLogger(__name__)

GenerateFn = Callable[..., Any]


class ReviewState(TypedDict, total=False):
    project_id: int
    file_path: str
    file_text: str
    analysis: dict
    evidence: list[dict]
    draft_findings: list[dict]
    draft_summary: str
    verified_findings: list[dict]
    dropped_findings: list[dict]
    critique_round: int
    call_count: int
    pending_queries: list[str]
    re_critique_only: bool
    warning: str
    budget_exceeded: bool


@dataclass
class AgenticReviewResult:
    review: Review
    evidence: list[RetrievedChunk]
    dropped_findings: list[DroppedFinding]
    call_count: int
    warning: str | None = None


ProgressFn = Callable[[str, str, str | None], None]


@dataclass
class PipelineContext:
    db: Session
    runtime: ModelRuntime
    skills: dict[str, SkillDefinition]
    language_skill: SkillDefinition
    generate: GenerateFn = generate_structured
    call_budget: int = AGENT_LLM_CALL_BUDGET
    node_timeout: float = AGENT_NODE_TIMEOUT_SECONDS
    evidence_max_chars: int = AGENT_EVIDENCE_MAX_CHARS
    on_progress: ProgressFn | None = None

    def emit(self, agent: str, status: str, detail: str | None = None) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(agent, status, detail)
        except Exception:
            logger.debug("progress callback failed", exc_info=False)


def run_agentic_review(
    db: Session,
    project_id: int,
    file_path: str,
    file_text: str,
    runtime: ModelRuntime,
    *,
    generate: GenerateFn | None = None,
    skills: dict[str, SkillDefinition] | None = None,
    on_progress: ProgressFn | None = None,
) -> AgenticReviewResult:
    ctx = PipelineContext(
        db=db,
        runtime=runtime,
        skills=skills or load_all_agent_skills(),
        language_skill=language_skill_for_path(file_path),
        generate=generate or generate_structured,
        on_progress=on_progress,
    )
    graph = build_graph(ctx)
    initial: ReviewState = {
        "project_id": project_id,
        "file_path": file_path,
        "file_text": file_text,
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
    final = graph.invoke(initial)
    findings = [AgentFinding.model_validate(f) for f in final.get("verified_findings") or []]
    review = Review(
        summary=final.get("draft_summary") or "Agentic review complete.",
        findings=[_as_public_finding(f) for f in findings],
    )
    dropped = [DroppedFinding.model_validate(d) for d in final.get("dropped_findings") or []]
    evidence = [RetrievedChunk(**e) for e in final.get("evidence") or []]
    warning = (final.get("warning") or "").strip() or None
    return AgenticReviewResult(
        review=review,
        evidence=evidence,
        dropped_findings=dropped,
        call_count=int(final.get("call_count") or 0),
        warning=warning,
    )


def _as_public_finding(finding: AgentFinding):
    from app.schemas import Finding

    return Finding.model_validate(finding.model_dump())


def build_graph(ctx: PipelineContext):
    graph = StateGraph(ReviewState)
    graph.add_node("analyser", _tracked(ctx, "analyser", _analyser_node))
    graph.add_node("retriever", _tracked(ctx, "retriever", _retriever_node))
    graph.add_node("reviewer", _tracked(ctx, "reviewer", _reviewer_node))
    graph.add_node("critic", _tracked(ctx, "critic", _critic_node))
    graph.add_node("reporter", _tracked(ctx, "reporter", _reporter_node))

    graph.add_edge(START, "analyser")
    graph.add_edge("analyser", "retriever")
    graph.add_conditional_edges(
        "retriever",
        _route_after_retriever,
        {"reviewer": "reviewer", "critic": "critic"},
    )
    graph.add_edge("reviewer", "critic")
    graph.add_conditional_edges(
        "critic",
        _route_after_critic,
        {"retriever": "retriever", "reporter": "reporter"},
    )
    graph.add_edge("reporter", END)
    return graph.compile()


def _tracked(ctx: PipelineContext, name: str, fn: Callable[[PipelineContext, ReviewState], dict]):
    """Emit running/done progress around each graph node for the live UI."""

    def node(state: ReviewState) -> dict:
        detail = None
        if name == "retriever" and state.get("re_critique_only"):
            detail = "Follow-up retrieval after critic"
        elif name == "critic" and int(state.get("critique_round") or 0) > 0:
            detail = "Re-checking after more context"
        ctx.emit(name, "running", detail)
        try:
            out = fn(ctx, state)
            ctx.emit(name, "done", detail)
            return out
        except Exception:
            ctx.emit(name, "error", detail)
            raise

    return node


def _route_after_retriever(state: ReviewState) -> Literal["reviewer", "critic"]:
    return "critic" if state.get("re_critique_only") else "reviewer"


def _route_after_critic(state: ReviewState) -> Literal["retriever", "reporter"]:
    if state.get("budget_exceeded"):
        return "reporter"
    # Critic sets re_critique_only + pending_queries when one more retrieve is allowed.
    if state.get("re_critique_only") and (state.get("pending_queries") or []):
        return "retriever"
    return "reporter"


def _tier_runtime(ctx: PipelineContext, tier: str) -> ModelRuntime:
    model_id = AGENT_CHEAP_MODEL if tier == "cheap" else AGENT_STRONG_MODEL
    # Keep provider/key from the user's selected config; only swap model id for the tier.
    return ModelRuntime(
        selection_id=ctx.runtime.selection_id,
        model_id=model_id or ctx.runtime.model_id,
        provider=ctx.runtime.provider,
        api_key=ctx.runtime.api_key,
        base_url=ctx.runtime.base_url,
    )


def _budget_ok(state: ReviewState, ctx: PipelineContext) -> bool:
    return int(state.get("call_count") or 0) < ctx.call_budget


def _run_timed(fn: Callable[[], Any], timeout: float, label: str) -> Any:
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout as exc:
            raise TimeoutError(f"{label} timed out after {timeout}s") from exc


def _analyser_node(ctx: PipelineContext, state: ReviewState) -> dict:
    skill = ctx.skills["analyser"]
    repo_map = _compact_repo_map(ctx.db, state["project_id"])
    user_prompt = (
        f"TARGET file: {state['file_path']}\n\n"
        f"Numbered source:\n{state['file_text']}\n\n"
        f"Repo map:\n{repo_map}"
    )

    def call():
        if not _budget_ok(state, ctx):
            return None
        return ctx.generate(
            _tier_runtime(ctx, skill.model_tier),
            skill.instructions,
            user_prompt,
            AnalysisResult,
        )

    call_count = int(state.get("call_count") or 0)
    warning = state.get("warning") or ""
    try:
        result = _run_timed(call, ctx.node_timeout, "analyser")
        if result is None:
            warning = _append_warning(warning, "LLM call budget reached during analyser.")
            return {
                "analysis": AnalysisResult().model_dump(),
                "warning": warning,
                "budget_exceeded": True,
            }
        call_count += 1
        return {"analysis": result.model_dump(), "call_count": call_count}
    except Exception as exc:
        # Spec: analyser failure falls back to Phase 2 style retrieval only.
        logger.warning("analyser failed; continuing with Phase 2 retrieval: %s", type(exc).__name__)
        return {
            "analysis": AnalysisResult().model_dump(),
            "warning": _append_warning(warning, "Analyser failed; used Phase 2 retrieval only."),
            "call_count": call_count,
        }


def _retriever_node(ctx: PipelineContext, state: ReviewState) -> dict:
    """Pass 1 stub: Phase 2 file retrieval + query/symbol lookups. No LLM."""
    project_id = state["project_id"]
    file_path = state["file_path"]
    analysis = AnalysisResult.model_validate(state.get("analysis") or {})
    queries = list(state.get("pending_queries") or []) or list(analysis.retrieval_queries)
    symbols = list(analysis.external_symbols_used)

    by_id: dict[int, RetrievedChunk] = {}
    for item in retrieve_for_file(ctx.db, project_id, file_path):
        by_id[item.chunk_id] = item

    for query in queries:
        q = (query or "").strip()
        if not q:
            continue
        try:
            for item in retrieve_for_question(ctx.db, project_id, q, top_k=5):
                by_id.setdefault(item.chunk_id, item)
        except Exception as exc:
            logger.warning("query retrieval skipped: %s", type(exc).__name__)

    for symbol in symbols:
        for item in _lookup_symbol(ctx.db, project_id, symbol):
            by_id.setdefault(item.chunk_id, item)

    evidence = _budget_evidence(list(by_id.values()), ctx.evidence_max_chars)
    return {
        "evidence": [_chunk_dict(c) for c in evidence],
        "pending_queries": [],
        # After a critique-driven retrieval, critic runs again (not reviewer).
        "re_critique_only": bool(state.get("re_critique_only") or state.get("critique_round")),
    }


def _reviewer_node(ctx: PipelineContext, state: ReviewState) -> dict:
    skill = ctx.skills["reviewer"]
    system = skill.instructions + "\n\n" + ctx.language_skill.instructions
    evidence_block = _format_evidence(state.get("evidence") or [])
    analysis = AnalysisResult.model_validate(state.get("analysis") or {})
    user_prompt = (
        f"TARGET file: {state['file_path']}\n\n"
        f"Numbered source:\n{state['file_text']}\n\n"
        f"Analysis purpose: {analysis.purpose}\n"
        f"Risk hypotheses:\n- " + "\n- ".join(analysis.risk_hypotheses or ["(none)"]) + "\n\n"
        f"Labelled evidence:\n{evidence_block}"
    )

    call_count = int(state.get("call_count") or 0)
    warning = state.get("warning") or ""
    if not _budget_ok(state, ctx):
        return {
            "draft_findings": [],
            "draft_summary": "Call budget exhausted before reviewer.",
            "warning": _append_warning(warning, "LLM call budget reached; returning verified findings so far."),
            "budget_exceeded": True,
        }

    def call():
        return ctx.generate(
            _tier_runtime(ctx, skill.model_tier),
            system,
            user_prompt,
            AgentReviewDraft,
        )

    try:
        draft = _run_timed(call, ctx.node_timeout, "reviewer")
        call_count += 1
        return {
            "draft_findings": [f.model_dump() for f in draft.findings],
            "draft_summary": draft.summary,
            "call_count": call_count,
        }
    except Exception as exc:
        logger.warning("reviewer failed: %s", type(exc).__name__)
        return {
            "draft_findings": [],
            "draft_summary": "Reviewer failed.",
            "warning": _append_warning(warning, "Reviewer failed; no draft findings."),
            "call_count": call_count,
        }


def _critic_node(ctx: PipelineContext, state: ReviewState) -> dict:
    drafts = [AgentFinding.model_validate(f) for f in state.get("draft_findings") or []]
    if not drafts:
        return {
            "verified_findings": [],
            "pending_queries": [],
            "re_critique_only": False,
        }

    skill = ctx.skills["critic"]
    system = skill.instructions + "\n\n" + ctx.language_skill.instructions
    evidence_block = _format_evidence(state.get("evidence") or [])
    draft_block = "\n\n".join(
        f"[{i}] location={f.location}\nissue={f.issue}\nsuggestion={f.suggestion}\n"
        f"evidence_chunk_ids={f.evidence_chunk_ids}"
        for i, f in enumerate(drafts)
    )
    user_prompt = (
        f"TARGET file: {state['file_path']}\n\n"
        f"Numbered source:\n{state['file_text']}\n\n"
        f"Labelled evidence:\n{evidence_block}\n\n"
        f"Draft findings:\n{draft_block}"
    )

    call_count = int(state.get("call_count") or 0)
    warning = state.get("warning") or ""
    critique_round = int(state.get("critique_round") or 0)
    dropped = list(state.get("dropped_findings") or [])

    if not _budget_ok(state, ctx):
        # Keep nothing new; preserve any already verified.
        return {
            "warning": _append_warning(warning, "LLM call budget reached during critic."),
            "budget_exceeded": True,
            "pending_queries": [],
            "re_critique_only": False,
            "verified_findings": state.get("verified_findings") or [],
        }

    def call():
        return ctx.generate(
            _tier_runtime(ctx, skill.model_tier),
            system,
            user_prompt,
            CritiqueResult,
        )

    try:
        critique = _run_timed(call, ctx.node_timeout, "critic")
        call_count += 1
    except Exception as exc:
        logger.warning("critic failed: %s", type(exc).__name__)
        # Fail closed: keep drafts unverified -> drop with reason.
        for f in drafts:
            dropped.append(
                DroppedFinding(
                    location=f.location,
                    issue=f.issue,
                    reason="Critic failed; finding left unverified.",
                    verdict="drop",
                ).model_dump()
            )
        return {
            "verified_findings": [],
            "dropped_findings": dropped,
            "pending_queries": [],
            "re_critique_only": False,
            "warning": _append_warning(warning, "Critic failed; drafts dropped."),
            "call_count": call_count,
        }

    line_count = _count_source_lines(state["file_text"])
    already_verified = list(state.get("verified_findings") or [])
    newly_kept: list[dict] = []
    still_open: list[dict] = []
    pending: list[str] = []
    by_index = {item.finding_index: item for item in critique.items}
    allow_more_context = critique_round < 1

    for i, finding in enumerate(drafts):
        item = by_index.get(i)
        if item is None:
            dropped.append(
                DroppedFinding(
                    location=finding.location,
                    issue=finding.issue,
                    reason="Critic omitted this finding.",
                    verdict="drop",
                ).model_dump()
            )
            continue
        if not _location_exists(finding.location, line_count):
            dropped.append(
                DroppedFinding(
                    location=finding.location,
                    issue=finding.issue,
                    reason="Cited lines do not exist in the target file.",
                    verdict="drop",
                ).model_dump()
            )
            continue
        if item.verdict == "keep":
            newly_kept.append(finding.model_dump())
        elif item.verdict == "needs_more_context" and allow_more_context:
            still_open.append(finding.model_dump())
            pending.append((item.retrieval_query or finding.issue)[:160])
        else:
            reason = item.reason or "Dropped by critic."
            if item.verdict == "needs_more_context":
                reason = item.reason or "Still unverified after extra retrieval."
            dropped.append(
                DroppedFinding(
                    location=finding.location,
                    issue=finding.issue,
                    reason=reason,
                    verdict=item.verdict,
                ).model_dump()
            )

    verified = already_verified + newly_kept
    updates: dict[str, Any] = {
        "call_count": call_count,
        "dropped_findings": dropped,
        "verified_findings": verified,
        "pending_queries": pending,
    }
    if pending and allow_more_context:
        # Retriever then critic only; do not re-run the reviewer.
        updates["critique_round"] = critique_round + 1
        updates["re_critique_only"] = True
        updates["draft_findings"] = still_open
    else:
        updates["re_critique_only"] = False
        updates["pending_queries"] = []
        updates["draft_findings"] = []
    return updates


def _reporter_node(ctx: PipelineContext, state: ReviewState) -> dict:
    """Plain merge/dedupe/sort — no LLM."""
    findings = [AgentFinding.model_validate(f) for f in state.get("verified_findings") or []]
    # If we still have drafts and no verified (budget cut mid-flight), keep verified only.
    deduped = _dedupe_findings(findings)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    deduped.sort(key=lambda f: severity_order.get(f.severity, 9))
    summary = state.get("draft_summary") or ""
    if not summary:
        summary = (
            f"Agentic review kept {len(deduped)} finding(s); "
            f"dropped {len(state.get('dropped_findings') or [])}."
        )
    warning = state.get("warning") or ""
    if state.get("budget_exceeded"):
        warning = _append_warning(
            warning,
            "Model call budget reached; returned verified findings only.",
        )
    return {
        "verified_findings": [f.model_dump() for f in deduped],
        "draft_summary": summary,
        "warning": warning,
        "re_critique_only": False,
        "pending_queries": [],
    }


def _compact_repo_map(db: Session, project_id: int, limit: int = 200) -> str:
    rows = db.execute(
        select(Chunk.path, Chunk.symbol_name)
        .where(Chunk.project_id == project_id)
        .order_by(Chunk.path, Chunk.start_line)
        .limit(limit * 3)
    ).all()
    by_path: dict[str, list[str]] = {}
    for path, symbol in rows:
        symbols = by_path.setdefault(path, [])
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    lines = []
    for path in sorted(by_path)[:limit]:
        syms = ", ".join(by_path[path][:12]) or "(no symbols)"
        lines.append(f"- {path}: {syms}")
    return "\n".join(lines) if lines else "(empty repo map)"


def _lookup_symbol(db: Session, project_id: int, symbol: str) -> list[RetrievedChunk]:
    name = (symbol or "").strip()
    if not name:
        return []
    exact = db.execute(
        select(Chunk).where(Chunk.project_id == project_id, Chunk.symbol_name == name).limit(8)
    ).scalars().all()
    if not exact:
        exact = db.execute(
            select(Chunk)
            .where(
                Chunk.project_id == project_id,
                Chunk.content.ilike(f"%{name}%"),
            )
            .limit(8)
        ).scalars().all()
    return [
        RetrievedChunk(
            chunk_id=c.id,
            path=c.path,
            start_line=c.start_line,
            end_line=c.end_line,
            source_type=c.source_type,
            content=c.content,
            score=1.0,
        )
        for c in exact
    ]


def _budget_evidence(chunks: list[RetrievedChunk], max_chars: int) -> list[RetrievedChunk]:
    out: list[RetrievedChunk] = []
    used = 0
    for chunk in sorted(chunks, key=lambda c: c.score, reverse=True):
        block = len(chunk.content) + 40
        if used + block > max_chars:
            continue
        out.append(chunk)
        used += block
    return out


def _chunk_dict(chunk: RetrievedChunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "path": chunk.path,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "source_type": chunk.source_type,
        "content": chunk.content,
        "score": chunk.score,
    }


def _format_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return "(no evidence chunks)"
    parts = []
    for item in evidence:
        parts.append(
            f"[chunk_id={item['chunk_id']}] {item['path']} "
            f"(lines {item['start_line']}-{item['end_line']})\n{item['content']}"
        )
    return "\n\n".join(parts)


def _count_source_lines(numbered: str) -> int:
    return max((len(numbered.splitlines()), 0))


def _location_exists(location: str, line_count: int) -> bool:
    nums = [int(n) for n in re.findall(r"\d+", location or "")]
    if not nums:
        return True  # non-numeric locations: leave to critic text
    return all(1 <= n <= line_count for n in nums)


def _dedupe_findings(findings: list[AgentFinding]) -> list[AgentFinding]:
    seen: set[str] = set()
    out: list[AgentFinding] = []
    for f in findings:
        key = f"{f.location}|{f.issue.strip().lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _append_warning(existing: str, message: str) -> str:
    parts = [p for p in (existing, message) if p]
    return " ".join(parts)
