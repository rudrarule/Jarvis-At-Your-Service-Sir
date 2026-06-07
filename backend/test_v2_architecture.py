import pytest


def test_v2_state_defaults():
    from workflows.v2.state import create_initial_state

    state = create_initial_state("open amazon and search headphones", "test")

    assert state["user_goal"] == "open amazon and search headphones"
    assert state["session_id"] == "test"
    assert state["task_plan"] == []
    assert state["completion_status"] == "planning"
    assert state["token_usage"]["total"] == 0


def test_v2_failure_classification():
    from workflows.v2.failure_handler import classify_browser_error

    assert classify_browser_error("Timeout 30000ms exceeded") == "page_timeout"
    assert classify_browser_error("waiting for locator button failed") == "element_not_found"
    assert classify_browser_error("Element is detached from DOM") == "stale_state"
    assert classify_browser_error("click intercepted by overlay") == "modal_blocked"
    assert classify_browser_error("Please login with password", "Sign in required") == "authentication_required"


@pytest.mark.asyncio
async def test_v2_planner_fallback_without_llm(monkeypatch):
    from workflows.v2.planner import plan_next_action
    from workflows.v2.state import create_initial_state

    monkeypatch.setenv("JARVIS_V2_USE_LLM_PLANNER", "false")
    state = await plan_next_action(create_initial_state("open bigbasket and add milk"))

    assert state["completion_status"] == "executing"
    assert len(state["task_plan"]) >= 2
    assert state["task_plan"][0].assigned_agent == "browser"
    assert state["task_plan"][0].params["url"] == "https://www.bigbasket.com"


def test_v2_graph_compiles():
    from workflows.v2.graph import build_jarvis_v2_graph

    app = build_jarvis_v2_graph()
    assert app is not None


# ── Browser Improvements: Element Verification ──


def test_verify_element_available_found():
    from workflows.v2.browser_agent import _verify_element_available
    from workflows.v2.state import BrowserStateSnapshot

    snap = BrowserStateSnapshot(
        url="https://example.com",
        title="Example",
        interactive_elements=[
            {"id": "7", "name": "Search", "role": "textbox"},
            {"id": "12", "name": "Submit", "role": "button"},
        ],
    )
    assert _verify_element_available("7", snap) is True
    assert _verify_element_available("12", snap) is True


def test_verify_element_available_missing():
    from workflows.v2.browser_agent import _verify_element_available
    from workflows.v2.state import BrowserStateSnapshot

    snap = BrowserStateSnapshot(
        url="https://example.com",
        title="Example",
        interactive_elements=[{"id": "7", "name": "Search"}],
    )
    assert _verify_element_available("999", snap) is False


def test_verify_element_available_none_id():
    from workflows.v2.browser_agent import _verify_element_available
    from workflows.v2.state import BrowserStateSnapshot

    snap = BrowserStateSnapshot(url="https://example.com", title="Example")
    # None element_id means the action doesn't target an element (e.g. scroll).
    assert _verify_element_available(None, snap) is True


def test_verify_element_ref_fallback():
    """Elements may use 'ref' instead of 'id'."""
    from workflows.v2.browser_agent import _verify_element_available
    from workflows.v2.state import BrowserStateSnapshot

    snap = BrowserStateSnapshot(
        url="https://example.com",
        title="Example",
        interactive_elements=[{"ref": "42", "name": "Login", "role": "button"}],
    )
    assert _verify_element_available("42", snap) is True
    assert _verify_element_available("99", snap) is False


# ── Browser Improvements: Action Guard Scoring ──


def test_score_action_valid_click():
    from workflows.v2.browser_agent import _score_candidate_action
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(
        url="https://example.com",
        title="Example",
        interactive_elements=[{"id": "5", "name": "Add to cart", "role": "button"}],
    )
    action = BrowserAction(
        action_type="click",
        element_id="5",
        reasoning="The add to cart button is visible and matches the objective.",
    )
    score = _score_candidate_action(action, snap)
    assert score >= 0.7, f"Valid click with existing element should score high, got {score}"


def test_score_action_hallucinated_element():
    from workflows.v2.browser_agent import _score_candidate_action
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(
        url="https://example.com",
        title="Example",
        interactive_elements=[{"id": "5", "name": "Add to cart"}],
    )
    action = BrowserAction(
        action_type="click",
        element_id="999",
        reasoning="Click the checkout button.",
    )
    score = _score_candidate_action(action, snap)
    assert score < 0.3, f"Hallucinated element should score below guard threshold, got {score}"


def test_score_action_click_no_element_id():
    from workflows.v2.browser_agent import _score_candidate_action
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(url="https://example.com", title="Example")
    action = BrowserAction(action_type="click", reasoning="click")
    score = _score_candidate_action(action, snap)
    assert score < 0.3, f"Click with no element_id should score below guard threshold, got {score}"


def test_score_action_open_url():
    from workflows.v2.browser_agent import _score_candidate_action
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(url="about:blank", title="")
    action = BrowserAction(action_type="open_url", url="https://www.amazon.in")
    score = _score_candidate_action(action, snap)
    assert score >= 0.8, f"open_url with valid URL should score high, got {score}"


def test_score_action_open_url_no_url():
    from workflows.v2.browser_agent import _score_candidate_action
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(url="about:blank", title="")
    action = BrowserAction(action_type="open_url", url="")
    score = _score_candidate_action(action, snap)
    assert score < 0.3, f"open_url without URL should score very low, got {score}"


def test_score_action_meta_actions():
    from workflows.v2.browser_agent import _score_candidate_action
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(url="https://example.com", title="Example")
    for action_type in ("done", "fail", "wait", "observe"):
        action = BrowserAction(action_type=action_type)
        score = _score_candidate_action(action, snap)
        assert score == 0.7, f"Meta-action '{action_type}' should score exactly 0.7, got {score}"


def test_score_action_scroll():
    from workflows.v2.browser_agent import _score_candidate_action
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(url="https://example.com", title="Example")
    action = BrowserAction(action_type="scroll", direction="down")
    score = _score_candidate_action(action, snap)
    assert score == 0.75, f"Scroll should score 0.75, got {score}"


# ── Browser Improvements: Post-Action Assertion ──


def test_assert_outcome_url_changed():
    from workflows.v2.browser_agent import _assert_action_outcome
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    pre = BrowserStateSnapshot(url="about:blank", title="")
    post = BrowserStateSnapshot(url="https://www.amazon.in", title="Amazon")
    action = BrowserAction(action_type="open_url", url="https://www.amazon.in")
    passed, detail = _assert_action_outcome(action, pre, post)
    assert passed is True
    assert "amazon" in detail.lower()


def test_assert_outcome_click_no_change():
    from workflows.v2.browser_agent import _assert_action_outcome
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(
        url="https://example.com",
        title="Example",
        page_fingerprint="abc123",
        element_counts={"button": 3},
    )
    action = BrowserAction(
        action_type="click",
        element_id="5",
        expected_delta="cart opens",
    )
    passed, detail = _assert_action_outcome(action, snap, snap)
    assert passed is False, "Click with identical pre/post snapshots should fail assertion"


def test_assert_outcome_click_with_change():
    from workflows.v2.browser_agent import _assert_action_outcome
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    pre = BrowserStateSnapshot(
        url="https://shop.com/product",
        title="Product Page",
        page_fingerprint="aaa",
        element_counts={"button": 3},
    )
    post = BrowserStateSnapshot(
        url="https://shop.com/product",
        title="Product Page",
        page_fingerprint="bbb",
        element_counts={"button": 5},
    )
    action = BrowserAction(action_type="click", element_id="5")
    passed, _ = _assert_action_outcome(action, pre, post)
    assert passed is True


def test_assert_outcome_type_always_passes():
    """Typing may not produce a DOM delta but is still considered valid."""
    from workflows.v2.browser_agent import _assert_action_outcome
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(
        url="https://search.com",
        title="Search",
        page_fingerprint="same",
    )
    action = BrowserAction(action_type="type", element_id="7", text="headphones")
    passed, _ = _assert_action_outcome(action, snap, snap)
    assert passed is True, "Typing should pass even without DOM delta"


def test_assert_outcome_expected_delta_match():
    from workflows.v2.browser_agent import _assert_action_outcome
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    pre = BrowserStateSnapshot(url="https://shop.com", title="Shop", summary="")
    post = BrowserStateSnapshot(
        url="https://shop.com",
        title="Shop",
        summary="Your cart now has 2 items. Checkout available.",
        page_fingerprint="changed",
    )
    action = BrowserAction(
        action_type="click",
        element_id="5",
        expected_delta="cart items checkout",
    )
    passed, detail = _assert_action_outcome(action, pre, post)
    assert passed is True
    assert "delta matched" in detail.lower()


def test_assert_outcome_passive_actions_always_pass():
    from workflows.v2.browser_agent import _assert_action_outcome
    from workflows.v2.state import BrowserAction, BrowserStateSnapshot

    snap = BrowserStateSnapshot(url="https://example.com", title="Example")
    for action_type in ("wait", "observe", "scroll", "go_back"):
        action = BrowserAction(action_type=action_type)
        passed, _ = _assert_action_outcome(action, snap, snap)
        assert passed is True, f"Passive action '{action_type}' should always pass"


# ── Graph Routing ──


def test_route_after_planner_completed():
    from workflows.v2.graph import _route_after_planner
    from workflows.v2.state import create_initial_state

    state = create_initial_state("test")
    state["completion_status"] = "completed"
    assert _route_after_planner(state) == "synthesizer"


def test_route_after_planner_to_browser():
    from workflows.v2.graph import _route_after_planner
    from workflows.v2.state import TaskStep, create_initial_state

    state = create_initial_state("test")
    state["completion_status"] = "executing"
    state["task_plan"] = [TaskStep(id="s1", description="open site", success_criteria="url loads", assigned_agent="browser")]
    state["current_step_index"] = 0
    assert _route_after_planner(state) == "browser_agent"


def test_route_after_planner_to_system():
    from workflows.v2.graph import _route_after_planner
    from workflows.v2.state import TaskStep, create_initial_state

    state = create_initial_state("test")
    state["completion_status"] = "executing"
    state["task_plan"] = [TaskStep(id="s1", description="send msg", success_criteria="msg sent", assigned_agent="system")]
    state["current_step_index"] = 0
    assert _route_after_planner(state) == "system_executor"


def test_route_after_browser_recovering():
    from workflows.v2.graph import _route_after_browser
    from workflows.v2.state import create_initial_state

    state = create_initial_state("test")
    state["completion_status"] = "recovering"
    assert _route_after_browser(state) == "failure_recovery"


def test_route_after_browser_success():
    from workflows.v2.graph import _route_after_browser
    from workflows.v2.state import create_initial_state

    state = create_initial_state("test")
    state["completion_status"] = "executing"
    assert _route_after_browser(state) == "planner"


# ── Synthesizer ──


def test_synthesizer_completed():
    from workflows.v2.synthesizer import synthesize_final_response
    from workflows.v2.state import create_initial_state

    state = create_initial_state("test")
    state["completion_status"] = "completed"
    state["task_progress"] = ["step_1: Opened Amazon.", "step_2: Found headphones."]
    result = synthesize_final_response(state)
    assert result["final_answer"]
    assert "headphones" in result["final_answer"].lower()


def test_synthesizer_preserves_existing_answer():
    from workflows.v2.synthesizer import synthesize_final_response
    from workflows.v2.state import create_initial_state

    state = create_initial_state("test")
    state["final_answer"] = "Custom answer from recovery."
    result = synthesize_final_response(state)
    assert result["final_answer"] == "Custom answer from recovery."


def test_synthesizer_failed_with_errors():
    from workflows.v2.state import FailureRecord, create_initial_state
    from workflows.v2.synthesizer import synthesize_final_response

    state = create_initial_state("test")
    state["completion_status"] = "failed"
    state["failure_history"] = [
        FailureRecord(step_id="s1", category="page_timeout", error_message="Timeout 30000ms exceeded"),
    ]
    result = synthesize_final_response(state)
    assert "timeout" in result["final_answer"].lower()


def test_compact_failure_record():
    from workflows.v2.browser_agent import _compact_failure_record
    from workflows.v2.state import FailureRecord, BrowserStateSnapshot

    snap = BrowserStateSnapshot(
        url="https://example.com",
        title="Example Title",
        accessibility_tree="Long tree...",
        interactive_elements=[{"id": "1", "name": "element"}],
        screenshot_base64="huge_base64_data",
    )
    failure = FailureRecord(
        step_id="step_2",
        category="validation_failed",
        error_message="Budget exhausted",
        page_state_at_failure=snap,
        recovery_hint="Try again",
        retryable=True,
    )

    compacted = _compact_failure_record(failure)
    assert compacted["step_id"] == "step_2"
    assert compacted["category"] == "validation_failed"
    assert compacted["error_message"] == "Budget exhausted"
    assert compacted["recovery_hint"] == "Try again"
    assert compacted["retryable"] is True
    assert compacted["url_at_failure"] == "https://example.com"
    assert compacted["title_at_failure"] == "Example Title"
    assert "page_state_at_failure" not in compacted
    assert "screenshot_base64" not in compacted
