from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.conversation.conversation_memory import (
    ConversationMemory,
    ConversationMemoryError,
)
from app.orchestration.database_orchestrator import (
    DatabaseOrchestrationError,
    DatabaseOrchestrator,
)
from app.query.answer_generator import (
    AnswerGenerationError,
    AnswerGenerator,
)


router = APIRouter()
orchestrator = DatabaseOrchestrator()
answer_generator = AnswerGenerator()
conversation_memory = ConversationMemory()


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None


@router.post("/ask/database")
def ask_database_question(
    request: AskRequest,
) -> dict[str, Any]:
    question = (request.question or "").strip()
    session_id = (request.session_id or "").strip() or None

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    # ----------------------------------------------------------
    # 1. Load previous conversation context.
    # ----------------------------------------------------------

    conversation_context: dict[str, Any] = {}

    if session_id:
        try:
            conversation_context = conversation_memory.get_context(
                session_id=session_id,
            )
        except ConversationMemoryError as exc:
            raise HTTPException(
                status_code=500,
                detail=str(exc),
            ) from exc

    # ----------------------------------------------------------
    # 2. Analyze and execute using the previous context.
    # ----------------------------------------------------------

    try:
        result = orchestrator.answer(
            question=question,
            conversation_context=conversation_context,
        )
    except DatabaseOrchestrationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    # ----------------------------------------------------------
    # 3. Generate the natural-language answer.
    # ----------------------------------------------------------

    # TEMPORARY DIAGNOSTIC:
    # Inspect the exact deterministic result that reaches
    # AnswerGenerator. This is intentionally placed here so
    # we can determine whether missing values are caused by
    # query execution or by natural-language generation.
    print("\n========== ANSWER GENERATOR INPUT ==========")
    print("QUESTION:", question)
    print("RESULT TYPE:", type(result.data).__name__)
    print("RESULT DATA:", result.data)
    print("============================================\n")

    try:
        natural_answer = answer_generator.generate(
            question=question,
            result=result.data,
            plan=result.plan,
            semantic_schema=orchestrator.schema,
            warnings=result.warnings,
        )
    except AnswerGenerationError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    # ----------------------------------------------------------
    # 4. Persist the verified result for future follow-ups.
    # ----------------------------------------------------------

    reference_id = None

    if session_id:
        try:
            reference_id = conversation_memory.save(
                session_id=session_id,
                question=question,
                result=result.data,
                plan=result.plan,
                tables=getattr(result, "tables", None),
            )
        except ConversationMemoryError as exc:
            raise HTTPException(
                status_code=500,
                detail=str(exc),
            ) from exc

    return {
        "ok": True,
        "answer": natural_answer,
        "warnings": result.warnings,
        "intent": result.plan.intent,
        "reference_id": reference_id,
    }