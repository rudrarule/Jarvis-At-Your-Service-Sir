"""LangGraph construction for the J.A.R.V.I.S v2 Planner + Browser system."""

from __future__ import annotations

import os
import sqlite3
import uuid

from langgraph.graph import END, START, StateGraph

from workflows.v2.browser_agent import execute_browser_step
from workflows.v2.failure_handler import run_failure_recovery
from workflows.v2.planner import plan_next_action
from workflows.v2.state import JarvisState, create_initial_state, get_current_step
from workflows.v2.synthesizer import (
    synthesize_final_response,
    synthesize_final_response_async,
)
from workflows.v2.system_executor import execute_system_step


def _route_after_planner(state: JarvisState) -> str:
    status = state.get("completion_status")
    if status in {"completed", "failed", "needs_user"}:
        return "synthesizer"

    step = get_current_step(state)
    if not step:
        return "synthesizer"
    if step.status == "failed":
        return "failure_recovery"
    if step.assigned_agent == "browser":
        return "browser_agent"
    return "system_executor"


def _route_after_browser(state: JarvisState) -> str:
    status = state.get("completion_status")
    if status in {"completed", "failed", "needs_user"}:
        return "synthesizer"
    if status == "recovering":
        return "failure_recovery"
    return "planner"


def _route_after_system(state: JarvisState) -> str:
    if state.get("completion_status") in {"completed", "failed", "needs_user"}:
        return "synthesizer"
    return "planner"


def build_jarvis_v2_graph():
    workflow = StateGraph(JarvisState)

    workflow.add_node("planner", plan_next_action)
    workflow.add_node("browser_agent", execute_browser_step)
    workflow.add_node("system_executor", execute_system_step)
    workflow.add_node("failure_recovery", run_failure_recovery)
    workflow.add_node("synthesizer", synthesize_final_response_async)

    workflow.add_edge(START, "planner")
    workflow.add_conditional_edges(
        "planner",
        _route_after_planner,
        {
            "browser_agent": "browser_agent",
            "system_executor": "system_executor",
            "failure_recovery": "failure_recovery",
            "synthesizer": "synthesizer",
        },
    )
    workflow.add_conditional_edges(
        "browser_agent",
        _route_after_browser,
        {
            "planner": "planner",
            "failure_recovery": "failure_recovery",
            "synthesizer": "synthesizer",
        },
    )
    workflow.add_conditional_edges(
        "system_executor",
        _route_after_system,
        {
            "planner": "planner",
            "synthesizer": "synthesizer",
        },
    )
    workflow.add_edge("failure_recovery", "planner")
    workflow.add_edge("synthesizer", END)

    if os.getenv("JARVIS_V2_GRAPH_CHECKPOINTS", "").lower() in {"1", "true", "yes", "on"}:
        from langgraph.checkpoint.sqlite import SqliteSaver

        db_path = os.getenv("JARVIS_V2_GRAPH_DB")
        if not db_path:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            db_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "db"))
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "jarvis_v2_graph.db")

        conn = sqlite3.connect(db_path, check_same_thread=False)
        return workflow.compile(checkpointer=SqliteSaver(conn))

    return workflow.compile()


jarvis_v2_graph_app = build_jarvis_v2_graph()


async def run_jarvis_v2_goal(user_goal: str, session_id: str = "default") -> JarvisState:
    state = create_initial_state(user_goal, session_id)
    return await jarvis_v2_graph_app.ainvoke(
        state,
        {
            "recursion_limit": int(os.getenv("JARVIS_V2_RECURSION_LIMIT", "80")),
            "configurable": {"thread_id": f"{session_id}:v2:{uuid.uuid4().hex[:8]}"},
        },
    )
