"""Tactical Browser Agent node for J.A.R.V.I.S v2."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from tools.browser_tool import (
    BrowserStateManager,
    go_back,
    interact_by_registry_id,
    observe_with_registry,
    open_url,
    scroll_page,
)
from workflows.v2.failure_handler import classify_browser_error
from workflows.v2.state import (
    ActionHistoryEntry,
    BrowserAction,
    BrowserExecutionResult,
    BrowserStateSnapshot,
    FailureRecord,
    JarvisState,
    TaskStep,
    ensure_state_defaults,
    get_current_step,
    model_to_dict,
    replace_current_step,
)


BROWSER_AGENT_SYSTEM_PROMPT = """You are the Tactical Browser Agent for J.A.R.V.I.S.

Your job is to complete exactly one browser objective from the Planner.
You receive a current page observation containing URL, title, accessibility
tree text, visible summary, and a numbered element registry. You choose a
single grounded action at a time.

Hard rules:
- Use only element IDs present in the latest observation.
- Never invent CSS selectors.
- After every click/type/scroll/open action, allow the graph to observe again.
- Prefer semantic evidence from the accessibility tree and element names.
- Handle popups before the main objective when they block progress.
- Stop immediately when success criteria are satisfied.
- Do not perform irreversible actions such as payment, purchase, or sending
  messages unless the step explicitly says confirmation has been granted.

Travel & Booking Best Practices:
- Differentiating "From" and "To" Fields: Travel websites often use identical placeholder or role names (e.g. "Country, city or airport") for both origin (From) and destination (To) fields.
  1. Inspect the "context" field in the element registry for origin/destination hints (e.g. context containing "From" or "origin" vs "To" or "destination").
  2. Double check that the element ID you choose matches the correct input field.
- Autocomplete Fields: When typing into an origin, destination, or lookup input field that triggers an autocomplete dropdown list:
  1. Type the location text into the input field. You MUST set "press_enter": false in your type action so the dropdown list stays open.
  2. Wait for the page to update, then in the next turn, select and click the correct autocomplete dropdown list item (role "option" or tag "li") rather than clicking individual inner spans or nested labels, to ensure the select action is registered correctly. Do not press enter or assume typing the name is sufficient.
  3. For Delhi, prefer a dropdown option containing "Indira Gandhi", "DEL", or "Delhi". For Goa, prefer a dropdown option containing "Goa", "GOI", "Dabolim", or "Manohar".
- Selecting Dates: When choosing dates in a calendar widget or date-picker:
  1. Check if the calendar widget is already open (e.g., month names like "June" or "July", grid of days, or specific dates like "Thursday, 18 June 2026" are visible in the accessibility tree or interactive elements list).
  2. If the calendar is ALREADY open/visible, DO NOT click the date selector/button (e.g. "Please select your departure date") again to open it. Clicking it will toggle the calendar closed and cause an infinite loop!
  3. Locate the specific calendar day number or date button (role "button" or "gridcell" matching the target date, e.g. "Thursday, 18 June 2026") in the interactive elements registry and click it directly. Do not guess or hallucinate date element IDs.
- Unlabeled Fields: If an input element lacks an explicit placeholder or name in the registry, look at preceding text, labels, or parent containers (e.g., "From", "To") in the accessibility tree or context field to determine its purpose.

Return ONLY a valid JSON object. Do not include any markdown formatting, code blocks, or text outside the JSON. Double check that your JSON structure is valid and contains no duplicate keys or trailing/missing brackets.

JSON structure:
{
  "reasoning": "why this action is best",
  "candidate_actions": [
    {"action_type": "click", "element_id": "12", "expected_delta": "cart opens"}
  ],
  "selected_action": {
    "action_type": "open_url | observe | click | type | scroll | go_back | wait | done | fail",
    "element_id": "optional registry id",
    "text": "text for type",
    "url": "url for open_url",
    "direction": "up | down",
    "press_enter": true,
    "expected_delta": "what should change"
  },
  "verification_strategy": "how to verify the objective after this action"
}
"""


DISMISS_TEXT_RE = re.compile(
    r"\b(accept|accept all|agree|allow|ok|okay|close|dismiss|skip|not now|continue|continue on web|x)\b",
    re.IGNORECASE,
)

MONTH_NAMES = {
    "jan": "january",
    "january": "january",
    "feb": "february",
    "february": "february",
    "mar": "march",
    "march": "march",
    "apr": "april",
    "april": "april",
    "may": "may",
    "jun": "june",
    "june": "june",
    "jul": "july",
    "july": "july",
    "aug": "august",
    "august": "august",
    "sep": "september",
    "sept": "september",
    "september": "september",
    "oct": "october",
    "october": "october",
    "nov": "november",
    "november": "november",
    "dec": "december",
    "december": "december",
}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _snapshot_from_observation(data: dict[str, Any] | None) -> BrowserStateSnapshot:
    data = data or {}
    return BrowserStateSnapshot(
        url=str(data.get("url") or ""),
        title=str(data.get("title") or ""),
        observation_id=data.get("observation_id"),
        page_fingerprint=data.get("page_fingerprint"),
        summary=str(data.get("summary") or ""),
        accessibility_tree=str(data.get("accessibility_tree") or ""),
        interactive_elements=list(data.get("interactive_elements") or []),
        element_counts=dict(data.get("element_counts") or {}),
        state_delta=data.get("state_delta"),
        screenshot_base64=data.get("screenshot_base64"),
    )


def _compact_observation(snapshot: BrowserStateSnapshot) -> dict[str, Any]:
    data = model_to_dict(snapshot)
    data.pop("screenshot_base64", None)
    data["interactive_elements"] = data.get("interactive_elements", [])[:150]
    data["accessibility_tree"] = str(data.get("accessibility_tree") or "")[:6000]
    data["summary"] = str(data.get("summary") or "")[:1200]
    return data


def _words(text: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]+", text.lower()) if len(part) > 2}


def _verify_success_criteria(step: TaskStep, snapshot: BrowserStateSnapshot, turn: int = 0) -> tuple[bool, list[str], float]:
    criteria = step.success_criteria.lower()
    page_text = " ".join(
        [
            snapshot.url,
            snapshot.title,
            snapshot.summary,
            snapshot.accessibility_tree,
            json.dumps(snapshot.interactive_elements[:40], ensure_ascii=True, default=str),
        ]
    ).lower()

    evidence: list[str] = []
    url_hint = str(step.params.get("url") or "")
    if step.objective_type == "navigate" and url_hint:
        target_host = re.sub(r"^https?://", "", url_hint).split("/")[0].replace("www.", "")
        if target_host and target_host in snapshot.url.replace("www.", ""):
            return True, [f"Browser URL contains target host {target_host}."], 0.92
        if turn > 0 and snapshot.url and snapshot.url != "about:blank":
            return True, [f"Browser navigated to {snapshot.url}."], 0.75

    url_match = re.search(r"url\s+contains\s+['\"]?([^'\".]+)", criteria)
    if url_match and url_match.group(1).strip().lower() in snapshot.url.lower():
        return True, [f"URL matches criterion: {url_match.group(1).strip()}"], 0.9

    if any(marker in criteria for marker in ("visible", "contains", "shows", "loaded", "confirmation")):
        goal_words = _words(step.description) | _words(step.success_criteria)
        stop_words = {
            "browser",
            "page",
            "visible",
            "contains",
            "loaded",
            "success",
            "criteria",
            "user",
            "goal",
            "requested",
            "information",
            "complete",
            "needed",
            "answer",
        }
        signal_words = [word for word in goal_words if word not in stop_words]
        hits = [word for word in signal_words if word in page_text]
        if signal_words and len(hits) >= max(2, min(4, len(signal_words) // 2)):
            evidence.append(f"Matched page terms: {', '.join(hits[:8])}.")
            return True, evidence, 0.72

    return False, evidence, 0.0


def _verify_element_available(element_id: str | None, snapshot: BrowserStateSnapshot) -> bool:
    """Pre-action check: confirm the target element exists in the current registry."""
    if not element_id:
        return True
    for elem in snapshot.interactive_elements:
        eid = elem.get("id") or elem.get("ref")
        if str(eid) == str(element_id):
            return True
    return False


def _score_candidate_action(action: BrowserAction, snapshot: BrowserStateSnapshot) -> float:
    """Deterministic confidence guard — scores an action before execution.

    Returns a value in [0.0, 1.0].  Actions below 0.3 are likely hallucinated
    or structurally invalid and should be replaced by a heuristic fallback.
    """
    score = 0.5

    # Meta-actions are always structurally valid.
    if action.action_type in ("done", "fail", "wait", "observe"):
        return 0.7

    if action.action_type == "open_url":
        return 0.9 if action.url else 0.2

    if action.action_type == "scroll":
        return 0.75

    # Element-dependent actions.
    if action.element_id:
        if _verify_element_available(action.element_id, snapshot):
            score += 0.3
        else:
            score -= 0.4  # Hallucinated or stale element ID.

    if action.action_type in ("click", "type") and not action.element_id:
        score -= 0.3

    if action.action_type == "type" and not action.text:
        score -= 0.2

    if action.reasoning and len(action.reasoning) > 10:
        score += 0.1

    return round(max(0.0, min(1.0, score)), 2)


def _assert_action_outcome(
    action: BrowserAction,
    pre: BrowserStateSnapshot,
    post: BrowserStateSnapshot,
) -> tuple[bool, str]:
    """Post-action assertion: verify the action produced an observable effect.

    Compares pre- and post-observation snapshots for URL changes, DOM fingerprint
    shifts, title changes, and element count deltas.  If the action carried an
    ``expected_delta``, its keywords are matched against the post-observation.
    """

    # Passive actions always pass.
    if action.action_type in ("wait", "observe", "scroll", "go_back"):
        return True, f"{action.action_type} completed"

    url_changed = pre.url != post.url
    fingerprint_changed = (pre.page_fingerprint or "") != (post.page_fingerprint or "")
    title_changed = pre.title != post.title
    pre_elem_count = sum(pre.element_counts.values()) if pre.element_counts else 0
    post_elem_count = sum(post.element_counts.values()) if post.element_counts else 0
    elements_shifted = abs(post_elem_count - pre_elem_count) > 2
    any_change = url_changed or fingerprint_changed or title_changed or elements_shifted

    # Check expected_delta keywords against post-observation text.
    if action.expected_delta:
        delta_words = _words(action.expected_delta)
        if delta_words:
            haystack = f"{post.url} {post.title} {post.summary} {post.accessibility_tree[:3000]}".lower()
            hits = [w for w in delta_words if w in haystack]
            if len(hits) >= max(1, len(delta_words) // 3):
                return True, f"Expected delta matched: {', '.join(hits[:6])}"

    if action.action_type == "open_url" and url_changed:
        return True, f"Navigated to {post.url}"

    if action.action_type == "type":
        if any_change:
            return True, "Page state changed after typing"
        # Typing into a field may not change the DOM fingerprint but is
        # still valid — give the benefit of the doubt on the first try.
        return True, "Text entered (no DOM delta detected, may be in-field)"

    if action.action_type == "click":
        if any_change:
            return True, "Page state changed after click"
        return False, "Click produced no observable state change"

    return any_change, "State change detected" if any_change else "No observable state change"


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


def _parse_action(data: dict[str, Any] | None) -> BrowserAction | None:
    if not data:
        return None
    selected = data.get("selected_action") if isinstance(data.get("selected_action"), dict) else data
    if isinstance(selected, dict):
        if not selected.get("reasoning") and data.get("reasoning"):
            selected["reasoning"] = str(data["reasoning"])
        if selected.get("action_type") == "type" and "press_enter" not in selected:
            # Autocomplete-backed travel fields need a follow-up option click.
            # Pressing Enter immediately can hide the dropdown or pick the wrong item.
            selected["press_enter"] = False
        if selected.get("direction") not in ("up", "down"):
            selected["direction"] = "down"
        if selected.get("url") is None:
            selected["url"] = ""
        if selected.get("text") is None:
            selected["text"] = ""
        if selected.get("reasoning") is None:
            selected["reasoning"] = ""
        if selected.get("expected_delta") is None:
            selected["expected_delta"] = ""
        if selected.get("element_id") is not None:
            selected["element_id"] = str(selected["element_id"])
        if selected.get("press_enter") is None:
            selected["press_enter"] = True
    try:
        return BrowserAction(**selected)
    except Exception as exc:
        print(f"[JarvisV2 Browser] Pydantic parsing failed for selected action: {selected}. Error: {exc}")
        return None


def _compact_failure_record(item: Any) -> dict[str, Any]:
    item_dict = model_to_dict(item)
    compacted = {
        "step_id": item_dict.get("step_id"),
        "category": item_dict.get("category"),
        "error_message": item_dict.get("error_message"),
        "attempt_count": item_dict.get("attempt_count"),
        "recovery_hint": item_dict.get("recovery_hint"),
        "retryable": item_dict.get("retryable"),
    }
    if "page_state_at_failure" in item_dict and item_dict["page_state_at_failure"]:
        pf = item_dict["page_state_at_failure"]
        compacted["url_at_failure"] = pf.get("url")
        compacted["title_at_failure"] = pf.get("title")
    return compacted


async def _call_browser_llm(step: TaskStep, snapshot: BrowserStateSnapshot, state: JarvisState) -> BrowserAction | None:
    if not _env_bool("JARVIS_V2_USE_LLM_BROWSER", True):
        return None

    try:
        from langchain_aws import ChatBedrockConverse
    except Exception:
        return None

    model_id = os.getenv("JARVIS_V2_BROWSER_MODEL_ID", "us.amazon.nova-pro-v1:0")
    region = os.getenv("AWS_BEDROCK_REGION", "us-west-1")
    prompt_payload = {
        "user_goal": state.get("user_goal", ""),
        "step": model_to_dict(step),
        "latest_observation": _compact_observation(snapshot),
        "recent_actions": [model_to_dict(item) for item in (state.get("action_history") or [])[-5:]],
        "recent_failures": [_compact_failure_record(item) for item in (state.get("failure_history") or [])[-3:]],
    }

    print(f"[TELEMETRY][BROWSER_AGENT] Requesting LLM action from model: {model_id} (Region: {region})")
    try:
        llm = ChatBedrockConverse(
            model=model_id,
            region_name=region,
            temperature=float(os.getenv("JARVIS_V2_BROWSER_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("JARVIS_V2_BROWSER_MAX_TOKENS", "1200")),
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=BROWSER_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(prompt_payload, ensure_ascii=True, default=str)),
            ]
        )
        content = response.content
        if isinstance(content, list):
            content = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
        extracted_json = _extract_json_object(str(content))
        print(f"[TELEMETRY][BROWSER_AGENT] LLM Response raw: {content}")
        return _parse_action(extracted_json)
    except Exception as exc:
        print(f"[JarvisV2 Browser] LLM action selection unavailable, using heuristic action: {exc}")
        return None


def _find_element(
    snapshot: BrowserStateSnapshot,
    *patterns: str,
    exclude_ids: set[str] | None = None,
) -> str | None:
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for element in snapshot.interactive_elements:
        element_id = element.get("id") or element.get("ref")
        if element_id is not None and exclude_ids and str(element_id) in exclude_ids:
            continue
        haystack = " ".join(
            str(element.get(key) or "")
            for key in ("name", "text", "placeholder", "context", "role", "tag", "type")
        )
        if "skip to" in haystack.lower() or "skip navigation" in haystack.lower():
            continue
        if any(regex.search(haystack) for regex in compiled):
            if element_id is not None:
                return str(element_id)
    return None


def _element_haystack(element: dict[str, Any]) -> str:
    return " ".join(
        str(element.get(key) or "")
        for key in ("name", "text", "placeholder", "context", "role", "tag", "type", "value")
    )


def _is_dropdown_option(element: dict[str, Any]) -> bool:
    haystack = _element_haystack(element).lower()
    role = str(element.get("role") or "").lower()
    tag = str(element.get("tag") or "").lower()
    if role in {"option", "menuitem"} or tag in {"li", "option"}:
        return True
    return any(
        marker in haystack
        for marker in ("autocomplete", "listbox", "dropdown", "suggestion", "results", "select airport")
    )


def _autocomplete_match_patterns(typed_text: str) -> list[str]:
    text = typed_text.strip().lower()
    patterns = [re.escape(part) for part in re.findall(r"[a-z0-9]{3,}", text)]
    if "delhi" in text or text == "del":
        patterns = [r"indira\s+gandhi", r"\bdel\b", r"delhi"] + patterns
    if "goa" in text or text == "goi":
        patterns = [r"\bgoi\b", r"goa", r"dabolim", r"manohar"] + patterns
    return patterns


def _autocomplete_followup_action(state: JarvisState, snapshot: BrowserStateSnapshot) -> BrowserAction | None:
    """After typing into an autocomplete field, click the best dropdown option.

    The order is intentional: related airport/city text first, then the first
    dropdown option only when no related text is present. It never falls back
    to arbitrary page elements.
    """
    history = list(state.get("action_history") or [])
    if not history:
        return None
    last_entry = history[-1]
    last_action = last_entry.action if hasattr(last_entry, "action") else None
    if last_action is None and isinstance(last_entry, dict) and isinstance(last_entry.get("action"), dict):
        try:
            last_action = BrowserAction(**last_entry["action"])
        except Exception:
            last_action = None
    last_success = bool(last_entry.success) if hasattr(last_entry, "success") else bool(last_entry.get("success")) if isinstance(last_entry, dict) else False
    if not last_action or last_action.action_type != "type" or not last_success:
        return None
    if len(history) >= 2:
        previous = history[-2].action if hasattr(history[-2], "action") else None
        if previous is None and isinstance(history[-2], dict) and isinstance(history[-2].get("action"), dict):
            try:
                previous = BrowserAction(**history[-2]["action"])
            except Exception:
                previous = None
        if previous and previous.action_type == "type" and previous.text == last_action.text:
            return None
    if last_action.press_enter:
        return None
    typed_text = (last_action.text or "").strip()
    if not typed_text:
        return None

    candidates: list[dict[str, Any]] = []
    for element in snapshot.interactive_elements:
        element_id = element.get("id") or element.get("ref")
        if element_id is None or not _is_dropdown_option(element):
            continue
        haystack = _element_haystack(element).lower()
        if not haystack.strip():
            continue
        candidates.append(element)

    if not candidates:
        return None

    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in _autocomplete_match_patterns(typed_text)]
    for element in candidates:
        haystack = _element_haystack(element)
        if any(pattern.search(haystack) for pattern in patterns):
            return BrowserAction(
                action_type="click",
                element_id=str(element.get("id") or element.get("ref")),
                reasoning=(
                    f"Typed '{typed_text}' into an autocomplete field; selecting the related "
                    f"dropdown option '{str(element.get('name') or element.get('text') or '')[:80]}'."
                ),
                expected_delta=f"The autocomplete field is set to the related option for {typed_text}.",
            )

    first = candidates[0]
    return BrowserAction(
        action_type="click",
        element_id=str(first.get("id") or first.get("ref")),
        reasoning=(
            f"Typed '{typed_text}' into an autocomplete field, but no related dropdown text matched. "
            "Selecting the first available dropdown option."
        ),
        expected_delta=f"The autocomplete field is set using the first dropdown option for {typed_text}.",
    )


def _extract_target_date(step: TaskStep, state: JarvisState) -> dict[str, str] | None:
    parts = [
        str(state.get("user_goal") or ""),
        step.description,
        step.success_criteria,
        json.dumps(step.params, ensure_ascii=True, default=str),
    ]
    text = " ".join(parts).lower()

    match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
        if not match:
            return None
        year, month_num, day = match.groups()
        month_index = int(month_num)
        if month_index < 1 or month_index > 12:
            return None
        month = list(dict.fromkeys(MONTH_NAMES.values()))[month_index - 1]
        return {"day": str(int(day)), "month": month, "year": year}

    day, month_raw, year = match.groups()
    month = MONTH_NAMES.get(month_raw.lower())
    if not month:
        return None
    return {"day": str(int(day)), "month": month, "year": year}


def _date_target_kind(step: TaskStep, state: JarvisState, action: BrowserAction | None = None) -> str:
    text = " ".join(
        [
            str(state.get("user_goal") or ""),
            step.description,
            step.success_criteria,
            json.dumps(step.params, ensure_ascii=True, default=str),
            action.reasoning if action else "",
            action.expected_delta if action else "",
        ]
    ).lower()
    if "return" in text and "departure" not in text:
        return "return"
    return "departure"


def _element_matches_target_date(element: dict[str, Any], target: dict[str, str], kind: str = "departure") -> bool:
    haystack = _element_haystack(element).lower()
    day = target["day"]
    month = target["month"]
    year = target["year"]

    has_full_date = (
        re.search(rf"\b{re.escape(day)}(?:st|nd|rd|th)?\b", haystack)
        and re.search(rf"\b{re.escape(month)}\b", haystack)
        and re.search(rf"\b{re.escape(year)}\b", haystack)
    )
    if not has_full_date:
        return False
    if kind == "departure" and "return" in haystack and "departure" not in haystack:
        return False
    if kind == "return" and "departure" in haystack and "return" not in haystack:
        return False
    return True


def _find_exact_date_element(snapshot: BrowserStateSnapshot, target: dict[str, str], kind: str = "departure") -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for element in snapshot.interactive_elements:
        element_id = element.get("id") or element.get("ref")
        if element_id is None:
            continue
        role = str(element.get("role") or "").lower()
        tag = str(element.get("tag") or "").lower()
        if role not in {"button", "gridcell", "option"} and tag not in {"button", "td", "div", "span"}:
            continue
        if _element_matches_target_date(element, target, kind):
            candidates.append(element)

    if not candidates:
        return None

    def score(element: dict[str, Any]) -> int:
        haystack = _element_haystack(element).lower()
        value = 0
        if kind in haystack:
            value += 3
        if "select" in haystack:
            value += 2
        if "disabled" in haystack or element.get("enabled") is False:
            value -= 5
        return value

    return sorted(candidates, key=score, reverse=True)[0]


def _date_followup_action(state: JarvisState, step: TaskStep, snapshot: BrowserStateSnapshot) -> BrowserAction | None:
    step_text = " ".join(
        [
            step.description,
            step.success_criteria,
            json.dumps(step.params, ensure_ascii=True, default=str),
        ]
    ).lower()
    if not any(marker in step_text for marker in ("date", "calendar", "departure", "return")):
        return None

    target = _extract_target_date(step, state)
    if not target:
        return None
    kind = _date_target_kind(step, state)
    element = _find_exact_date_element(snapshot, target, kind)
    if not element:
        return None
    label = str(element.get("name") or element.get("text") or "")[:100]
    return BrowserAction(
        action_type="click",
        element_id=str(element.get("id") or element.get("ref")),
        reasoning=f"Selecting the exact {kind} date match '{label}' for {target['day']} {target['month']} {target['year']}.",
        expected_delta=f"{kind.title()} date is set to {target['day']} {target['month']} {target['year']}.",
    )


def _is_date_selection_action(action: BrowserAction, step: TaskStep, state: JarvisState) -> bool:
    action_text = " ".join([action.reasoning, action.expected_delta]).lower()
    step_text = " ".join(
        [
            step.description,
            step.success_criteria,
            json.dumps(step.params, ensure_ascii=True, default=str),
        ]
    ).lower()
    action_mentions_date = any(marker in action_text for marker in ("date", "calendar", "departure", "return"))
    step_mentions_date = any(marker in step_text for marker in ("date", "calendar", "departure", "return"))
    return action_mentions_date or step_mentions_date


def _validate_date_click_action(
    action: BrowserAction,
    step: TaskStep,
    state: JarvisState,
    snapshot: BrowserStateSnapshot,
) -> tuple[BrowserAction, str | None]:
    if action.action_type != "click" or not _is_date_selection_action(action, step, state):
        return action, None

    target = _extract_target_date(step, state)
    if not target:
        return action, None

    kind = _date_target_kind(step, state, action)
    chosen: dict[str, Any] | None = None
    for element in snapshot.interactive_elements:
        element_id = element.get("id") or element.get("ref")
        if str(element_id) == str(action.element_id):
            chosen = element
            break

    if chosen and _element_matches_target_date(chosen, target, kind):
        return action, None

    chosen_text = _element_haystack(chosen).lower() if chosen else ""
    action_text = f"{action.reasoning} {action.expected_delta}".lower()
    if chosen and (
        "calendar" in action_text
        or "date picker" in action_text
        or "please select your departure date" in chosen_text
        or ("departure date" in chosen_text and "select" in chosen_text)
    ):
        return action, None

    exact = _find_exact_date_element(snapshot, target, kind)
    if exact:
        replacement = BrowserAction(
            action_type="click",
            element_id=str(exact.get("id") or exact.get("ref")),
            reasoning=(
                f"Replacing mismatched date click with exact {kind} date "
                f"{target['day']} {target['month']} {target['year']}."
            ),
            expected_delta=f"{kind.title()} date is set to {target['day']} {target['month']} {target['year']}.",
        )
        chosen_summary = _element_haystack(chosen)[:120] if chosen else str(action.element_id)
        return replacement, f"Date guard replaced element {action.element_id} ({chosen_summary}) with exact element {replacement.element_id}."

    return BrowserAction(
        action_type="fail",
        reasoning=(
            f"Target {kind} date {target['day']} {target['month']} {target['year']} is not present in the current "
            "calendar registry, so refusing to click a nearby or guessed date."
        ),
        expected_delta="Re-observe or navigate the calendar until the exact target date is visible.",
    ), "Date guard blocked a mismatched calendar click; exact target date was not visible."


def _heuristic_action(
    step: TaskStep,
    snapshot: BrowserStateSnapshot,
    turn: int,
    clicked_dismiss_ids: set[str] | None = None,
) -> BrowserAction:
    if step.objective_type == "navigate" and step.params.get("url") and turn == 0:
        return BrowserAction(
            action_type="open_url",
            url=str(step.params["url"]),
            reasoning="Planner supplied a direct target URL for this navigation step.",
            expected_delta="The browser URL should change and a page should load.",
        )

    dismiss_id = _find_element(
        snapshot,
        r"\b(accept|agree|allow|ok|close|dismiss|skip|not now|continue on web)\b",
        exclude_ids=clicked_dismiss_ids,
    )
    if dismiss_id:
        return BrowserAction(
            action_type="click",
            element_id=dismiss_id,
            reasoning="A likely popup or permission control is visible and may block progress.",
            expected_delta="The popup disappears or page interaction becomes available.",
        )

    goal = str(step.params.get("user_goal") or step.description)
    search_terms = re.sub(
        r"\b(open|go to|search|find|on|in|from|for|me|please|jarvis|complete|browser|objective)\b",
        " ",
        goal,
        flags=re.IGNORECASE,
    )
    search_terms = re.sub(r"\s+", " ", search_terms).strip()
    search_id = _find_element(snapshot, r"search", r"textbox", r"searchbox")
    if search_id and search_terms and turn <= 2:
        return BrowserAction(
            action_type="type",
            element_id=search_id,
            text=search_terms[:120],
            reasoning="A search/text field is available and can drive the page toward the objective.",
            press_enter=True,
            expected_delta="Search results or matching page content appears.",
        )

    if turn < 4:
        return BrowserAction(
            action_type="scroll",
            direction="down",
            reasoning="The needed element or information is not visible yet.",
            expected_delta="More page content becomes visible.",
        )

    return BrowserAction(
        action_type="fail",
        reasoning="No grounded action is available from the current observation.",
        expected_delta="Escalate to recovery or replanning.",
    )


async def _execute_action(action: BrowserAction) -> dict[str, Any]:
    if action.action_type == "open_url":
        return await open_url(action.url)
    if action.action_type == "observe":
        return await observe_with_registry(include_screenshot=False, include_ax_tree_text=True)
    if action.action_type == "click":
        if not action.element_id:
            return {"success": False, "action": "click", "error": "click action missing element_id"}
        return await interact_by_registry_id(action.element_id, "click")
    if action.action_type == "type":
        if not action.element_id:
            return {"success": False, "action": "type", "error": "type action missing element_id"}
        res = await interact_by_registry_id(action.element_id, "type", action.text, action.press_enter)
        try:
            page = await BrowserStateManager.get_page()
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        return res
    if action.action_type == "scroll":
        return await scroll_page(action.direction)
    if action.action_type == "go_back":
        return await go_back()
    if action.action_type == "wait":
        page = await BrowserStateManager.get_page()
        await page.wait_for_timeout(1000)
        return {"success": True, "action": "wait", "observation": "Waited for dynamic page updates."}
    if action.action_type == "done":
        return {"success": True, "action": "done", "observation": action.reasoning or "Step complete."}
    return {"success": False, "action": action.action_type, "error": action.reasoning or "Browser Agent chose to fail."}


def _result_summary(result: dict[str, Any]) -> str:
    return str(result.get("observation") or result.get("error") or result.get("action") or "")[:500]


async def execute_browser_step(state: JarvisState) -> JarvisState:
    state = ensure_state_defaults(state)
    step = get_current_step(state)
    if not step:
        return {**state, "completion_status": "completed"}

    max_actions = int(os.getenv("JARVIS_V2_BROWSER_ACTION_BUDGET", "10"))
    include_screenshot = _env_bool("JARVIS_V2_BROWSER_SCREENSHOTS", False)
    started_step = step.model_copy(update={"status": "running", "attempt_count": step.attempt_count + 1})
    state = {**state, "task_plan": replace_current_step(state, started_step), "browser_active": True}

    print(f"\n[TELEMETRY][BROWSER_AGENT] ========================================================")
    print(f"[TELEMETRY][BROWSER_AGENT] Starting Browser Agent Node execution.")
    print(f"[TELEMETRY][BROWSER_AGENT] Goal: '{state.get('user_goal')}'")
    print(f"[TELEMETRY][BROWSER_AGENT] Step ID: '{started_step.id}' | Description: '{started_step.description}'")
    print(f"[TELEMETRY][BROWSER_AGENT] Success Criteria: '{started_step.success_criteria}'")
    print(f"[TELEMETRY][BROWSER_AGENT] Attempt Count: {started_step.attempt_count} / {started_step.max_attempts}")
    print(f"[TELEMETRY][BROWSER_AGENT] ========================================================")

    actions_performed: list[BrowserAction] = []
    new_action_history = list(state.get("action_history") or [])
    new_observations = list(state.get("browser_observations") or [])
    last_snapshot: BrowserStateSnapshot | None = None
    _pre_action_snapshot: BrowserStateSnapshot | None = None
    _last_executed_action: BrowserAction | None = None
    clicked_dismiss_ids: set[str] = set()

    for turn in range(max_actions):
        print(f"\n[TELEMETRY][BROWSER_AGENT] --- Action Turn {turn + 1} / {max_actions} ---")
        observe_result = await observe_with_registry(
            include_screenshot=include_screenshot,
            include_ax_tree_text=True,
        )
        if not observe_result.get("success"):
            error = str(observe_result.get("error") or "Observation failed")
            category = classify_browser_error(error, "")
            print(f"[TELEMETRY][BROWSER_AGENT] Observation failed! error='{error}', classified as '{category}'")
            failed_step = started_step.model_copy(update={"status": "failed", "result": error})
            failure = FailureRecord(
                step_id=started_step.id,
                category=category,
                error_message=error,
                attempt_count=started_step.attempt_count,
                retryable=True,
            )
            result = BrowserExecutionResult(
                step_id=started_step.id,
                success=False,
                summary=error,
                actions_performed=actions_performed,
                error_type=category,
                error_message=error,
                needs_replan=False,
            )
            return {
                **state,
                "task_plan": replace_current_step(state, failed_step),
                "failure_history": list(state.get("failure_history") or []) + [failure],
                "browser_execution_results": list(state.get("browser_execution_results") or []) + [result],
                "completion_status": "recovering",
            }

        last_snapshot = _snapshot_from_observation(observe_result.get("data") or {})
        print(f"[TELEMETRY][BROWSER_AGENT] Observed URL: '{last_snapshot.url}' | Title: '{last_snapshot.title}'")
        new_observations.append(last_snapshot)

        # ── Post-action assertion (validates the PREVIOUS turn's action) ──
        if _last_executed_action is not None and _pre_action_snapshot is not None:
            assertion_ok, assertion_detail = _assert_action_outcome(
                _last_executed_action, _pre_action_snapshot, last_snapshot,
            )
            print(f"[TELEMETRY][BROWSER_AGENT] Post-Action Assertion: success={assertion_ok} | details='{assertion_detail}'")
            if not assertion_ok:
                state = {
                    **state,
                    "scratchpad": (state.get("scratchpad") or "")
                    + f"\n[PostAssert WARN] turn {turn}: {assertion_detail}",
                }
            _last_executed_action = None
            _pre_action_snapshot = None

        success, evidence, confidence = _verify_success_criteria(started_step, last_snapshot, turn)
        print(f"[TELEMETRY][BROWSER_AGENT] Step Success Check: success={success} | confidence={confidence} | evidence={evidence}")
        if success and (turn > 0 or started_step.objective_type == "navigate"):
            print(f"[TELEMETRY][BROWSER_AGENT] Step '{started_step.id}' Success Criteria MET! Exiting execution loop.")
            completed_step = started_step.model_copy(
                update={"status": "completed", "result": "; ".join(evidence) or "Success criteria satisfied."}
            )
            result = BrowserExecutionResult(
                step_id=started_step.id,
                success=True,
                summary=completed_step.result or "Browser step completed.",
                actions_performed=actions_performed,
                final_observation=last_snapshot,
                confidence=confidence,
                evidence=evidence,
            )
            return {
                **state,
                "task_plan": replace_current_step(state, completed_step),
                "current_browser_state": last_snapshot,
                "browser_observations": new_observations[-20:],
                "browser_execution_results": list(state.get("browser_execution_results") or []) + [result],
                "action_history": new_action_history[-50:],
                "task_progress": list(state.get("task_progress") or []) + [f"{completed_step.id}: {completed_step.result}"],
                "completion_status": "executing",
            }

        action = _date_followup_action({**state, "action_history": new_action_history}, started_step, last_snapshot)
        if action is not None:
            print(
                "[TELEMETRY][BROWSER_AGENT] Exact date selection: "
                f"action={action.action_type} | element_id={action.element_id} | reasoning='{action.reasoning}'"
            )
        if action is None:
            action = _autocomplete_followup_action({**state, "action_history": new_action_history}, last_snapshot)
        if action is not None:
            print(
                "[TELEMETRY][BROWSER_AGENT] Deterministic follow-up selection: "
                f"action={action.action_type} | element_id={action.element_id} | reasoning='{action.reasoning}'"
            )
        else:
            action = await _call_browser_llm(started_step, last_snapshot, state)
        if action is None:
            print(f"[TELEMETRY][BROWSER_AGENT] No LLM response. Invoking heuristic decision strategy...")
            action = _heuristic_action(started_step, last_snapshot, turn, clicked_dismiss_ids)
            print(f"[TELEMETRY][BROWSER_AGENT] Heuristic selection: action={action.action_type} | element_id={action.element_id} | reasoning='{action.reasoning}'")
            if action.action_type == "click" and action.element_id:
                clicked_dismiss_ids.add(str(action.element_id))
        else:
            print(f"[TELEMETRY][BROWSER_AGENT] LLM decision: action={action.action_type} | element_id={action.element_id} | reasoning='{action.reasoning}'")

        action, date_guard_detail = _validate_date_click_action(action, started_step, state, last_snapshot)
        if date_guard_detail:
            print(f"[TELEMETRY][BROWSER_AGENT] Date Guard: {date_guard_detail}")
            state = {
                **state,
                "scratchpad": (state.get("scratchpad") or "") + f"\n[DateGuard] {date_guard_detail}",
            }

        # ── Pre-action element verification ──
        if action.element_id and not _verify_element_available(action.element_id, last_snapshot):
            print(f"[TELEMETRY][BROWSER_AGENT] Pre-verify warning: Target element {action.element_id} missing from current page. Falling back to heuristic.")
            state = {
                **state,
                "scratchpad": (state.get("scratchpad") or "")
                + f"\n[PreVerify] Element {action.element_id} missing from registry, falling back to heuristic.",
            }
            action = _heuristic_action(started_step, last_snapshot, turn, clicked_dismiss_ids)
            print(f"[TELEMETRY][BROWSER_AGENT] Heuristic selection (after missing element fallback): action={action.action_type} | element_id={action.element_id} | reasoning='{action.reasoning}'")
            if action.action_type == "click" and action.element_id:
                clicked_dismiss_ids.add(str(action.element_id))

        # ── Deterministic action confidence guard ──
        action_score = _score_candidate_action(action, last_snapshot)
        print(f"[TELEMETRY][BROWSER_AGENT] Action validation confidence score: {action_score}")
        if action_score < 0.3 and action.action_type != "fail":
            print(f"[TELEMETRY][BROWSER_AGENT] Confidence score below threshold (< 0.3). Falling back to heuristic.")
            state = {
                **state,
                "scratchpad": (state.get("scratchpad") or "")
                + f"\n[Guard] Action scored {action_score:.2f}, replacing with heuristic.",
            }
            action = _heuristic_action(started_step, last_snapshot, turn, clicked_dismiss_ids)
            print(f"[TELEMETRY][BROWSER_AGENT] Heuristic selection (after confidence guard fallback): action={action.action_type} | element_id={action.element_id} | reasoning='{action.reasoning}'")
            if action.action_type == "click" and action.element_id:
                clicked_dismiss_ids.add(str(action.element_id))

        if action.action_type == "done":
            print(f"[TELEMETRY][BROWSER_AGENT] Selected action is DONE. Finalizing step.")
            completed_step = started_step.model_copy(update={"status": "completed", "result": action.reasoning})
            result = BrowserExecutionResult(
                step_id=started_step.id,
                success=True,
                summary=action.reasoning or "Browser Agent reported completion.",
                actions_performed=actions_performed + [action],
                final_observation=last_snapshot,
                confidence=0.8,
                evidence=[action.reasoning] if action.reasoning else [],
            )
            return {
                **state,
                "task_plan": replace_current_step(state, completed_step),
                "current_browser_state": last_snapshot,
                "browser_observations": new_observations[-20:],
                "browser_execution_results": list(state.get("browser_execution_results") or []) + [result],
                "task_progress": list(state.get("task_progress") or []) + [f"{completed_step.id}: completed."],
                "completion_status": "executing",
            }

        # Save pre-action state for post-action assertion on the next turn.
        _pre_action_snapshot = last_snapshot
        _last_executed_action = action

        print(f"[TELEMETRY][BROWSER_AGENT] Launching execution for action: {action.action_type} (element_id={action.element_id}, text='{action.text}', url='{action.url}')")
        start_time = time.perf_counter()
        action_result = await _execute_action(action)
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        actions_performed.append(action)
        new_action_history.append(
            ActionHistoryEntry(
                step_id=started_step.id,
                action=action,
                success=bool(action_result.get("success")),
                result_summary=_result_summary(action_result),
                error=action_result.get("error"),
                before_observation_id=last_snapshot.observation_id if last_snapshot else None,
                duration_ms=duration_ms,
            )
        )
        print(f"[TELEMETRY][BROWSER_AGENT] Action executed in {duration_ms}ms. Result Success: {action_result.get('success')} | Summary: '{_result_summary(action_result)}'")

        if not action_result.get("success"):
            page_text = ""
            if last_snapshot:
                page_text = f"{last_snapshot.summary}\n{last_snapshot.accessibility_tree}"
            error = str(action_result.get("error") or action_result.get("observation") or "Browser action failed")
            category = classify_browser_error(error, page_text, action.action_type)
            print(f"[TELEMETRY][BROWSER_AGENT] Browser Action failed! error='{error}', classified category='{category}'")
            failed_step = started_step.model_copy(update={"status": "failed", "result": error})
            failure = FailureRecord(
                step_id=started_step.id,
                category=category,
                error_message=error,
                attempt_count=started_step.attempt_count,
                page_state_at_failure=last_snapshot,
                retryable=started_step.attempt_count < started_step.max_attempts,
            )
            result = BrowserExecutionResult(
                step_id=started_step.id,
                success=False,
                summary=error,
                actions_performed=actions_performed,
                final_observation=last_snapshot,
                error_type=category,
                error_message=error,
                needs_replan=not failure.retryable,
            )
            return {
                **state,
                "task_plan": replace_current_step(state, failed_step),
                "current_browser_state": last_snapshot,
                "browser_observations": new_observations[-20:],
                "browser_execution_results": list(state.get("browser_execution_results") or []) + [result],
                "action_history": new_action_history[-50:],
                "failure_history": list(state.get("failure_history") or []) + [failure],
                "completion_status": "recovering" if failure.retryable else "executing",
            }

    error_message = f"Browser action budget exhausted after {max_actions} actions."
    print(f"[TELEMETRY][BROWSER_AGENT] {error_message}")
    failed_step = started_step.model_copy(update={"status": "failed", "result": error_message})
    failure = FailureRecord(
        step_id=started_step.id,
        category="validation_failed",
        error_message=error_message,
        attempt_count=started_step.attempt_count,
        page_state_at_failure=last_snapshot,
        retryable=started_step.attempt_count < started_step.max_attempts,
    )
    result = BrowserExecutionResult(
        step_id=started_step.id,
        success=False,
        summary=error_message,
        actions_performed=actions_performed,
        final_observation=last_snapshot,
        error_type="validation_failed",
        error_message=error_message,
        needs_replan=not failure.retryable,
    )
    return {
        **state,
        "task_plan": replace_current_step(state, failed_step),
        "current_browser_state": last_snapshot,
        "browser_observations": new_observations[-20:],
        "browser_execution_results": list(state.get("browser_execution_results") or []) + [result],
        "action_history": new_action_history[-50:],
        "failure_history": list(state.get("failure_history") or []) + [failure],
        "completion_status": "recovering" if failure.retryable else "executing",
    }
