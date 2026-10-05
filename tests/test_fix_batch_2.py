from __future__ import annotations

import pytest

from app.llm.deepseek_client import DeepSeekClient
from app.query.answer_generator import AnswerGenerator
from app.query.schema import QueryPlan


@pytest.fixture(scope="module")
def answer_generator():
    return AnswerGenerator()


def test_system_prompt_rule21_contract(answer_generator):
    """System prompt Rule 21 explicitly distinguishes session tokens from database record identifiers."""
    prompt = answer_generator._build_system_prompt()
    assert "Do not expose internal conversation-memory reference IDs" in prompt
    assert "database record identifiers, entity IDs, codes, or primary/foreign keys" in prompt
    assert "already present in the VERIFIED QUERY RESULT are valid factual data" in prompt
    assert "Do NOT invent human-readable" in prompt


def test_database_identifier_included_for_which_entity_question(answer_generator):
    """Database identifier already in verified result is reported when identifying requested entity."""
    question = "Which event has the highest number of registrations?"
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["registration_sitecore_id"],
        group_by=["event_sitecore_id"],
        aggregation="count",
        sort_column="count",
        sort_direction="desc",
        limit=1,
    )
    data = [
        {
            "event_sitecore_id": "2feae74c-7368-45e4-9f28-9b06ff096fac",
            "aggregation_value": 5,
        }
    ]

    answer = answer_generator.generate(
        question=question,
        result=data,
        plan=plan,
    )

    # Identifier and count must both be presented
    assert "2feae74c-7368-45e4-9f28-9b06ff096fac" in answer
    assert "5" in answer
    # Must not claim it is hidden or only an internal reference
    assert "cannot be provided" not in answer.lower()
    assert "only by an internal event identifier" not in answer.lower()


def test_conversation_session_reference_tokens_not_exposed(answer_generator):
    """Conversation/session memory reference tokens are strictly forbidden from being exposed."""
    question = "What is the peak sales volume?"
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["volume"],
        aggregation="max",
    )
    data = 1500
    warnings = ["Executed against internal session reference_id=ref-session-98765-token"]

    answer = answer_generator.generate(
        question=question,
        result=data,
        plan=plan,
        warnings=warnings,
    )

    assert "1,500" in answer or "1500" in answer
    assert "ref-session-98765-token" not in answer


def test_query_plan_and_internal_implementation_details_not_exposed(answer_generator):
    """Internal QueryPlan structural AST names and implementation mechanics are not exposed."""
    question = "What are the top 3 products by price?"
    plan = QueryPlan(
        intent="ranking",
        target_columns=["name", "price"],
        sort_column="price",
        sort_direction="desc",
        limit=3,
    )
    data = [
        {"name": "Widget Alpha", "price": 100},
        {"name": "Widget Beta", "price": 90},
        {"name": "Widget Gamma", "price": 80},
    ]

    answer = answer_generator.generate(
        question=question,
        result=data,
        plan=plan,
    )

    assert "Widget Alpha" in answer
    assert "Widget Beta" in answer
    assert "Widget Gamma" in answer
    # Must not leak AST structure
    assert "QueryPlan" not in answer
    assert "target_columns" not in answer
    assert "sort_column" not in answer


def test_model_does_not_invent_human_readable_name_when_absent(answer_generator):
    """The model must not invent a human-readable entity name when only an ID is present."""
    question = "Which student has the highest score?"
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["score"],
        group_by=["student_uuid"],
        aggregation="max",
        sort_column="aggregation_value",
        sort_direction="desc",
        limit=1,
    )
    student_id = "e8b23c91-4471-419b-a01b-9f4561234567"
    data = [
        {
            "student_uuid": student_id,
            "aggregation_value": 98,
        }
    ]

    answer = answer_generator.generate(
        question=question,
        result=data,
        plan=plan,
    )

    assert student_id in answer
    assert "98" in answer
    # Must not hallucinate a fake person name
    assert "John Doe" not in answer
    assert "Jane Doe" not in answer
    assert "Alice" not in answer


def test_existing_answer_generator_ordinary_count_scalar_lookup(answer_generator):
    """Existing behavior remains intact for ordinary counts, aggregations, and empty results."""
    # 1. Scalar count
    ans_count = answer_generator.generate(
        question="How many users are registered?",
        result=720,
        plan=QueryPlan(intent="count"),
    )
    assert "720" in ans_count

    # 2. Scalar average
    ans_avg = answer_generator.generate(
        question="What is the average transaction value?",
        result=45.5,
        plan=QueryPlan(intent="aggregation", aggregation="average"),
    )
    assert "45.5" in ans_avg

    # 3. Empty result
    ans_empty = answer_generator.generate(
        question="Show users with status suspended",
        result=[],
        plan=QueryPlan(intent="lookup"),
    )
    assert any(term in ans_empty.lower() for term in ["no", "none", "not found", "0 matching"])
