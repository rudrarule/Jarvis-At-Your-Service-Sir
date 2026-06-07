"""Strategic Planner Agent node for the J.A.R.V.I.S v2 graph."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from workflows.v2.state import (
    JarvisState,
    PlannerReasoningEntry,
    TaskStep,
    ensure_state_defaults,
    first_pending_step_index,
    get_current_step,
    model_to_dict,
    replace_current_step,
)


PLANNER_SYSTEM_PROMPT = """You are the Strategic Planner for J.A.R.V.I.S.

You optimize for browser automation as the primary capability. Your job is to
decompose the user's goal into a short, executable plan, define success
criteria, evaluate execution results, and re-plan when browser execution fails.

Boundaries:
- You do not click, type, scroll, inspect selectors, or choose element IDs.
- You do not call browser tools directly.
- You assign browser objectives to the Browser Agent and non-browser work to
  system agents such as file, WhatsApp, memory, or utility executors.

Planning rules:
- Keep plans to 2-5 outcome-oriented steps.
- Browser steps should say what must be achieved on the page, not how to click.
- Every step must include concrete observable success criteria.
- If a browser step fails repeatedly, choose a meaningfully different route.
- Prefer direct URLs for known sites instead of search engines.
- Mark risky communication or checkout/payment actions as requires_confirmation.

Travel & Booking Form-Filling Rule:
- For travel booking or complex form-filling requests (e.g. searching flights/hotels on Skyscanner, Kayak, MakeMyTrip, etc.), split the flow into explicit, discrete browser tasks:
  1. Navigate to the website.
  2. Input locations (origin/destination) and explicitly instruct the Browser Agent to wait for and select the appropriate autocomplete dropdown options.
  3. Select dates (departure/return).
  4. Submit search and wait for results page.
  This allows the Browser Agent to focus on precise, micro-actions per step rather than trying to perform the entire form-fill in one turn.

Return JSON only using this schema:
{
  "reasoning": "why this plan or replan is appropriate",
  "status": "executing | completed | failed | needs_user",
  "next_objective": "short description of the next objective",
  "steps": [
    {
      "id": "step_1",
      "description": "outcome-oriented task",
      "success_criteria": "observable success condition",
      "assigned_agent": "browser | system",
      "objective_type": "navigate | browser_task | verify | file | whatsapp | memory | utility",
      "params": {"optional": "hints"},
      "requires_confirmation": false
    }
  ]
}
"""


class PlannerDecision(BaseModel):
    reasoning: str = Field(default="")
    status: str = Field(default="executing")
    next_objective: str = Field(default="")
    steps: list[TaskStep] = Field(default_factory=list)


KNOWN_SITE_URLS = {
    "swiggy": "https://www.swiggy.com",
    "zomato": "https://www.zomato.com",
    "bigbasket": "https://www.bigbasket.com",
    "blinkit": "https://blinkit.com",
    "zepto": "https://www.zepto.co",
    "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com",
    "makemytrip": "https://www.makemytrip.com",
    "goibibo": "https://www.goibibo.com",
    "ixigo": "https://www.ixigo.com",
    "irctc": "https://www.irctc.co.in",
    "booking": "https://www.booking.com",
}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _make_search_url(goal: str) -> str:
    cleaned = re.sub(r"\b(?:jarvis|please|search|find|open|compare|research)\b", " ", goal, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip() or goal
    return "https://duckduckgo.com/?q=" + urllib.parse.quote(cleaned)


def _extract_direct_url(goal: str) -> str:
    match = re.search(r"https?://[^\s]+", goal)
    if match:
        return match.group(0).rstrip(".,)")
    match = re.search(r"\b(?:www\.)?([A-Za-z0-9-]+\.(?:com|in|org|net|io))(?:/[^\s]*)?", goal)
    if match:
        raw = match.group(0).rstrip(".,)")
        return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"
    text = goal.lower()
    for keyword, url in KNOWN_SITE_URLS.items():
        if keyword in text:
            return url
    if "flight" in text:
        return KNOWN_SITE_URLS["makemytrip"]
    if "hotel" in text:
        return KNOWN_SITE_URLS["booking"]
    return ""


def _fallback_plan(goal: str, failures: list[Any] | None = None) -> PlannerDecision:
    failures = failures or []
    direct_url = _extract_direct_url(goal)
    steps: list[TaskStep] = []

    if direct_url:
        steps.append(
            TaskStep(
                id="step_1",
                description=f"Open the most relevant site for the goal: {direct_url}",
                success_criteria=f"The browser is loaded at or redirected from {direct_url}.",
                assigned_agent="browser",
                objective_type="navigate",
                params={"url": direct_url},
            )
        )
    else:
        search_url = _make_search_url(goal)
        steps.append(
            TaskStep(
                id="step_1",
                description="Open a search results page for the user's browser task.",
                success_criteria="Search results or a relevant page are visible in the browser.",
                assigned_agent="browser",
                objective_type="navigate",
                params={"url": search_url},
            )
        )

    steps.append(
        TaskStep(
            id="step_2",
            description=f"Complete the browser objective for this user goal: {goal}",
            success_criteria=(
                "The page visibly contains the information, form state, cart state, or confirmation "
                "needed to answer the user's goal. Stop before payment or irreversible actions."
            ),
            assigned_agent="browser",
            objective_type="browser_task",
            params={"user_goal": goal},
            max_attempts=3,
        )
    )

    if any(word in goal.lower() for word in ("whatsapp", "message", "text", "send")):
        steps.append(
            TaskStep(
                id="step_3",
                description="Prepare the communication requested by the user after browser work is complete.",
                success_criteria="A message draft or sent-message confirmation exists, depending on user confirmation.",
                assigned_agent="system",
                objective_type="whatsapp",
                params={"tool_name": "whatsapp_send_message"},
                requires_confirmation=True,
            )
        )

    reason = "Created a conservative browser-first fallback plan."
    if failures:
        reason += " Prior failures were preserved for the Browser Agent and recovery node."
    return PlannerDecision(reasoning=reason, status="executing", next_objective=steps[0].description, steps=steps)


def _validate_planner_decision(data: dict[str, Any] | None, goal: str) -> PlannerDecision:
    if not data:
        return _fallback_plan(goal)

    steps = []
    for index, raw in enumerate(data.get("steps") or [], start=1):
        if not isinstance(raw, dict):
            continue
        try:
            raw.setdefault("id", f"step_{index}")
            raw.setdefault("assigned_agent", "browser")
            raw.setdefault("objective_type", "browser_task")
            raw.setdefault("success_criteria", "The requested outcome is visible or verifiable.")
            steps.append(TaskStep(**raw))
        except Exception:
            continue

    if not steps and data.get("status") not in {"completed", "failed", "needs_user"}:
        return _fallback_plan(goal)

    return PlannerDecision(
        reasoning=str(data.get("reasoning") or "Planner returned a validated plan."),
        status=str(data.get("status") or "executing"),
        next_objective=str(data.get("next_objective") or (steps[0].description if steps else "")),
        steps=steps,
    )


def _planner_input(state: JarvisState) -> str:
    compact_state = {
        "user_goal": state.get("user_goal", ""),
        "current_step_index": state.get("current_step_index", 0),
        "task_plan": [model_to_dict(step) for step in state.get("task_plan", [])],
        "recent_browser_results": [
            model_to_dict(item) for item in (state.get("browser_execution_results") or [])[-3:]
        ],
        "recent_failures": [model_to_dict(item) for item in (state.get("failure_history") or [])[-5:]],
        "task_progress": (state.get("task_progress") or [])[-8:],
    }
    return json.dumps(compact_state, ensure_ascii=True, default=str)


async def _call_planner_llm(state: JarvisState) -> PlannerDecision | None:
    if not _env_bool("JARVIS_V2_USE_LLM_PLANNER", True):
        return None

    try:
        from langchain_aws import ChatBedrockConverse
    except Exception:
        return None

    model_id = os.getenv("JARVIS_V2_PLANNER_MODEL_ID", os.getenv("CLAUDE_MODEL_ID", "us.amazon.nova-pro-v1:0"))
    region = os.getenv("AWS_BEDROCK_REGION", "us-west-1")

    print(f"[TELEMETRY][PLANNER] Requesting plan from Planner LLM model: {model_id} (Region: {region})")
    try:
        llm = ChatBedrockConverse(
            model=model_id,
            region_name=region,
            temperature=float(os.getenv("JARVIS_V2_PLANNER_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("JARVIS_V2_PLANNER_MAX_TOKENS", "1600")),
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=PLANNER_SYSTEM_PROMPT),
                HumanMessage(content=_planner_input(state)),
            ]
        )
        content = response.content
        if isinstance(content, list):
            content = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
        extracted_json = _extract_json_object(str(content))
        print(f"[TELEMETRY][PLANNER] LLM Response raw: {content}")
        return _validate_planner_decision(extracted_json, state.get("user_goal", ""))
    except Exception as exc:
        print(f"[JarvisV2 Planner] LLM planner unavailable, using fallback plan: {exc}")
        return None


def _append_reasoning(state: JarvisState, entry: PlannerReasoningEntry) -> list[PlannerReasoningEntry]:
    return list(state.get("planner_reasoning") or [])[-20:] + [entry]


async def plan_next_action(state: JarvisState) -> JarvisState:
    """Create, advance, or revise the task plan."""

    state = ensure_state_defaults(state)
    plan = [step if isinstance(step, TaskStep) else TaskStep(**step) for step in state.get("task_plan", [])]
    current_index = state.get("current_step_index", 0)
    current_step = get_current_step({**state, "task_plan": plan})

    print(f"\n[TELEMETRY][PLANNER] ========================================================")
    print(f"[TELEMETRY][PLANNER] Entering Planner Node.")
    print(f"[TELEMETRY][PLANNER] Current Step Index: {current_index} | Plan length: {len(plan)}")
    if current_step:
        print(f"[TELEMETRY][PLANNER] Current Step ID: '{current_step.id}' | Status: '{current_step.status}' | Description: '{current_step.description}'")
    print(f"[TELEMETRY][PLANNER] ========================================================")

    if state.get("completion_status") in {"completed", "failed", "needs_user"}:
        print(f"[TELEMETRY][PLANNER] completion_status is already '{state.get('completion_status')}'. No action taken.")
        return state

    # Existing step just completed: advance to the next pending step.
    if current_step and current_step.status == "completed":
        next_index = first_pending_step_index(plan, current_index + 1)
        if next_index is None:
            print(f"[TELEMETRY][PLANNER] All steps completed! Finalizing goal.")
            return {
                **state,
                "task_plan": plan,
                "completion_status": "completed",
                "planner_reasoning": _append_reasoning(
                    state,
                    PlannerReasoningEntry(
                        decision_type="complete",
                        reasoning="All planned steps are completed.",
                        plan_version=state.get("plan_version", 0),
                    ),
                ),
            }
        print(f"[TELEMETRY][PLANNER] Advancing to next step index {next_index}: {plan[next_index].id}")
        return {
            **state,
            "task_plan": plan,
            "current_step_index": next_index,
            "completion_status": "executing",
            "planner_reasoning": _append_reasoning(
                state,
                PlannerReasoningEntry(
                    decision_type="advance",
                    reasoning=f"Advancing to {plan[next_index].id}.",
                    next_step_id=plan[next_index].id,
                    plan_version=state.get("plan_version", 0),
                ),
            ),
        }

    # Hard failure remains planner-owned. Re-plan once the recovery node has
    # recorded enough context or the Browser Agent asked for a new route.
    if current_step and current_step.status == "failed":
        print(f"[TELEMETRY][PLANNER] Step failed. Invoking re-planner LLM...")
        decision = await _call_planner_llm(state)
        if decision is None:
            print(f"[TELEMETRY][PLANNER] Planner LLM failed/unavailable. Using fallback plan.")
            decision = _fallback_plan(state.get("user_goal", ""), state.get("failure_history", []))
            decision.reasoning = "Re-planned with fallback logic after a failed browser step."

        plan_version = state.get("plan_version", 0) + 1
        print(f"[TELEMETRY][PLANNER] Re-plan generated: status={decision.status} | version={plan_version} | steps={len(decision.steps)}")
        for i, s in enumerate(decision.steps):
            print(f"  - Step {i+1} [{s.assigned_agent.upper()}]: {s.description} (Criteria: {s.success_criteria})")
        return {
            **state,
            "task_plan": decision.steps,
            "current_step_index": 0,
            "completion_status": "executing" if decision.status == "executing" else decision.status,
            "plan_version": plan_version,
            "planner_reasoning": _append_reasoning(
                state,
                PlannerReasoningEntry(
                    decision_type="replan",
                    reasoning=decision.reasoning,
                    next_step_id=decision.steps[0].id if decision.steps else None,
                    plan_version=plan_version,
                ),
            ),
        }

    # Initial plan.
    if not plan:
        # ── Information Sufficiency Gate (catches direct v2 invocation; fail-open) ──
        try:
            from services.clarification import needs_clarification, format_clarification_response

            _clar = await needs_clarification(state.get("user_goal", ""), "")
            if not _clar.sufficient:
                print("[TELEMETRY][PLANNER] Request needs clarification — pausing for user input.")
                return {
                    **state,
                    "completion_status": "needs_user",
                    "final_answer": format_clarification_response(_clar),
                }
        except Exception as exc:
            print(f"[TELEMETRY][PLANNER] Clarification gate skipped: {exc}")

        print(f"[TELEMETRY][PLANNER] No plan exists. Invoking planner LLM to generate initial plan...")
        decision = await _call_planner_llm(state)
        if decision is None:
            print(f"[TELEMETRY][PLANNER] Planner LLM failed/unavailable. Using fallback plan.")
            decision = _fallback_plan(state.get("user_goal", ""))
        plan_version = state.get("plan_version", 0) + 1
        status = decision.status if decision.status in {"completed", "failed", "needs_user"} else "executing"
        print(f"[TELEMETRY][PLANNER] Initial plan generated: status={status} | version={plan_version} | steps={len(decision.steps)}")
        for i, s in enumerate(decision.steps):
            print(f"  - Step {i+1} [{s.assigned_agent.upper()}]: {s.description} (Criteria: {s.success_criteria})")
        return {
            **state,
            "task_plan": decision.steps,
            "current_step_index": 0,
            "completion_status": status,
            "plan_version": plan_version,
            "planner_reasoning": _append_reasoning(
                state,
                PlannerReasoningEntry(
                    decision_type="initial_plan",
                    reasoning=decision.reasoning,
                    next_step_id=decision.steps[0].id if decision.steps else None,
                    plan_version=plan_version,
                ),
            ),
            "task_progress": list(state.get("task_progress") or []) + [f"Plan created with {len(decision.steps)} step(s)."],
        }

    # Continue executing the current pending step.
    if current_step and current_step.status in {"pending", "running"}:
        print(f"[TELEMETRY][PLANNER] Continuing execution of current step: {current_step.id}")
        return {**state, "task_plan": plan, "completion_status": "executing"}

    # Defensive fallback if the index drifted.
    next_index = first_pending_step_index(plan, 0)
    print(f"[TELEMETRY][PLANNER] Index drifted. Defensive fallback next index: {next_index}")
    if next_index is None:
        return {**state, "task_plan": plan, "completion_status": "completed"}
    return {**state, "task_plan": plan, "current_step_index": next_index, "completion_status": "executing"}
