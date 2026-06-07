"""Failure classification and local recovery for the v2 browser graph."""

from __future__ import annotations

import re
from typing import Any

from tools.browser_tool import BrowserStateManager, interact_by_registry_id, observe_with_registry
from workflows.v2.state import FailureCategory, JarvisState, TaskStep, ensure_state_defaults, get_current_step, replace_current_step


AUTH_RE = re.compile(r"\b(sign in|login|log in|password|credential|otp|two-factor|2fa|verify your identity)\b", re.IGNORECASE)
BOT_CHECK_RE = re.compile(r"\b(captcha|robot|are you a person|human verification|bot|automated|verify you are human)\b", re.IGNORECASE)
MODAL_RE = re.compile(r"\b(modal|dialog|overlay|popup|pop-up|blocked|intercepted|not clickable|receives pointer events)\b", re.IGNORECASE)
DISMISS_RE = re.compile(r"\b(close|dismiss|skip|not now|continue|continue on web|accept|agree|ok|okay|x)\b", re.IGNORECASE)


def classify_browser_error(
    error_message: str,
    page_text: str = "",
    action_type: str = "",
) -> FailureCategory:
    """Map raw browser/tool failures to stable production categories."""

    error = (error_message or "").lower()
    page = (page_text or "").lower()

    # Check if this is truly an authentication required failure.
    # It must contain a clear login/credential reference, AND either:
    # 1. Be on a page with password/passcode/passkey/otp text.
    # 2. Or the error itself explicitly mentions passwords/passcodes/2fa/login.
    is_auth_error = False
    if AUTH_RE.search(error_message or ""):
        if any(indicator in error for indicator in ("password", "passcode", "passkey", "otp", "2fa", "two-factor")):
            is_auth_error = True
        elif any(indicator in page for indicator in ("password", "passcode", "passkey", "otp", "2fa", "two-factor")):
            is_auth_error = True

    if is_auth_error:
        return "authentication_required"
    if BOT_CHECK_RE.search(error_message or "") or BOT_CHECK_RE.search(page_text or ""):
        return "authentication_required"
    if "timeout" in error or "timed out" in error:
        return "page_timeout"
    if "not found" in error or "no element" in error or "waiting for locator" in error or "missing element_id" in error:
        return "element_not_found"
    if "detached" in error or "stale" in error or "page may have changed" in error:
        return "stale_state"
    if MODAL_RE.search(error_message or ""):
        return "modal_blocked"
    if action_type == "click" or "click" in error:
        return "click_failed"
    if action_type == "type" or "fill" in error or "press" in error:
        return "typing_failed"
    if "navigation" in error or "net::" in error:
        return "navigation_failed"
    if "verify" in error or "criteria" in error or "budget exhausted" in error:
        return "validation_failed"
    return "unknown_execution_failed"


async def _try_dismiss_modal() -> bool:
    observation = await observe_with_registry(include_screenshot=False, include_ax_tree_text=True)
    if not observation.get("success"):
        return False
    data = observation.get("data") or {}
    for element in data.get("interactive_elements") or []:
        haystack = " ".join(
            str(element.get(key) or "")
            for key in ("name", "text", "placeholder", "context", "role", "tag")
        )
        if DISMISS_RE.search(haystack):
            element_id = element.get("id") or element.get("ref")
            if element_id is None:
                continue
            result = await interact_by_registry_id(str(element_id), "click")
            return bool(result.get("success"))
    return False


async def _refresh_page() -> bool:
    try:
        page = await BrowserStateManager.get_page()
        await page.reload(wait_until="domcontentloaded", timeout=15000)
        return True
    except Exception:
        return False


def _retry_current_step(state: JarvisState, step: TaskStep, hint: str) -> JarvisState:
    retry_step = step.model_copy(update={"status": "pending", "result": hint})
    return {
        **state,
        "task_plan": replace_current_step(state, retry_step),
        "completion_status": "executing",
        "recovery_count": state.get("recovery_count", 0) + 1,
        "scratchpad": (state.get("scratchpad") or "") + f"\n[Recovery] {hint}",
    }


async def run_failure_recovery(state: JarvisState) -> JarvisState:
    """Perform cheap local recovery before the Planner spends another call."""

    state = ensure_state_defaults(state)
    step = get_current_step(state)
    failures = list(state.get("failure_history") or [])

    print(f"\n[TELEMETRY][FAILURE_RECOVERY] ========================================================")
    print(f"[TELEMETRY][FAILURE_RECOVERY] Entering Failure Recovery Node.")
    if step:
        print(f"[TELEMETRY][FAILURE_RECOVERY] Current Step ID: '{step.id}' | Attempt Count: {step.attempt_count} | Max Attempts: {step.max_attempts}")
    print(f"[TELEMETRY][FAILURE_RECOVERY] Failures in history: {len(failures)}")
    print(f"[TELEMETRY][FAILURE_RECOVERY] ========================================================")

    if not step or not failures:
        print(f"[TELEMETRY][FAILURE_RECOVERY] No active step or failure history. Routing back to executing.")
        return {**state, "completion_status": "executing"}

    last_failure = failures[-1]
    category = last_failure.category
    print(f"[TELEMETRY][FAILURE_RECOVERY] Last execution failure category: '{category}'")
    print(f"[TELEMETRY][FAILURE_RECOVERY] Failure message: '{last_failure.error_message}'")

    if category == "authentication_required":
        print(f"[TELEMETRY][FAILURE_RECOVERY] Authentication Required detected. Transitioning to needs_user.")
        blocked_step = step.model_copy(update={"status": "blocked", "result": last_failure.error_message})
        return {
            **state,
            "task_plan": replace_current_step(state, blocked_step),
            "completion_status": "needs_user",
            "final_answer": "The browser reached a login or identity verification step. I need user input before continuing.",
        }

    if step.attempt_count >= step.max_attempts:
        print(f"[TELEMETRY][FAILURE_RECOVERY] Step attempt count ({step.attempt_count}) has reached max_attempts ({step.max_attempts}). Escalating to planner.")
        failed_step = step.model_copy(update={"status": "failed"})
        return {
            **state,
            "task_plan": replace_current_step(state, failed_step),
            "completion_status": "executing",
            "scratchpad": (state.get("scratchpad") or "") + "\n[Recovery] Retry budget exhausted; planner should re-plan.",
        }

    if category in {"modal_blocked", "click_failed"}:
        print(f"[TELEMETRY][FAILURE_RECOVERY] Attempting local modal/popup dismissal...")
        dismissed = await _try_dismiss_modal()
        print(f"[TELEMETRY][FAILURE_RECOVERY] Modal dismissal result: {dismissed}")
        if dismissed:
            return _retry_current_step(state, step, "Dismissed a likely popup or overlay and will retry the step.")

    if category in {"stale_state", "element_not_found", "validation_failed"}:
        print(f"[TELEMETRY][FAILURE_RECOVERY] Refreshing element registry...")
        await observe_with_registry(include_screenshot=False, include_ax_tree_text=True)
        return _retry_current_step(state, step, "Refreshed the element registry and will retry with a fresh observation.")

    if category in {"page_timeout", "navigation_failed"}:
        print(f"[TELEMETRY][FAILURE_RECOVERY] Refreshing page...")
        refreshed = await _refresh_page()
        print(f"[TELEMETRY][FAILURE_RECOVERY] Page reload result: {refreshed}")
        if refreshed:
            return _retry_current_step(state, step, "Reloaded the current page after a timeout/navigation failure.")

    print(f"[TELEMETRY][FAILURE_RECOVERY] No local recovery actions succeeded or are available for category '{category}'. Escalating step failure to planner.")
    failed_step = step.model_copy(update={"status": "failed"})
    return {
        **state,
        "task_plan": replace_current_step(state, failed_step),
        "completion_status": "executing",
        "scratchpad": (state.get("scratchpad") or "") + f"\n[Recovery] No local recovery available for {category}.",
    }
