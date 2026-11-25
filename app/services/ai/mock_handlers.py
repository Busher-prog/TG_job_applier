"""Handlers used by MockLLMProvider. Output is derived only from the input context."""

from __future__ import annotations

from typing import Any

from app.providers.llm.mock_provider import mock_handler
from app.services.cv.heuristic_parser import heuristic_parse


@mock_handler("cv_parser")
def _cv_parser(context: dict[str, Any]) -> dict[str, Any]:
    return heuristic_parse(context.get("text", ""), context.get("links", []))


@mock_handler("cv_structure_planner")
def _planner(context: dict[str, Any]) -> dict[str, Any]:
    from app.services.cv.structure import rule_based_plan

    return rule_based_plan(context["facts"], context.get("target_roles") or [], context.get("direction")).model_dump()


@mock_handler("cv_content_generator")
def _content(context: dict[str, Any]) -> dict[str, Any]:
    from app.services.cv.facts import exp_id
    from app.services.cv.generator import deterministic_summary

    facts = context["facts"]
    shorter = context.get("page_limit") == 1 or any(
        "short" in i.lower() or "корот" in i.lower() or "kürz" in i.lower() for i in context.get("instructions", [])
    )
    limit = 2 if shorter else 5
    return {
        "headline": (context.get("target_roles") or [None])[0],
        "professional_summary": deterministic_summary(facts, context.get("target_roles") or [], context["language"]),
        "experience": [
            {"id": exp_id(i), "bullets": [*e.achievements, *e.responsibilities][:limit]}
            for i, e in enumerate(facts.experience)
        ],
        "skills": [*facts.skills.hard, *facts.skills.technical],
        "software": [*facts.skills.software, *facts.skills.tools],
        "soft_skills": list(facts.skills.soft),
    }


@mock_handler("cv_optimizer")
def _optimizer(context: dict[str, Any]) -> dict[str, Any]:
    # Rule-based findings are shown from localisation; the mock adds no free text.
    return {"strengths": [], "issues": [], "recommendations": [], "missing_information": [], "clarifying_questions": []}


@mock_handler("interview_extract")
def _interview(context: dict[str, Any]) -> dict[str, Any]:
    from app.services.cv.interview import heuristic_extract

    return heuristic_extract(context["stage"], context["answer"], context.get("expected_field"))


@mock_handler("interview_questions")
def _interview_questions(context: dict[str, Any]) -> dict[str, Any]:
    return {"questions": []}  # caller falls back to the localised question bank


@mock_handler("skill_suggester")
def _skills(context: dict[str, Any]) -> dict[str, Any]:
    from app.services.cv.interview import find_tools

    facts = context["facts"]
    pool = " ".join([*context.get("answers", []), *(" ".join(e.responsibilities + e.tools) for e in facts.experience)])
    return {"skills": find_tools(pool)}


@mock_handler("user_intent_interpreter")
def _intent(context: dict[str, Any]) -> dict[str, Any]:
    from app.services.cv.editing import rule_based_intent

    return rule_based_intent(context["text"]).model_dump()
