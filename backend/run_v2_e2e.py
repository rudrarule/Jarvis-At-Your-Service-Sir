#!/usr/bin/env python
"""End-to-End Test and Debug Runner for J.A.R.V.I.S v2.

Runs the dual-agent (Planner + Browser) architecture and displays full state tracing
with detailed node-by-node execution logs.
"""
import asyncio
import os
import sys
import argparse
import uuid
import json
from datetime import datetime
from pathlib import Path

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from workflows.v2.graph import build_jarvis_v2_graph
from workflows.v2.state import create_initial_state, get_current_step
from tools.browser_tool import BrowserStateManager
from workflows.v2.state import model_to_dict

# ANSI Color codes for rich logging
CLR_HEADER = "\033[95m"
CLR_BLUE = "\033[94m"
CLR_CYAN = "\033[96m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_RED = "\033[91m"
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"

def print_header(title: str, color: str = CLR_HEADER):
    width = 70
    border = "=" * width
    print(f"\n{color}{border}")
    print(f"{title.center(width)}")
    print(f"{border}{CLR_RESET}\n")

def print_sub_header(title: str, color: str = CLR_CYAN):
    print(f"\n{color}--- {title} ---{CLR_RESET}")

async def run_e2e(goal: str, visible: bool, screenshots: bool, session_id: str):
    # Set environment variables for browser settings
    os.environ["BROWSER_HEADLESS"] = "false" if visible else "true"
    os.environ["JARVIS_V2_BROWSER_SCREENSHOTS"] = "true" if screenshots else "false"
    os.environ["JARVIS_V2_GRAPH_CHECKPOINTS"] = "false"  # Run memory-only for testing
    os.environ.setdefault("JARVIS_E2E_CAPTURE_EACH_ACTION", "true")
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_dir = Path(__file__).resolve().parent / "data" / "e2e_debug" / f"{run_stamp}_{session_id}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    os.environ["JARVIS_E2E_DEBUG_DIR"] = str(debug_dir)
    event_log_path = debug_dir / "events.jsonl"

    def write_debug_event(kind: str, payload: dict):
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "payload": payload,
        }
        with event_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    print_header("J.A.R.V.I.S v2 E2E EXECUTION RUNNER", CLR_BLUE + CLR_BOLD)
    print(f"{CLR_BOLD}User Goal:{CLR_RESET} {goal}")
    print(f"{CLR_BOLD}Headless:{CLR_RESET} {not visible}")
    print(f"{CLR_BOLD}Screenshots:{CLR_RESET} {screenshots}")
    print(f"{CLR_BOLD}Session ID:{CLR_RESET} {session_id}")
    print(f"{CLR_BOLD}Debug Dir:{CLR_RESET} {debug_dir}")
    print(f"AWS Bedrock Model: {os.getenv('JARVIS_V2_BROWSER_MODEL_ID', 'us.amazon.nova-pro-v1:0')}")
    print("-" * 70)
    write_debug_event("run_started", {
        "goal": goal,
        "headless": not visible,
        "screenshots": screenshots,
        "session_id": session_id,
        "debug_dir": str(debug_dir),
    })

    # Initialize graph
    app = build_jarvis_v2_graph()
    
    # Create initial state
    state = create_initial_state(goal, session_id)
    config = {
        "recursion_limit": 100,
        "configurable": {"thread_id": f"{session_id}:e2e:{uuid.uuid4().hex[:8]}"},
    }

    # Tracking variable to print state changes cleanly
    last_step_index = -1
    last_plan_len = 0

    try:
        # Stream events step-by-step
        async for event in app.astream(state, config):
            for node_name, node_update in event.items():
                print_header(f"NODE EVENT: {node_name.upper()}", CLR_HEADER)
                write_debug_event("node_event", {
                    "node": node_name,
                    "completion_status": node_update.get("completion_status"),
                    "current_step_index": node_update.get("current_step_index"),
                    "plan": [model_to_dict(step) for step in node_update.get("task_plan", [])],
                    "latest_browser_state": model_to_dict(node_update.get("current_browser_state")),
                    "latest_action": model_to_dict((node_update.get("action_history") or [None])[-1]),
                    "latest_failure": model_to_dict((node_update.get("failure_history") or [None])[-1]),
                    "scratchpad_tail": str(node_update.get("scratchpad") or "")[-2000:],
                    "final_answer": node_update.get("final_answer", ""),
                })
                
                # Check for Planner Node
                if node_name == "planner":
                    completion_status = node_update.get("completion_status", "planning")
                    print(f"{CLR_BOLD}Completion Status:{CLR_RESET} {completion_status}")
                    
                    # Print reasoning
                    reasonings = node_update.get("planner_reasoning", [])
                    if reasonings:
                        last_reasoning = reasonings[-1]
                        print(f"{CLR_BOLD}Planner Reasoning:{CLR_RESET} {CLR_CYAN}{last_reasoning.reasoning}{CLR_RESET}")
                    
                    # Print plan if updated or modified
                    plan = node_update.get("task_plan", [])
                    if len(plan) != last_plan_len or node_update.get("plan_version", 0) > 1:
                        last_plan_len = len(plan)
                        print_sub_header("CURRENT PLAN LAYOUT", CLR_BLUE)
                        for idx, step in enumerate(plan):
                            status_clr = CLR_YELLOW if step.status == "pending" else (CLR_GREEN if step.status == "completed" else CLR_RED)
                            print(f" {idx + 1}. [{step.assigned_agent.upper()}] {step.id}: {step.description}")
                            print(f"    {CLR_BOLD}Criteria:{CLR_RESET} {step.success_criteria}")
                            print(f"    {CLR_BOLD}Status:{CLR_RESET} {status_clr}{step.status}{CLR_RESET}")
                            if step.result:
                                print(f"    {CLR_BOLD}Result:{CLR_RESET} {step.result[:200]}...")
                    
                    curr_idx = node_update.get("current_step_index", 0)
                    if curr_idx < len(plan):
                        curr_step = plan[curr_idx]
                        print(f"\n{CLR_BOLD}Next Active Step:{CLR_RESET} {curr_step.id} ({curr_step.assigned_agent}) -> {curr_step.description}")

                # Check for Browser Executor Node
                elif node_name == "browser_agent":
                    plan = node_update.get("task_plan", [])
                    curr_idx = node_update.get("current_step_index", 0)
                    
                    # Print active step
                    if curr_idx < len(plan):
                        print(f"{CLR_BOLD}Active Browser Step:{CLR_RESET} {plan[curr_idx].description}")
                    
                    # Print page status
                    snap = node_update.get("current_browser_state")
                    if snap:
                        print(f"{CLR_BOLD}Current Page:{CLR_RESET} {CLR_GREEN}{snap.title}{CLR_RESET} ({snap.url})")
                    
                    # Print history of actions executed in this node invocation
                    history = node_update.get("action_history", [])
                    if history:
                        last_actions = [h for h in history if plan and h.step_id == plan[curr_idx].id]
                        if last_actions:
                            print_sub_header("EXECUTED BROWSER ACTIONS", CLR_CYAN)
                            for entry in last_actions:
                                act = entry.action
                                print(f" {CLR_BOLD}► Action:{CLR_RESET} {CLR_CYAN}{act.action_type.upper()}{CLR_RESET} (element: {act.element_id or 'none'})")
                                if act.reasoning:
                                    print(f"   {CLR_BOLD}Reasoning:{CLR_RESET} {act.reasoning}")
                                if act.url:
                                    print(f"   {CLR_BOLD}URL:{CLR_RESET} {act.url}")
                                if act.text:
                                    print(f"   {CLR_BOLD}Text:{CLR_RESET} {act.text}")
                                if act.expected_delta:
                                    print(f"   {CLR_BOLD}Expected Delta:{CLR_RESET} {act.expected_delta}")
                                success_clr = CLR_GREEN if entry.success else CLR_RED
                                print(f"   {CLR_BOLD}Outcome:{CLR_RESET} {success_clr}{'SUCCESS' if entry.success else 'FAILED'}{CLR_RESET} - {entry.result_summary}")
                    
                    # Print failures if any
                    failures = node_update.get("failure_history", [])
                    if failures:
                        step_failures = [f for f in failures if plan and f.step_id == plan[curr_idx].id]
                        if step_failures:
                            print_sub_header("BROWSER EXECUTION ERRORS", CLR_RED)
                            for f in step_failures:
                                print(f" {CLR_BOLD}⚠ [{f.category}]{CLR_RESET} {CLR_RED}{f.error_message}{CLR_RESET}")
                                if f.recovery_hint:
                                    print(f"   {CLR_BOLD}Hint:{CLR_RESET} {f.recovery_hint}")

                # Check for System Executor Node
                elif node_name == "system_executor":
                    progress = node_update.get("task_progress", [])
                    if progress:
                        print(f"{CLR_BOLD}System Progress:{CLR_RESET} {CLR_GREEN}{progress[-1]}{CLR_RESET}")

                # Check for Failure Recovery Node
                elif node_name == "failure_recovery":
                    print(f"{CLR_BOLD}Status:{CLR_RESET} {CLR_YELLOW}{node_update.get('completion_status')}{CLR_RESET}")
                    scratch = node_update.get("scratchpad", "")
                    if scratch:
                        last_line = scratch.strip().split("\n")[-1]
                        print(f"{CLR_BOLD}Recovery Log:{CLR_RESET} {CLR_YELLOW}{last_line}{CLR_RESET}")

                # Check for Synthesizer Node
                elif node_name == "synthesizer":
                    print_header("FINAL ANSWER SYNTHESIS", CLR_GREEN + CLR_BOLD)
                    ans = node_update.get("final_answer", "")
                    print(f"{CLR_BOLD}Synthesized Answer:{CLR_RESET}\n{ans}")
                    print("-" * 70)

                # Keep the internal state synced for looping
                state.update(node_update)

    except Exception as e:
        print(f"\n{CLR_RED}E2E Execution Error: {e}{CLR_RESET}")
        write_debug_event("runner_exception", {"error": str(e)})
        import traceback
        traceback.print_exc()
    finally:
        final_summary = {
            "completion_status": state.get("completion_status"),
            "final_answer": state.get("final_answer", ""),
            "plan": [model_to_dict(step) for step in state.get("task_plan", [])],
            "failures": [model_to_dict(item) for item in state.get("failure_history", [])],
            "actions": [model_to_dict(item) for item in state.get("action_history", [])],
            "debug_dir": str(debug_dir),
        }
        (debug_dir / "final_state.json").write_text(
            json.dumps(final_summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n{CLR_BOLD}Debug artifacts:{CLR_RESET} {debug_dir}")
        # Clean up browser
        print(f"\n{CLR_BLUE}Shutting down browser context...{CLR_RESET}")
        await BrowserStateManager.close_all()
        print(f"{CLR_GREEN}Shutdown complete.{CLR_RESET}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S v2 E2E Debugger")
    parser.add_argument("goal", type=str, nargs="?", default="open wikipedia and search for deepmind",
                        help="The goal prompt to run E2E.")
    parser.add_argument("--visible", action="store_true", default=False,
                        help="Run the browser in visible mode (default: headless).")
    parser.add_argument("--screenshots", action="store_true", default=False,
                        help="Enable screenshot saving in browser observations.")
    parser.add_argument("--session", type=str, default="e2e-debug-session",
                        help="Session ID to use (default: e2e-debug-session).")
    
    # Reconfigure stdout/stderr to handle UTF-8 symbols (like ₹)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
        
    args = parser.parse_args()
    
    asyncio.run(run_e2e(args.goal, args.visible, args.screenshots, args.session))
