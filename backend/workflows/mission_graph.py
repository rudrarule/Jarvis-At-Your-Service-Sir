"""
mission_graph.py - Planner/Executor/Verifier workflow for complex goals.

This graph is intentionally conservative: it decomposes common missions into
small steps, executes only low-risk tools, and leaves risky actions for a
future confirmation/resume phase.
"""
import inspect
import json
import os
import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from workflows.tool_wrapper import ALL_TOOLS

MAX_STEP_RETRIES = int(os.getenv("MISSION_MAX_STEP_RETRIES", "2"))


class MissionState(TypedDict, total=False):
    user_goal: str
    session_id: str
    plan: list[dict[str, Any]]
    current_step: int
    step_results: list[dict[str, Any]]
    verified: bool
    errors: list[str]
    pending_confirmation: list[dict[str, Any]]
    final_answer: str
    retry_counts: dict[str, int]
    step_verifications: list[dict[str, Any]]
    events: list[dict[str, Any]]


RISKY_TOOLS = {"whatsapp_send_message"}
ALLOWED_MISSION_TOOLS = {
    "browser_open_url",
    "browser_observe",
    "browser_scroll",
    "browser_get_status",
    "browser_go_back",
    "weather_check",
    "file_read",
    "file_write",
    "file_list",
    "file_search",
    "whatsapp_check_messages",
    "whatsapp_send_message",
}
_active_missions: dict[str, MissionState] = {}


def _tool_map() -> dict[str, Any]:
    return {tool.name: tool for tool in ALL_TOOLS}


def _extract_file_path(goal: str) -> str:
    match = re.search(r"\b(?:to|as|in)\s+([A-Za-z0-9_\-/\\]+(?:\.(?:txt|md|json|py)))\b", goal)
    if match:
        return match.group(1).replace("\\", "/")
    return "mission_notes.md"


def _extract_weather_location(goal: str) -> str:
    match = re.search(
        r"\bweather\s+(?:in|for|at)\s+([A-Za-z ,.-]+?)(?:\s+(?:and|save|with|the|to|at)\b|$)",
        goal,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" .,")
    return ""


def _extract_message_contact(goal: str) -> str:
    match = re.search(
        r"\b(?:message|text|whatsapp)\s+([A-Za-z0-9 _.-]{1,30}?)(?:\s+(?:the|a|this|that|summary|about|to|and)\b|$)",
        goal,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" .,")
    match = re.search(r"\bto\s+([A-Za-z0-9 _.-]{1,30})\b", goal, re.IGNORECASE)
    if match:
        return match.group(1).strip(" .,")
    return ""


def _make_search_url(goal: str) -> str:
    query = re.sub(r"\b(?:jarvis|please|research|find|search|compare|save|message|text)\b", " ", goal, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query).strip() or goal
    return "https://duckduckgo.com/?q=" + urllib.parse.quote(query)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def _emit_mission_event(event_type: str, payload: dict[str, Any], level: str = "info") -> None:
    try:
        from services.dashboard_event_service import emit_dashboard_event

        await emit_dashboard_event(event_type, payload, source="mission", level=level)
    except Exception as exc:
        print(f"[Mission Telemetry] Failed to emit {event_type}: {exc}")


def _tool_result_success(output: Any) -> bool:
    if isinstance(output, dict):
        if output.get("success") is False:
            return False
        if output.get("error"):
            return False
        return True

    text = str(output).lower()
    failure_markers = [
        "failed",
        "couldn't",
        "could not",
        "error:",
        "encountered an error",
        "timeout",
        "not available",
    ]
    return not any(marker in text for marker in failure_markers)


def _verify_step_output(step: dict[str, Any], args: dict[str, Any], output: Any) -> dict[str, Any]:
    tool_name = step.get("tool")
    base_passed = _tool_result_success(output)
    confidence = 0.82 if base_passed else 0.25
    reason = "tool_reported_success" if base_passed else "tool_reported_failure"

    if tool_name == "browser_open_url" and isinstance(output, dict):
        data = output.get("data") or {}
        passed = base_passed and (bool(data.get("url")) or output.get("success") is True)
        return {
            "passed": passed,
            "confidence": 0.9 if data.get("url") else (0.72 if passed else 0.35),
            "reason": "url_loaded" if data.get("url") else ("tool_success_without_url_delta" if passed else "browser_url_missing_after_open"),
        }

    if tool_name == "browser_observe" and isinstance(output, dict):
        data = output.get("data") or {}
        passed = base_passed and (
            bool(data.get("url") or data.get("summary") or data.get("interactive_elements"))
            or output.get("success") is True
        )
        return {
            "passed": passed,
            "confidence": 0.9 if data else (0.72 if passed else 0.35),
            "reason": "page_observation_available" if data else ("tool_success_without_observation_payload" if passed else "empty_browser_observation"),
        }

    if tool_name == "file_write":
        text = str(output).lower()
        passed = base_passed and ("written" in text or "success" in text or isinstance(output, dict))
        return {
            "passed": passed,
            "confidence": 0.88 if passed else 0.30,
            "reason": "file_write_acknowledged" if passed else "file_write_not_confirmed",
        }

    if tool_name == "whatsapp_send_message":
        text = str(output).lower()
        passed = base_passed and any(marker in text for marker in ("sent", "success", "done"))
        return {
            "passed": passed,
            "confidence": 0.86 if passed else 0.35,
            "reason": "message_send_acknowledged" if passed else "message_send_not_confirmed",
        }

    return {"passed": base_passed, "confidence": confidence, "reason": reason}


def _is_retryable_step(step: dict[str, Any], verification: dict[str, Any]) -> bool:
    if verification.get("passed"):
        return False
    return step.get("tool") in {
        "browser_open_url",
        "browser_observe",
        "browser_scroll",
        "browser_get_status",
        "weather_check",
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _validate_step(raw_step: Any, step_id: int) -> dict[str, Any] | None:
    if not isinstance(raw_step, dict):
        return None

    tool_name = raw_step.get("tool")
    if not isinstance(tool_name, str) or tool_name not in ALLOWED_MISSION_TOOLS:
        return None

    args = raw_step.get("args") or {}
    if not isinstance(args, dict):
        return None

    if tool_name == "browser_open_url":
        url = args.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return None

    if tool_name == "file_write":
        path = args.get("path")
        if not isinstance(path, str) or not re.search(r"\.(txt|md|json|py)$", path, re.IGNORECASE):
            return None
        args["content"] = ""

    if tool_name == "whatsapp_send_message":
        contact = args.get("contact")
        if not isinstance(contact, str) or not contact.strip():
            return None
        args["message"] = ""

    risk = str(raw_step.get("risk", "")).lower()
    requires_confirmation = bool(raw_step.get("requires_confirmation")) or tool_name in RISKY_TOOLS or risk in {"high", "dangerous"}

    return {
        "id": step_id,
        "type": str(raw_step.get("type") or tool_name.split("_", 1)[0]),
        "tool": tool_name,
        "args": args,
        "instruction": str(raw_step.get("instruction") or f"Run {tool_name}."),
        "status": "pending",
        "requires_confirmation": requires_confirmation,
    }


def _validate_raw_steps(raw_steps: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list):
        return []

    plan = []
    for raw_step in raw_steps[:8]:
        step = _validate_step(raw_step, len(plan) + 1)
        if step:
            plan.append(step)
    return plan


def _validate_llm_plan(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not data:
        return []
    return _validate_raw_steps(data.get("steps"))


async def llm_plan_mission(goal: str) -> list[dict[str, Any]]:
    """
    Optional local planner. It is off by default and always validated.
    Set MISSION_USE_LLM_PLANNER=true to enable.
    """
    if not _env_bool("MISSION_USE_LLM_PLANNER", False):
        return []

    try:
        import httpx
    except ImportError:
        return []

    model = os.getenv("MISSION_PLANNER_MODEL", os.getenv("OLLAMA_MODEL", "llama3.2:3b"))
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    tool_names = ", ".join(sorted(ALLOWED_MISSION_TOOLS))
    prompt = (
        "You are a mission planner for JARVIS. Return JSON only. "
        "Create a short ordered plan using only these tools: "
        f"{tool_names}. "
        "Use browser_open_url before browser_observe for web work. "
        "Use file_write for saving notes. "
        "Use whatsapp_send_message only when the user asks to send/message/text someone, "
        "and mark it risk='high'. "
        "Schema: {\"steps\":[{\"type\":\"browser\",\"tool\":\"browser_open_url\","
        "\"args\":{\"url\":\"https://...\"},\"instruction\":\"...\",\"risk\":\"low\"}]}.\n"
        f"User goal: {goal}"
    )

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "Return valid compact JSON only. No markdown."},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{ollama_url}/api/chat", json=payload)
            response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
    except Exception as exc:
        print(f"[Mission Planner] LLM planner unavailable, using heuristic fallback: {exc}")
        return []

    plan = _validate_llm_plan(_extract_json_object(content))
    if not plan:
        print("[Mission Planner] LLM output failed validation, using heuristic fallback.")
    return plan


def _is_mission_goal(goal: str) -> bool:
    text = goal.lower()
    mission_phrases = [
        "research",
        "find and compare",
        "search and save",
        "search and message",
        "analyze and save",
        "compare",
        "summarize and save",
        "do this for me",
    ]
    compound_tool_goal = any(word in text for word in ("search", "find", "open")) and any(
        word in text for word in ("save", "message", "compare", "summarize")
    )
    return any(phrase in text for phrase in mission_phrases) or compound_tool_goal


def _heuristic_plan(goal: str) -> list[dict[str, Any]]:
    text = goal.lower()
    plan: list[dict[str, Any]] = []

    if any(word in text for word in ("research", "search", "find", "compare", "latest", "open")):
        plan.append({
            "id": len(plan) + 1,
            "type": "browser",
            "tool": "browser_open_url",
            "args": {"url": _make_search_url(goal)},
            "instruction": "Open a search page for the mission goal.",
            "status": "pending",
            "requires_confirmation": False,
        })
        plan.append({
            "id": len(plan) + 1,
            "type": "browser",
            "tool": "browser_observe",
            "args": {},
            "instruction": "Observe the current page and collect visible context.",
            "status": "pending",
            "requires_confirmation": False,
        })

    if any(word in text for word in ("weather", "temperature", "forecast", "rain")):
        plan.append({
            "id": len(plan) + 1,
            "type": "weather",
            "tool": "weather_check",
            "args": {"location": _extract_weather_location(goal)},
            "instruction": "Check weather relevant to the mission.",
            "status": "pending",
            "requires_confirmation": False,
        })

    if any(word in text for word in ("save", "note", "file")):
        plan.append({
            "id": len(plan) + 1,
            "type": "file",
            "tool": "file_write",
            "args": {"path": _extract_file_path(goal), "content": ""},
            "instruction": "Save the mission summary to a workspace file.",
            "status": "pending",
            "requires_confirmation": False,
        })

    if any(word in text for word in ("whatsapp", "message", "text")):
        plan.append({
            "id": len(plan) + 1,
            "type": "whatsapp",
            "tool": "whatsapp_send_message",
            "args": {"contact": _extract_message_contact(goal), "message": ""},
            "instruction": "Send a summary after explicit confirmation.",
            "status": "pending",
            "requires_confirmation": True,
        })

    if not plan:
        plan.append({
            "id": 1,
            "type": "analysis",
            "tool": None,
            "args": {},
            "instruction": "Explain that this goal is not specific enough for Mission Mode.",
            "status": "pending",
            "requires_confirmation": False,
        })

    return plan


async def plan_mission(state: MissionState) -> MissionState:
    goal = state["user_goal"]
    plan = _validate_raw_steps(await llm_plan_mission(goal))
    if not plan:
        plan = _heuristic_plan(goal)
    await _emit_mission_event(
        "plan.created",
        {"session_id": state.get("session_id"), "steps": plan, "step_count": len(plan)},
    )
    return {
        **state,
        "plan": plan,
        "current_step": 0,
        "step_results": [],
        "errors": [],
        "retry_counts": {},
        "step_verifications": [],
    }


def safety_gate(state: MissionState) -> MissionState:
    gated_plan = []
    pending_confirmation = []
    for step in state.get("plan", []):
        step = dict(step)
        if step.get("tool") in RISKY_TOOLS:
            step["requires_confirmation"] = True
            pending_confirmation.append(step)
        gated_plan.append(step)
    return {**state, "plan": gated_plan, "pending_confirmation": pending_confirmation}


def get_active_mission(session_id: str) -> MissionState | None:
    return _active_missions.get(session_id)


def clear_mission(session_id: str) -> None:
    _active_missions.pop(session_id, None)


def store_active_mission(session_id: str, state: MissionState) -> None:
    _active_missions[session_id] = {**state, "created_at": datetime.now()}


async def _invoke_tool(tool: Any, args: dict[str, Any]) -> Any:
    coroutine = getattr(tool, "coroutine", None)
    if coroutine:
        result = coroutine(**args)
        if inspect.isawaitable(result):
            return await result
        return result

    if hasattr(tool, "ainvoke"):
        try:
            return await tool.ainvoke(args)
        except NotImplementedError:
            pass

    func = getattr(tool, "func", None)
    if func:
        result = func(**args)
    elif hasattr(tool, "invoke"):
        try:
            result = tool.invoke(args)
        except NotImplementedError:
            result = tool(**args)
    else:
        result = tool(**args)
    if inspect.isawaitable(result):
        return await result
    return result


def _summarize_results(goal: str, results: list[dict[str, Any]]) -> str:
    lines = [f"Mission goal: {goal}", "", "Collected results:"]
    for item in results:
        status = item.get("status", "unknown")
        instruction = item.get("instruction", "Step")
        output = str(item.get("output", ""))[:1500]
        lines.append(f"- {instruction} [{status}]: {output}")
    return "\n".join(lines)


def _prepare_confirmed_args(
    tool_name: str,
    args: dict[str, Any],
    state: MissionState,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prepared = dict(args)
    summary_results = results if results is not None else state.get("step_results", [])
    if tool_name == "file_write":
        prepared["content"] = _summarize_results(state["user_goal"], summary_results)
    elif tool_name == "whatsapp_send_message":
        prepared["message"] = _summarize_results(state["user_goal"], summary_results)[:1800]
    return prepared


async def execute_plan(state: MissionState) -> MissionState:
    tools = _tool_map()
    results = list(state.get("step_results", []))
    errors = list(state.get("errors", []))
    retry_counts = dict(state.get("retry_counts") or {})
    verifications = list(state.get("step_verifications", []))

    for step in state.get("plan", []):
        if step.get("status") == "done":
            continue

        if step.get("requires_confirmation"):
            step["status"] = "waiting_confirmation"
            continue

        tool_name = step.get("tool")
        if not tool_name:
            step["status"] = "skipped"
            continue

        tool = tools.get(tool_name)
        if not tool:
            step["status"] = "failed"
            error = f"Tool '{tool_name}' is not available."
            errors.append(error)
            results.append({**step, "status": "failed", "output": error})
            continue

        args = _prepare_confirmed_args(tool_name, step.get("args") or {}, state, results)
        step_key = str(step.get("id") or tool_name)
        max_attempts = 1 + MAX_STEP_RETRIES
        output = None
        verification: dict[str, Any] = {"passed": False, "confidence": 0.0, "reason": "not_executed"}

        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            await _emit_mission_event(
                "tool.started",
                {
                    "session_id": state.get("session_id"),
                    "step_id": step.get("id"),
                    "tool": tool_name,
                    "attempt": attempt,
                    "args": args,
                },
            )
            try:
                output = await _invoke_tool(tool, args)
                verification = _verify_step_output(step, args, output)
                verifications.append({
                    "step_id": step.get("id"),
                    "tool": tool_name,
                    "attempt": attempt,
                    **verification,
                })
                await _emit_mission_event(
                    "verifier.result",
                    {
                        "session_id": state.get("session_id"),
                        "step_id": step.get("id"),
                        "tool": tool_name,
                        "attempt": attempt,
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                        **verification,
                    },
                    level="info" if verification.get("passed") else "warning",
                )

                if verification.get("passed"):
                    step["status"] = "done"
                    results.append({
                        **step,
                        "status": "done",
                        "output": output,
                        "verification": verification,
                        "attempts": attempt,
                    })
                    break

                retry_counts[step_key] = attempt
                if attempt < max_attempts and _is_retryable_step(step, verification):
                    await _emit_mission_event(
                        "retry.scheduled",
                        {
                            "session_id": state.get("session_id"),
                            "step_id": step.get("id"),
                            "tool": tool_name,
                            "attempt": attempt,
                            "reason": verification.get("reason"),
                        },
                        level="warning",
                    )
                    continue

                step["status"] = "failed"
                error = f"{tool_name} verification failed: {verification.get('reason')}"
                errors.append(error)
                results.append({
                    **step,
                    "status": "failed",
                    "output": output,
                    "verification": verification,
                    "attempts": attempt,
                })
                break
            except Exception as exc:
                retry_counts[step_key] = attempt
                verification = {
                    "passed": False,
                    "confidence": 0.0,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
                verifications.append({
                    "step_id": step.get("id"),
                    "tool": tool_name,
                    "attempt": attempt,
                    **verification,
                })
                if attempt < max_attempts and _is_retryable_step(step, verification):
                    await _emit_mission_event(
                        "retry.scheduled",
                        {
                            "session_id": state.get("session_id"),
                            "step_id": step.get("id"),
                            "tool": tool_name,
                            "attempt": attempt,
                            "reason": verification["reason"],
                        },
                        level="warning",
                    )
                    continue

                step["status"] = "failed"
                error = f"{tool_name} failed: {exc}"
                errors.append(error)
                results.append({
                    **step,
                    "status": "failed",
                    "output": error,
                    "verification": verification,
                    "attempts": attempt,
                })
                break

    return {
        **state,
        "step_results": results,
        "errors": errors,
        "retry_counts": retry_counts,
        "step_verifications": verifications,
    }


def verify_mission(state: MissionState) -> MissionState:
    errors = state.get("errors", [])
    pending = state.get("pending_confirmation", [])
    completed = [r for r in state.get("step_results", []) if r.get("status") == "done"]

    if errors:
        final = "I started the mission, but hit a problem: " + "; ".join(errors[:2])
        return {**state, "verified": False, "final_answer": final}

    if pending:
        labels = ", ".join(step.get("tool", "action") for step in pending)
        summary = _summarize_results(state["user_goal"], completed)
        final = (
            "Mission progress is ready, but I paused before risky action(s): "
            f"{labels}. Please confirm before I continue.\n\n{summary}"
        )
        return {**state, "verified": False, "final_answer": final}

    if completed:
        final = "Mission completed.\n\n" + _summarize_results(state["user_goal"], completed)
        return {**state, "verified": True, "final_answer": final}

    return {
        **state,
        "verified": False,
        "final_answer": "I need a more specific mission before I can plan useful steps.",
    }


def _is_affirmative(text: str) -> bool:
    return text.strip().lower() in {"yes", "y", "yeah", "yep", "ok", "okay", "confirm", "proceed", "send it", "do it"}


def _is_negative(text: str) -> bool:
    return text.strip().lower() in {"no", "n", "nope", "cancel", "stop", "don't", "do not"}


async def handle_mission_confirmation(session_id: str, user_message: str) -> str:
    state = get_active_mission(session_id)
    if not state:
        return ""

    if _is_negative(user_message):
        clear_mission(session_id)
        return "Mission cancelled, Sir."

    if not _is_affirmative(user_message):
        return "Please confirm whether I should continue the paused mission, Sir."

    for step in state.get("pending_confirmation", []):
        step["requires_confirmation"] = False
        step["status"] = "pending"

    state["pending_confirmation"] = []
    state = await execute_plan(state)
    state = verify_mission(state)
    clear_mission(session_id)
    return state.get("final_answer", "Mission completed, Sir.")


def build_mission_graph():
    workflow = StateGraph(MissionState)
    workflow.add_node("planner", plan_mission)
    workflow.add_node("safety_gate", safety_gate)
    workflow.add_node("executor", execute_plan)
    workflow.add_node("verifier", verify_mission)

    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "safety_gate")
    workflow.add_edge("safety_gate", "executor")
    workflow.add_edge("executor", "verifier")
    workflow.add_edge("verifier", END)
    return workflow.compile()


mission_graph_app = build_mission_graph()
