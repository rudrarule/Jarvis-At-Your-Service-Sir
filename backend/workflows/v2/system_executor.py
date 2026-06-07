"""Non-browser executor for v2 planner steps.

This is intentionally small. Browser automation is the core path, while system
steps are delegated to existing LangChain tools when the Planner assigns them.
"""

from __future__ import annotations

import inspect
from typing import Any

from workflows.tool_wrapper import ALL_TOOLS
from workflows.v2.state import BrowserExecutionResult, FailureRecord, JarvisState, ensure_state_defaults, get_current_step, replace_current_step


def _tool_map() -> dict[str, Any]:
    return {tool.name: tool for tool in ALL_TOOLS}


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
        result = tool.invoke(args)
    else:
        result = tool(**args)
    if inspect.isawaitable(result):
        return await result
    return result


async def execute_system_step(state: JarvisState) -> JarvisState:
    state = ensure_state_defaults(state)
    step = get_current_step(state)
    if not step:
        return {**state, "completion_status": "completed"}

    tool_name = str(step.params.get("tool_name") or "")
    if step.requires_confirmation:
        blocked = step.model_copy(update={"status": "blocked", "result": "Waiting for user confirmation."})
        return {
            **state,
            "task_plan": replace_current_step(state, blocked),
            "completion_status": "needs_user",
            "final_answer": f"I paused before running {tool_name or 'a system action'} because it requires confirmation.",
        }

    tool = _tool_map().get(tool_name)
    if not tool:
        failed = step.model_copy(update={"status": "failed", "result": f"Tool '{tool_name}' is unavailable."})
        failure = FailureRecord(
            step_id=step.id,
            category="tool_unavailable",
            error_message=f"Tool '{tool_name}' is unavailable.",
            retryable=False,
        )
        return {
            **state,
            "task_plan": replace_current_step(state, failed),
            "failure_history": list(state.get("failure_history") or []) + [failure],
            "completion_status": "executing",
        }

    args = dict(step.params.get("args") or {})
    try:
        output = await _invoke_tool(tool, args)
    except Exception as exc:
        failed = step.model_copy(update={"status": "failed", "result": str(exc)})
        failure = FailureRecord(
            step_id=step.id,
            category="unknown_execution_failed",
            error_message=str(exc),
            retryable=False,
        )
        return {
            **state,
            "task_plan": replace_current_step(state, failed),
            "failure_history": list(state.get("failure_history") or []) + [failure],
            "completion_status": "executing",
        }

    completed = step.model_copy(update={"status": "completed", "result": str(output)[:1500]})
    result = BrowserExecutionResult(
        step_id=step.id,
        success=True,
        summary=str(output)[:1500],
        confidence=0.85,
        evidence=[f"Executed {tool_name}."],
    )
    return {
        **state,
        "task_plan": replace_current_step(state, completed),
        "browser_execution_results": list(state.get("browser_execution_results") or []) + [result],
        "task_progress": list(state.get("task_progress") or []) + [f"{completed.id}: system step completed."],
        "completion_status": "executing",
    }
