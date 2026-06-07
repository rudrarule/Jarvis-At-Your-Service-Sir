"""Information-sufficiency gate for J.A.R.V.I.S.

Detects incomplete user requests (e.g. "find me the best laptop") and asks one
round of targeted clarification questions instead of executing on assumptions.

Design:
  * Heuristic fast-path skips self-contained commands (no LLM cost).
  * A single cheap Nova-Lite call scores sufficiency for ambiguous requests.
  * FAIL-OPEN: any error / disabled flag -> treat as sufficient (never block).
  * Flag: JARVIS_CLARIFY (default on). Threshold: JARVIS_CLARIFY_THRESHOLD (0.70).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field


@dataclass
class ClarificationResult:
    sufficient: bool = True
    confidence: float = 1.0
    missing_fields: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    category: str = "general"


SUFFICIENCY_SYSTEM_PROMPT = """You are an information sufficiency analyzer for J.A.R.V.I.S, an AI assistant.

Analyze whether the user's request has enough information to execute successfully.

Categories that REQUIRE specific details:
- SHOPPING: product name required. Budget, brand preferences, and size are helpful.
- TRAVEL: destination, dates required. Budget, class, number of travelers helpful.
- BOOKING: venue/service, date/time required. Number of guests, preferences helpful.
- FOOD_ORDER: restaurant or cuisine required. Delivery address, dietary preferences helpful.
- RESEARCH: topic required. Depth, specific aspects, time period helpful.
- COMMUNICATION: recipient required. Message content required.

Categories that are SELF-SUFFICIENT (always return sufficient=true):
- GREETING, STATUS_CHECK, SYSTEM_COMMAND, SIMPLE_QUERY

Be lenient: only ask when a key parameter is genuinely missing. If the request is
specific enough to act on, return sufficient=true with high confidence.

Return compact JSON only:
{
  "sufficient": true/false,
  "confidence": 0.0-1.0,
  "category": "shopping|travel|booking|food_order|research|communication|general|self_sufficient",
  "missing_fields": ["field1", "field2"],
  "questions": ["Natural question 1?", "Natural question 2?"]
}"""


# Self-contained commands that never need clarification (skip the LLM entirely).
_SKIP_PATTERNS = [
    r"^\s*(hi|hello|hey|yo|sup|thanks|thank you|ok|okay|cool|nice|great)\b",
    r"\bhttps?://",                               # explicit URL present
    r"^\s*(open|launch|start|close|quit|kill)\s+\S+",
    r"^\s*play\b",                                # play <song/media>
    r"\b(weather|temperature|forecast|humidity)\b",
    r"^\s*(lock|shutdown|restart|sleep|hibernate)\b",
    r"^\s*(what'?s up|how are you|you there|you ok|you okay)\b",
    r"^\s*(what'?s|whats) the time\b|^\s*time\b",
]


def _clarify_enabled() -> bool:
    return os.getenv("JARVIS_CLARIFY", "true").strip().lower() in {"1", "true", "yes", "on"}


def _heuristic_skip(message: str) -> bool:
    t = (message or "").lower().strip()
    if not t:
        return True
    if len(t.split()) <= 1:           # single token ("hi", "status")
        return True
    return any(re.search(p, t) for p in _SKIP_PATTERNS)


async def needs_clarification(
    user_message: str,
    memory_context: str = "",
    session_history: list[dict] | None = None
) -> ClarificationResult:
    """Return a ClarificationResult. sufficient=True means proceed; False means ask."""
    if not _clarify_enabled():
        return ClarificationResult()

    # Single-round clarification: check if we already asked clarification in the last assistant response
    if session_history:
        for msg in reversed(session_history):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if "Before I proceed, sir" in content:
                    print("[Clarify] Already asked clarification in the last assistant response. Proceeding to execution.")
                    return ClarificationResult(sufficient=True)
                break

    if _heuristic_skip(user_message):
        return ClarificationResult()

    try:
        import asyncio

        from services.llm_service import _get_bedrock_client

        client = _get_bedrock_client()
        
        # Combine recent session history to understand context
        user_block = user_message
        if session_history:
            history_lines = []
            for m in session_history[-5:]:
                role = m.get("role", "user").upper()
                content = m.get("content", "")
                if "Before I proceed, sir" in content:
                    continue
                history_lines.append(f"{role}: {content}")
            if history_lines:
                history_str = "\n".join(history_lines)
                user_block = f"[Context History]\n{history_str}\n\n[New User Request]\n{user_message}"

        if memory_context:
            user_block += f"\n\n[Known user preferences]\n{memory_context}"

        model_id = os.getenv(
            "JARVIS_CLARIFY_MODEL_ID",
            os.getenv("JARVIS_ROUTER_MODEL_ID", "us.amazon.nova-lite-v1:0"),
        )
        resp = await asyncio.to_thread(
            client.converse,
            modelId=model_id,
            system=[{"text": SUFFICIENCY_SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_block}]}],
            inferenceConfig={"maxTokens": 220, "temperature": 0},
        )
        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        text = " ".join(b.get("text", "") for b in blocks)
        s, e = text.find("{"), text.rfind("}")
        data = json.loads(text[s:e + 1]) if (s >= 0 and e > s) else {}

        llm_sufficient = bool(data.get("sufficient", True))
        confidence = float(data.get("confidence", 1.0) or 1.0)
        threshold = float(os.getenv("JARVIS_CLARIFY_THRESHOLD", "0.70"))
        sufficient = llm_sufficient and confidence >= threshold

        result = ClarificationResult(
            sufficient=sufficient,
            confidence=confidence,
            missing_fields=list(data.get("missing_fields") or []),
            questions=list(data.get("questions") or []),
            category=str(data.get("category") or "general"),
        )
        print(f"[Clarify] sufficient={result.sufficient} conf={result.confidence:.2f} "
              f"cat={result.category} missing={result.missing_fields}")
        return result
    except Exception as exc:
        print(f"[Clarify] sufficiency check failed, proceeding (fail-open): {exc}")
        return ClarificationResult()  # never block the user on error


def format_clarification_response(result: ClarificationResult) -> str:
    questions = result.questions or [
        f"Could you specify the {f}?" for f in (result.missing_fields or ["key details"])
    ]
    bullets = "\n".join(f" • {q}" for q in questions[:4])
    return (
        "Before I proceed, sir — a few details would help me serve you better:\n"
        f"{bullets}\n"
        "Share those and I'll take care of the rest."
    )
