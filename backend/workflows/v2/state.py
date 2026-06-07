"""Shared state contracts for the J.A.R.V.I.S Planner + Browser graph.

The v2 graph intentionally keeps strategic planning state separate from
low-level browser execution history. Pydantic models are used at graph
boundaries so each node can validate the data it receives and returns.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


AgentName = Literal[
    "planner",
    "browser",
    "system",
    "research",
    "coding",
    "memory",
    "communication",
]
StepStatus = Literal["pending", "running", "completed", "failed", "blocked", "skipped"]
CompletionStatus = Literal["planning", "executing", "recovering", "completed", "failed", "needs_user"]
FailureCategory = Literal[
    "element_not_found",
    "click_failed",
    "typing_failed",
    "modal_blocked",
    "authentication_required",
    "validation_failed",
    "stale_state",
    "page_timeout",
    "navigation_failed",
    "tool_unavailable",
    "unknown_execution_failed",
]
BrowserActionType = Literal[
    "open_url",
    "observe",
    "click",
    "type",
    "scroll",
    "go_back",
    "wait",
    "done",
    "fail",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStep(BaseModel):
    """A planner-owned unit of work.

    Browser steps are outcome-oriented, not selector-oriented. The Browser
    Agent decides the actual page actions required to satisfy the step.
    """

    id: str = Field(description="Stable step identifier such as step_1.")
    description: str = Field(description="Outcome-oriented step description.")
    success_criteria: str = Field(description="Concrete observable criteria for step success.")
    assigned_agent: AgentName = Field(default="browser")
    objective_type: str = Field(default="browser_task")
    status: StepStatus = Field(default="pending")
    result: Optional[str] = Field(default=None)
    params: dict[str, Any] = Field(default_factory=dict)
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=2)
    requires_confirmation: bool = Field(default=False)


class BrowserStateSnapshot(BaseModel):
    url: str = ""
    title: str = ""
    observation_id: Optional[str] = None
    page_fingerprint: Optional[str] = None
    summary: str = ""
    accessibility_tree: str = ""
    interactive_elements: list[dict[str, Any]] = Field(default_factory=list)
    element_counts: dict[str, int] = Field(default_factory=dict)
    state_delta: Optional[str] = None
    screenshot_base64: Optional[str] = None
    captured_at: str = Field(default_factory=now_iso)


class BrowserAction(BaseModel):
    action_type: BrowserActionType
    reasoning: str = ""
    element_id: Optional[str] = None
    text: str = ""
    url: str = ""
    direction: Literal["up", "down"] = "down"
    press_enter: bool = True
    expected_delta: str = ""


class ActionHistoryEntry(BaseModel):
    step_id: str
    action: BrowserAction
    success: bool
    result_summary: str = ""
    error: Optional[str] = None
    before_observation_id: Optional[str] = None
    after_observation_id: Optional[str] = None
    duration_ms: int = 0
    timestamp: str = Field(default_factory=now_iso)


class FailureRecord(BaseModel):
    step_id: str
    category: FailureCategory
    error_message: str
    attempt_count: int = 1
    page_state_at_failure: Optional[BrowserStateSnapshot] = None
    recovery_hint: str = ""
    retryable: bool = True
    timestamp: str = Field(default_factory=now_iso)


class PlannerReasoningEntry(BaseModel):
    decision_type: Literal["initial_plan", "advance", "replan", "complete", "fail"]
    reasoning: str
    next_step_id: Optional[str] = None
    plan_version: int = 1
    timestamp: str = Field(default_factory=now_iso)


class BrowserExecutionResult(BaseModel):
    step_id: str
    success: bool
    summary: str
    actions_performed: list[BrowserAction] = Field(default_factory=list)
    final_observation: Optional[BrowserStateSnapshot] = None
    error_type: Optional[FailureCategory] = None
    error_message: Optional[str] = None
    needs_replan: bool = False
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=now_iso)


class JarvisState(TypedDict, total=False):
    # Inputs and core intent
    user_goal: str
    session_id: str
    current_time: str

    # Planner state
    task_plan: list[TaskStep]
    current_step_index: int
    planner_reasoning: list[PlannerReasoningEntry]
    plan_version: int

    # Browser state
    browser_active: bool
    current_browser_state: Optional[BrowserStateSnapshot]
    browser_observations: list[BrowserStateSnapshot]
    browser_execution_results: list[BrowserExecutionResult]

    # Histories
    action_history: list[ActionHistoryEntry]
    failure_history: list[FailureRecord]
    task_progress: list[str]

    # Control/status
    completion_status: CompletionStatus
    final_answer: str
    scratchpad: str
    recovery_count: int
    token_usage: dict[str, int]


def model_to_dict(model: BaseModel | dict[str, Any] | None) -> dict[str, Any]:
    if model is None:
        return {}
    if isinstance(model, dict):
        return model
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def create_initial_state(user_goal: str, session_id: str = "default") -> JarvisState:
    return {
        "user_goal": user_goal,
        "session_id": session_id,
        "current_time": now_iso(),
        "task_plan": [],
        "current_step_index": 0,
        "planner_reasoning": [],
        "plan_version": 0,
        "browser_active": False,
        "current_browser_state": None,
        "browser_observations": [],
        "browser_execution_results": [],
        "action_history": [],
        "failure_history": [],
        "task_progress": [],
        "completion_status": "planning",
        "final_answer": "",
        "scratchpad": "",
        "recovery_count": 0,
        "token_usage": {"input": 0, "output": 0, "total": 0},
    }


def ensure_state_defaults(state: JarvisState) -> JarvisState:
    """Return a state copy with all optional list/status fields initialized."""

    base = create_initial_state(state.get("user_goal", ""), state.get("session_id", "default"))
    base.update(state)
    for key in (
        "task_plan",
        "planner_reasoning",
        "browser_observations",
        "browser_execution_results",
        "action_history",
        "failure_history",
        "task_progress",
    ):
        base[key] = list(base.get(key) or [])
    base["token_usage"] = dict(base.get("token_usage") or {"input": 0, "output": 0, "total": 0})
    return base


def get_current_step(state: JarvisState) -> Optional[TaskStep]:
    plan = state.get("task_plan") or []
    index = state.get("current_step_index", 0)
    if index < 0 or index >= len(plan):
        return None
    step = plan[index]
    return step if isinstance(step, TaskStep) else TaskStep(**step)


def replace_current_step(state: JarvisState, step: TaskStep) -> list[TaskStep]:
    plan = [item if isinstance(item, TaskStep) else TaskStep(**item) for item in state.get("task_plan", [])]
    index = state.get("current_step_index", 0)
    if 0 <= index < len(plan):
        plan[index] = step
    return plan


def first_pending_step_index(plan: list[TaskStep], start_at: int = 0) -> int | None:
    for index in range(max(0, start_at), len(plan)):
        if plan[index].status == "pending":
            return index
    return None
