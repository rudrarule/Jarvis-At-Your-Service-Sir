"""Tests for the information-sufficiency clarification gate.

The pure tests (heuristics, formatting, dataclass) run anywhere. The LLM
sufficiency tests need Bedrock access and are skipped if boto3/creds are absent.
"""
import os

import pytest

from services.clarification import (
    ClarificationResult,
    _heuristic_skip,
    format_clarification_response,
    needs_clarification,
)


# ── Pure / offline tests ─────────────────────────────────────
@pytest.mark.parametrize("msg", [
    "open youtube",
    "play bohemian rhapsody",
    "what's the weather",
    "hi",
    "lock system",
    "shutdown",
    "visit https://example.com for me",
    "thanks",
    "status",
])
def test_heuristic_skips_self_contained(msg):
    assert _heuristic_skip(msg) is True


@pytest.mark.parametrize("msg", [
    "find me the best laptop",
    "book me a hotel",
    "order food from swiggy",
    "find flights",
])
def test_heuristic_does_not_skip_ambiguous(msg):
    assert _heuristic_skip(msg) is False


def test_result_defaults_are_sufficient():
    r = ClarificationResult()
    assert r.sufficient is True
    assert r.confidence == 1.0


def test_format_response_contains_questions():
    r = ClarificationResult(
        sufficient=False, confidence=0.4,
        missing_fields=["budget", "os"],
        questions=["What's your budget range?", "Preferred operating system?"],
    )
    out = format_clarification_response(r)
    assert "budget" in out.lower()
    assert "•" in out


@pytest.mark.asyncio
async def test_disabled_flag_is_fail_open(monkeypatch):
    monkeypatch.setenv("JARVIS_CLARIFY", "false")
    r = await needs_clarification("find me a good phone")
    assert r.sufficient is True  # disabled -> never blocks


@pytest.mark.asyncio
async def test_session_history_bypass():
    # No clarification in history -> should not bypass
    # (heuristics don't match "find me a laptop", so it proceeds to LLM check)
    r1 = await needs_clarification("find me a laptop", session_history=[])
    assert r1.sufficient is False
    
    # Clarification in history -> should immediately bypass and return sufficient=True
    history = [
        {"role": "user", "content": "find me a laptop"},
        {"role": "assistant", "content": "Before I proceed, sir — a few details would help me serve you better:\n • What's your budget?"}
    ]
    r2 = await needs_clarification("budget is 80k", session_history=history)
    assert r2.sufficient is True


# ── Integration tests (require Bedrock) ──────────────────────
_HAS_BEDROCK = bool(os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"))


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_BEDROCK, reason="Bedrock creds not configured")
@pytest.mark.parametrize("msg,expect_sufficient", [
    ("Find me the best laptop", False),
    ("Book me a hotel", False),
    ("Find flights", False),
    ("Search for iPhone 16 Pro Max price on Amazon and Flipkart", True),
    ("Find flights from Delhi to Goa on June 29 for 2 adults", True),
])
async def test_llm_sufficiency(monkeypatch, msg, expect_sufficient):
    monkeypatch.setenv("JARVIS_CLARIFY", "true")
    r = await needs_clarification(msg)
    assert r.sufficient is expect_sufficient
