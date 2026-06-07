"""Final response synthesis for the v2 graph.

Transforms raw task progress, browser results, and failure history into
a polished, concise J.A.R.V.I.S-style response. Never exposes internal
tool names, element IDs, DOM content, or execution details.
"""

from __future__ import annotations

import os
import re
from typing import Any

from workflows.v2.state import JarvisState, ensure_state_defaults


SYNTHESIZER_PROMPT = """You are J.A.R.V.I.S delivering a final briefing to Sir.

Given the raw execution summary below, produce a concise, polished response.

RULES:
- Address the user as "Sir"
- NEVER mention tool names, element IDs, DOM content, browser actions, or internal details
- NEVER say "I navigated to...", "I clicked...", "I observed...", "browser_observe", etc.
- Compress aggressively: if 10 lines can be said in 2, prefer 2
- Extract ONLY key findings, prices, facts, recommendations
- Use natural spoken English with slight British wit
- 3-5 sentences maximum for simple tasks, structured bullets for comparisons
- If you have specific data (prices, names, ratings), include them precisely
- If the task failed, explain what went wrong simply without technical details

RAW EXECUTION SUMMARY:
{raw_summary}

USER'S ORIGINAL GOAL:
{user_goal}

Produce ONLY the final spoken response. No preamble, no markdown, no tool references."""


def _strip_internal_noise(text: str) -> str:
    """Remove common internal artifacts from raw progress/result strings."""
    # Remove tool names and element references
    text = re.sub(r"\bbrowser_\w+\b", "", text)
    text = re.sub(r"\bfile_\w+\b", "", text)
    text = re.sub(r"\bwhatsapp_\w+\b", "", text)
    text = re.sub(r"\bweather_check\b", "", text)
    text = re.sub(r"\belement[_ ](?:id|ID)?\s*[:=]?\s*\d+", "", text)
    text = re.sub(r"observation_id\s*[:=]\s*\S+", "", text)
    text = re.sub(r"page_fingerprint\s*[:=]\s*\S+", "", text)
    text = re.sub(r"\[Tool\].*", "", text)
    text = re.sub(r"\[TELEMETRY\].*", "", text)
    # Clean up extra whitespace
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def _build_raw_summary(state: JarvisState) -> str:
    """Gather all relevant execution data into a compact raw summary."""
    parts = []

    # Task progress
    progress = state.get("task_progress") or []
    if progress:
        parts.append("Progress: " + " | ".join(progress[-5:]))

    # Browser execution results
    browser_results = state.get("browser_execution_results") or []
    for br in browser_results[-3:]:
        summary = getattr(br, "summary", "") or ""
        if summary:
            parts.append(f"Result: {summary[:500]}")

    # Plan step results
    plan = state.get("task_plan") or []
    for step in plan:
        result = getattr(step, "result", "") or ""
        if result and step.status == "completed":
            parts.append(f"Step '{step.description}': {result[:500]}")

    # Failure info
    failures = state.get("failure_history") or []
    if failures:
        last = failures[-1]
        parts.append(f"Last failure: {getattr(last, 'category', 'unknown')} - {getattr(last, 'error_message', '')}")

    raw = "\n".join(parts) if parts else "Task completed but no detailed results were captured."
    return _strip_internal_noise(raw)


async def _llm_synthesize(raw_summary: str, user_goal: str) -> str | None:
    """Use the LLM to produce a polished response from raw data."""
    try:
        from langchain_aws import ChatBedrockConverse
        from langchain_core.messages import HumanMessage

        model_id = os.getenv("CLAUDE_MODEL_ID", "us.amazon.nova-pro-v1:0")
        region = os.getenv("AWS_BEDROCK_REGION", "us-east-1")

        llm = ChatBedrockConverse(
            model=model_id,
            region_name=region,
            temperature=0.3,
            max_tokens=400,
        )

        prompt = SYNTHESIZER_PROMPT.format(
            raw_summary=raw_summary,
            user_goal=user_goal,
        )

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        return str(content).strip() if content else None
    except Exception as exc:
        print(f"[Synthesizer] LLM polish failed, using cleaned fallback: {exc}")
        return None


def _fallback_synthesis(state: JarvisState) -> str:
    """Produce a basic cleaned-up response without the LLM."""
    status = state.get("completion_status", "completed")
    progress = state.get("task_progress") or []
    failures = state.get("failure_history") or []

    if status == "completed":
        if progress:
            cleaned = _strip_internal_noise(" ".join(progress[-3:]))
            return f"Done, sir. {cleaned}" if cleaned else "Done, sir. The requested task has been completed."
        return "Done, sir. The requested task has been completed."
    elif status == "needs_user":
        return state.get("final_answer") or "I need your input before continuing, sir."
    elif failures:
        last = failures[-1]
        error = _strip_internal_noise(getattr(last, "error_message", "unknown issue"))
        return f"I wasn't able to complete that, sir. {error}"
    else:
        return "I stopped before I could verify completion, sir."


async def synthesize_final_response_async(state: JarvisState) -> JarvisState:
    """Async version — uses LLM to polish the final response."""
    state = ensure_state_defaults(state)
    if state.get("final_answer"):
        return state

    raw_summary = _build_raw_summary(state)
    user_goal = state.get("user_goal", "")

    # Try LLM-polished response first
    answer = await _llm_synthesize(raw_summary, user_goal)

    # Fall back to basic cleaned response
    if not answer:
        answer = _fallback_synthesis(state)

    return {**state, "final_answer": answer}


def synthesize_final_response(state: JarvisState) -> JarvisState:
    """Sync fallback — used when the graph node must be synchronous."""
    state = ensure_state_defaults(state)
    if state.get("final_answer"):
        return state

    answer = _fallback_synthesis(state)
    return {**state, "final_answer": answer}
