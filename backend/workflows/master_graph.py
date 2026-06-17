"""
master_graph.py — Master LangGraph ReAct Agent with Vision
Builds a StateGraph with LLM caching, MemorySaver checkpointing,
tool error recovery, Llama hallucination interception,
and vision-guided browser observation via screenshots.
"""
import re
import json
import uuid
import os
import copy
import hashlib
import time
from typing import Any, TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_aws import ChatBedrockConverse

from workflows.tool_wrapper import ALL_TOOLS

MAX_AGENT_ITERATIONS = int(os.getenv("JARVIS_MAX_AGENT_ITERATIONS", "10"))
MIN_TOOL_CONFIDENCE = float(os.getenv("JARVIS_MIN_TOOL_CONFIDENCE", "0.55"))
# Tools that are allowed ONE verbatim retry before the loop-guard blocks them.
# A weak/empty result is a legitimate reason to re-run these (search snippets vary,
# observations re-scan the page) — unlike action tools, where an identical repeat
# really is a stuck loop. They get seen_count>=2 grace instead of >=1.
_RETRYABLE_TOOLS = {"browser_observe", "tavily_search", "browser_search", "fetch"}
CONTEXT_WINDOW_SIZE = int(os.getenv("JARVIS_CONTEXT_WINDOW_SIZE", "6"))  # Keep last N AI+Tool pairs in full
# ── Route-scoped MCP tool binding ─────────────────────────
# Native tools (browser/file/whatsapp/weather) are ALWAYS bound — they're the
# agent's core hands and were already reliable. We only scope MCP-sourced tools
# by the router's decision so adding more MCP servers can't flood Nova's tool
# list on turns where they're irrelevant. Maps route -> allowed MCP groups.
# An unknown/empty route keeps ALL MCP tools (fail-open; never regress).
_MCP_ROUTE_GROUPS: dict[str, set[str]] = {
    "browser": {"web", "fs", "memory"},    # web research + save/read files + recall user facts
    "mission": {"web", "fs", "voice", "monitoring", "memory", "google"},    # complex multi-step: allow everything
    "tool":    {"fs", "voice", "monitoring", "memory", "google"},           # local actions: fs, voice, monitoring, memory, Gmail/Calendar/Drive
    "vision":  set(),            # screen-look: no MCP tools (shouldn't reach graph)
}

# MCP groups that are bound on EVERY route, regardless of the route map above.
# Voice is always-on so JARVIS can speak/narrate during any task (incl. browser
# and vision turns). Survives future route additions automatically.
_ALWAYS_ALLOWED_MCP_GROUPS: set[str] = {"voice"}


def _route_scoping_enabled() -> bool:
    return os.getenv("JARVIS_ROUTE_SCOPED_TOOLS", "true").strip().lower() in {"1", "true", "yes", "on"}


def _is_mcp_tool(tool) -> bool:
    return bool((getattr(tool, "metadata", None) or {}).get("mcp"))


def _scope_mcp_tools_by_route(tools: list, route: str) -> list:
    """Drop MCP tools that don't belong to the given route. Native tools are kept
    untouched. Fail-open: unknown route -> keep all MCP tools."""
    if not _route_scoping_enabled():
        return tools
    route = (route or "").strip().lower()
    if route not in _MCP_ROUTE_GROUPS:        # "" / unknown -> no scoping
        return tools
    allowed = _MCP_ROUTE_GROUPS[route]
    scoped = []
    for t in tools:
        if not _is_mcp_tool(t):
            scoped.append(t)                  # native tool — always keep
            continue
        group = (getattr(t, "metadata", None) or {}).get("mcp_group", "web")
        if group in allowed or group in _ALWAYS_ALLOWED_MCP_GROUPS:
            scoped.append(t)
    return scoped

# ── LLM Instance Cache ────────────────────────────────────
# Avoids re-instantiating ChatBedrockConverse on every graph iteration.
# Each unique model_id gets one cached instance.
_llm_cache: dict[str, ChatBedrockConverse] = {}


def _clone_message(msg: BaseMessage) -> BaseMessage:
    """Clone messages before vision cleanup so checkpoints/history are not mutated."""
    if hasattr(msg, "model_copy"):
        return msg.model_copy(deep=True)
    if hasattr(msg, "copy"):
        return msg.copy(deep=True)
    return copy.deepcopy(msg)

def _is_vision_capable(model_id: str) -> bool:
    """Claude and Llama-4 Maverick (and Nova) can read images; Llama 3.x cannot.

    Used so we don't downgrade a vision-capable agent model (e.g. Claude Sonnet)
    back to the fallback Maverick vision model just because a screenshot appeared.
    """
    mid = (model_id or "").lower()
    return ("claude" in mid) or ("maverick" in mid) or ("nova" in mid)


def _get_llm(model_id: str, region: str) -> ChatBedrockConverse:
    """Returns a cached LLM instance, creating one if needed."""
    if model_id not in _llm_cache:
        _llm_cache[model_id] = ChatBedrockConverse(
            model=model_id,
            region_name=region,
            max_tokens=1024,
            temperature=0.3
        )
        print(f"[Graph] Created new LLM instance: {model_id}")
    else:
        print(f"[Graph] Reusing cached LLM: {model_id}")
    return _llm_cache[model_id]

# ── State Schema ──────────────────────────────────────────
class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int  # Accurate iteration counter
    tool_history: list[dict[str, Any]]
    loop_signatures: dict[str, int]
    tool_failures: dict[str, int]
    last_observation: dict[str, Any]
    last_observation_id: str
    last_page_fingerprint: str
    last_element_ids: list[Any]
    interactive_registry: dict[str, Any]
    blocked_tool_call: bool
    final_status: str
    task_progress: list[str]  # Track completed sub-tasks for progress awareness
    stale_iterations: int  # Consecutive iterations with no tool calls (stale loop detection)
    file_write_completed: bool  # Set True when file_write tool succeeds — signals task is likely done
    token_usage: dict[str, int]  # Accumulated token usage {"input": 0, "output": 0, "total": 0}
    token_budget: int  # Token limit budget ceiling

# ── Graph Edges ───────────────────────────────────────────
def should_continue(state: AgentState):
    """Determine whether to route to tools or end the conversation."""
    messages = state['messages']
    last_message = messages[-1]
    
    # ── Token Budget Check ──
    token_usage = state.get("token_usage") or {}
    total_tokens = token_usage.get("total", 0)
    token_budget = state.get("token_budget", int(os.getenv("JARVIS_TOKEN_BUDGET", "200000")))
    if total_tokens > token_budget:
        print(f"[Graph] Token budget exceeded: {total_tokens}/{token_budget} — halting")
        return "loop_halt"
    
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        # stale_iterations is already set by call_model (0 if tool calls, +1 if not)
        stale = state.get("stale_iterations", 0)
        
        # ── File-Write Completion Gate ──
        # If the agent already wrote a file (goal output) and now has no more tool calls,
        # it's done — don't let it keep browsing for "more info".
        if state.get("file_write_completed"):
            print(f"[Graph] Task output file already written — agent has no more tool calls — ending gracefully")
            return END
        
        # ── Stale Loop Detection ──
        missing_research = _missing_required_research_terms(state)
        if missing_research and stale <= 2:
            print(f"[Graph] Missing required comparison research: {', '.join(missing_research)}")
            return "retry"

        if stale >= 3:
            print(f"[Graph] Stale loop detected: {stale} consecutive iterations with no tool calls — terminating")
            return "loop_halt"
        
        # ── Intent-Without-Action Detection ──
        # If the LLM says "I will now...", route back so it can actually make the tool call
        content = str(getattr(last_message, 'content', '') or '')
        intent_phrases = [
            "i will now", "let me", "now i will", "i shall", "i'll now", "next, i will",
            "i will search", "i will open", "i will navigate", "i will check",
            "i'll check", "allow me", "allow me to", "certainly, sir", "right away",
            "one moment", "give me a moment", "let me check", "i'll take a look",
            "i will take a look", "checking the", "let me find", "i'll find",
        ]
        if any(phrase in content.lower() for phrase in intent_phrases) and stale <= 1:
            print(f"[Graph] Intent-without-action detected — routing back to agent for tool call")
            return "retry"

        # ── Grounded-Evidence Gate (anti-hallucination, flag-gated) ──
        # Don't let the agent finish a web task by stating facts (prices/numbers) that
        # never appeared in a page it actually observed. Force one more observe instead.
        if os.getenv("JARVIS_GROUNDED_ANSWERS", "false").lower() in {"1", "true", "yes", "on"} \
                and _used_browser(state) and not state.get("file_write_completed"):
            answer = str(getattr(last_message, "content", "") or "")
            if answer and not _answer_is_grounded(answer, state) and stale < 2:
                print("[Grounding] Final answer not supported by observations — forcing re-observe")
                return "retry"

        return END
    if state.get("iteration", 0) >= MAX_AGENT_ITERATIONS:
        return "loop_halt"
    return "tool_guard"


def _route_after_tool_guard(state: AgentState):
    return "agent" if state.get("blocked_tool_call") else "tools"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    except TypeError:
        return str(value)


def _safe_console_text(value: Any) -> str:
    return str(value).encode("ascii", "replace").decode("ascii")


def _first_user_text(state: AgentState) -> str:
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            return str(getattr(msg, "content", "") or "")
    return ""


def _browser_history_mentions(state: AgentState, term: str) -> bool:
    needle = term.lower()
    for record in state.get("tool_history", []) or []:
        if record.get("phase") != "guard":
            continue
        tool_name = str(record.get("tool") or "")
        if not tool_name.startswith("browser_"):
            continue
        haystack = _safe_json(record.get("arguments") or {}).lower()
        if needle in haystack:
            return True
    return False


def _requested_output_path(goal: str) -> str:
    matches = re.findall(r"\b[A-Za-z0-9_\-./\\]+(?:\.(?:txt|md|json|py))\b", goal)
    return matches[-1].replace("\\", "/").lstrip("/") if matches else ""


def _normalized_file_path(path: Any) -> str:
    return str(path or "").replace("\\", "/").lstrip("/")


def _required_goal_terms(goal: str) -> list[str]:
    text = goal.lower()
    terms: list[str] = []
    for term in (
        "iphone",
        "amazon",
        "flipkart",
        "nvidia",
        "amd",
        "apple",
    ):
        if term in text:
            terms.append(term)
    return terms


def _missing_required_content_terms(goal: str, content: str) -> list[str]:
    content_lower = content.lower()
    required = _required_goal_terms(goal)
    return [term for term in required if term not in content_lower]


def _missing_required_research_terms(state: AgentState) -> list[str]:
    goal = _first_user_text(state).lower()
    if not any(word in goal for word in ("compare", "comparison", "versus", " vs ", "price", "deal", "deals", "revenue")):
        return []
    terms = _required_goal_terms(goal)
    return [term for term in terms if not _browser_history_mentions(state, term)]


def _parse_tool_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            data = json.loads(content)
            return data if isinstance(data, dict) else {"raw": content}
        except json.JSONDecodeError:
            return {"raw": content}
    return {"raw": str(content)}


# ── Grounded-Evidence helpers (anti-hallucination) ──
def _collect_observation_text(state: AgentState) -> str:
    """All real page content the agent actually observed this run (browser_observe payloads)."""
    chunks = []
    last = state.get("last_observation") or {}
    if isinstance(last, dict):
        chunks.append(str(last.get("summary", "")) + " " + str(last.get("accessibility_tree", "")))
    for m in state.get("messages", []):
        if isinstance(m, ToolMessage):
            payload = _parse_tool_payload(m.content)
            if str(payload.get("action")) == "browser_observe":
                data = payload.get("data") or {}
                chunks.append(str(data.get("summary", "")) + " " + str(data.get("accessibility_tree", "")))
    return " ".join(chunks).lower()


def _used_browser(state: AgentState) -> bool:
    return any(str(r.get("tool", "")).startswith("browser_") for r in (state.get("tool_history") or []))


def _answer_is_grounded(answer: str, state: AgentState) -> bool:
    """A factual answer must share specific numeric claims with observed page text.
    Pure prose with no hard claims passes; money/numbers must be backed by an observation."""
    obs = _collect_observation_text(state)
    if not obs:
        return False  # browser task but nothing observed -> not grounded
    claims = re.findall(r'(?:rs\.?|₹|\$)\s?\d[\d,]*|\b\d{2,}\b', answer.lower())
    if not claims:
        return True  # no hard factual claims to verify
    obs_digits = re.sub(r'[^\d]', '', obs)
    backed = sum(1 for c in claims if re.sub(r'[^\d]', '', c) and re.sub(r'[^\d]', '', c) in obs_digits)
    return backed >= max(1, len(claims) // 2)


def _tool_call_name(call: dict[str, Any]) -> str:
    return str(call.get("name") or call.get("function", {}).get("name") or "")


def _tool_call_args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args")
    if args is None and isinstance(call.get("function"), dict):
        args = call["function"].get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return args if isinstance(args, dict) else {}


def _tool_call_id(call: dict[str, Any]) -> str:
    return str(call.get("id") or f"call_{uuid.uuid4().hex[:10]}")


def _page_fingerprint(data: dict[str, Any]) -> str:
    ax_tree = data.get("accessibility_tree", "")
    if ax_tree:
        standardized_tree = re.sub(r"\s+", " ", ax_tree).strip()
        basis = f"{data.get('url', '')}:{standardized_tree}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    elements = data.get("interactive_elements") or []
    compact_elements = [
        {
            "id": item.get("id"),
            "tag": item.get("tag"),
            "role": item.get("role"),
            "text": item.get("text"),
            "context": item.get("context"),
        }
        for item in elements[:80]
        if isinstance(item, dict)
    ]
    basis = {
        "url": data.get("url", ""),
        "title": data.get("title", ""),
        "summary": str(data.get("summary", ""))[:1000],
        "elements": compact_elements,
    }
    return hashlib.sha256(_safe_json(basis).encode("utf-8")).hexdigest()[:16]


def _tool_signature(call: dict[str, Any], state: AgentState) -> str:
    name = _tool_call_name(call)
    args = _tool_call_args(call)
    browser_scope = state.get("last_page_fingerprint", "") if name.startswith("browser_") else ""
    raw = {"tool": name, "args": args, "page": browser_scope}
    return hashlib.sha256(_safe_json(raw).encode("utf-8")).hexdigest()[:16]


def _score_tool_call(call: dict[str, Any], state: AgentState) -> tuple[float, str]:
    name = _tool_call_name(call)
    args = _tool_call_args(call)
    known_tools = {tool.name for tool in ALL_TOOLS}
    if name not in known_tools:
        return 0.0, "unknown_tool"

    if name == "browser_open_url":
        url = args.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return 0.95, "valid_url"
        return 0.35, "browser_open_url_requires_http_url"

    if name == "browser_observe":
        return 0.82, "observation_is_safe"

    if name == "browser_interact":
        element_id = args.get("element_id")
        action = args.get("action")
        if action not in {"click", "type"}:
            return 0.25, "invalid_browser_action"
        if action == "type" and not str(args.get("text", "")).strip():
            return 0.40, "type_action_requires_text"
        if not state.get("last_observation_id"):
            return 0.30, "browser_interact_requires_recent_observation"
        
        allowed_ids = set(state.get("last_element_ids") or [])
        is_valid = (element_id in allowed_ids)
        if not is_valid:
            try:
                is_valid = (int(element_id) in allowed_ids)
            except (ValueError, TypeError):
                pass
        if not is_valid:
            try:
                is_valid = (str(element_id) in allowed_ids)
            except (ValueError, TypeError):
                pass
                
        if not is_valid:
            return 0.42, "element_id_not_in_latest_observation"
        return 0.92, "grounded_element_id"

    if name == "browser_scroll":
        direction = str(args.get("direction", "down")).lower()
        if direction not in {"up", "down"}:
            return 0.35, "invalid_scroll_direction"
        return (0.75, "scroll_after_observation") if state.get("last_observation_id") else (0.55, "scroll_without_observation")

    if name in {"browser_get_status", "browser_go_back"}:
        return 0.75, "low_risk_browser_control"

    if name == "file_write":
        path = args.get("path")
        content = args.get("content")
        if not (isinstance(path, str) and re.search(r"\.(txt|md|json|py)$", path, re.IGNORECASE) and isinstance(content, str)):
            return 0.35, "file_write_requires_safe_path_and_content"
        goal = _first_user_text(state)
        requested_path = _requested_output_path(goal)
        if requested_path and _normalized_file_path(path).lower() != requested_path.lower():
            return 0.35, f"file_write_path_mismatch_expected_{requested_path}"
        missing_terms = _missing_required_research_terms(state)
        if missing_terms:
            return 0.35, "file_write_missing_required_research_" + "_".join(missing_terms)
        missing_content_terms = _missing_required_content_terms(goal, content)
        if missing_content_terms:
            return 0.35, "file_write_content_missing_" + "_".join(missing_content_terms)
        return 0.88, "valid_file_write"

    if name in {"file_read", "file_list", "file_search", "weather_check", "whatsapp_check_messages"}:
        return 0.82, "valid_low_risk_tool"

    if name == "whatsapp_send_message":
        if str(args.get("contact", "")).strip() and str(args.get("message", "")).strip():
            return 0.70, "risky_tool_requires_confirmation_upstream"
        return 0.30, "whatsapp_send_requires_contact_and_message"

    return 0.65, "known_tool"


def _extract_token_usage(response: Any) -> dict[str, int]:
    """Extracts input and output tokens from AIMessage in a model-agnostic way."""
    input_tokens = 0
    output_tokens = 0
    
    # 1. Try standard langchain usage_metadata
    usage_metadata = getattr(response, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        input_tokens = usage_metadata.get("input_tokens", 0)
        output_tokens = usage_metadata.get("output_tokens", 0)
        
    # 2. Try response_metadata
    if not input_tokens or not output_tokens:
        response_metadata = getattr(response, "response_metadata", {})
        if isinstance(response_metadata, dict):
            # Check for standard 'usage' key
            usage = response_metadata.get("usage", {})
            if isinstance(usage, dict):
                input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0
            
            # Check for Bedrock-specific invocation metrics
            if not input_tokens or not output_tokens:
                metrics = response_metadata.get("amazon-bedrock-invocationMetrics", {})
                if isinstance(metrics, dict):
                    input_tokens = metrics.get("inputTokenCount") or 0
                    output_tokens = metrics.get("outputTokenCount") or 0
                    
    total_tokens = input_tokens + output_tokens
    return {
        "input": input_tokens,
        "output": output_tokens,
        "total": total_tokens
    }


async def _emit_graph_event(event_type: str, payload: dict[str, Any], level: str = "info") -> None:
    try:
        from services.dashboard_event_service import emit_dashboard_event

        await emit_dashboard_event(event_type, payload, source="graph", level=level)
    except Exception as exc:
        print(f"[Graph Telemetry] Failed to emit {event_type}: {exc}")

# ── Vision Post-Processor ─────────────────────────────────
def _extract_screenshot_from_tool_results(messages: list[BaseMessage]) -> str | None:
    """
    Scans the most recent ToolMessage for a screenshot_base64 field.
    If found, extracts and returns it (removing it from the text payload
    to avoid sending a giant base64 blob as text to the LLM).
    """
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            content = msg.content
            
            # ToolNode may serialize as str or keep as dict
            data = None
            if isinstance(content, str) and "screenshot_base64" in content:
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(content, dict):
                data = content
            
            if not data:
                break
                
            # Deep search for the screenshot key
            screenshot = None
            if isinstance(data, dict):
                screenshot = data.get("screenshot_base64")
                if not screenshot and isinstance(data.get("data"), dict):
                    screenshot = data["data"].get("screenshot_base64")
            
            if screenshot and len(screenshot) > 100:  # sanity check: real b64 is large
                # Remove screenshot from text to save tokens
                def _strip_screenshot(d):
                    if isinstance(d, dict):
                        for k in list(d.keys()):
                            if k == "screenshot_base64":
                                d[k] = "[SCREENSHOT - sent as image]"
                            elif isinstance(d[k], dict):
                                _strip_screenshot(d[k])
                
                _strip_screenshot(data)
                
                if isinstance(content, str):
                    msg.content = json.dumps(data)
                else:
                    msg.content = data
                
                print(f"[Vision] Extracted screenshot from tool result ({len(screenshot)} chars base64)")
                return screenshot
            
            break  # Only check the most recent ToolMessage
    return None

def _prune_old_images(messages: list[BaseMessage], keep_count: int = 2):
    """
    Finds all messages with image blocks and keeps only the most recent N.
    Strips image blocks from older messages to satisfy model limits (e.g. 3-image limit).
    """
    image_indices = []
    for i, msg in enumerate(messages):
        if hasattr(msg, "content") and isinstance(msg.content, list):
            if any(isinstance(block, dict) and block.get("type") == "image" for block in msg.content):
                image_indices.append(i)
    
    if len(image_indices) > keep_count:
        to_prune = image_indices[:-keep_count]
        for idx in to_prune:
            msg = messages[idx]
            # Replace list content with just the text part as a plain string
            text_parts = [b.get("text", "") for b in msg.content if isinstance(b, dict) and b.get("type") == "text"]
            msg.content = "".join(text_parts)
            print(f"[Vision] Pruned old image from history at index {idx}, content restored to string")


def clean_messages_for_bedrock(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Ensures conversation history satisfies Bedrock Converse API rules."""
    system_messages = [m for m in messages if isinstance(m, SystemMessage)]
    conv_messages = [m for m in messages if not isinstance(m, SystemMessage)]
    
    # 1. Start with a HumanMessage
    first_user_idx = -1
    for idx, msg in enumerate(conv_messages):
        if isinstance(msg, HumanMessage):
            first_user_idx = idx
            break
            
    if first_user_idx == -1:
        conv_messages = [HumanMessage(content="Hello")] + conv_messages
    elif first_user_idx > 0:
        conv_messages = conv_messages[first_user_idx:]
        
    # 2. Alternate user and assistant, merging consecutive ones of same role
    cleaned = []
    for msg in conv_messages:
        if not cleaned:
            cleaned.append(msg)
            continue
            
        prev = cleaned[-1]
        
        def get_role(m):
            if isinstance(m, HumanMessage):
                return "user"
            if isinstance(m, AIMessage):
                return "assistant"
            if isinstance(m, ToolMessage):
                return "tool"
            return "user"
            
        role_prev = get_role(prev)
        role_curr = get_role(msg)
        
        effective_role_prev = "user" if role_prev in ("user", "tool") else "assistant"
        effective_role_curr = "user" if role_curr in ("user", "tool") else "assistant"
        
        if effective_role_prev == effective_role_curr:
            if role_prev == "user" and role_curr == "user":
                prev.content = str(prev.content) + "\n" + str(msg.content)
            elif role_prev == "assistant" and role_curr == "assistant":
                prev.content = str(prev.content) + "\n" + str(msg.content)
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    prev.tool_calls = (getattr(prev, "tool_calls", []) or []) + msg.tool_calls
            else:
                cleaned.append(msg)
        else:
            cleaned.append(msg)
            
    # 3. Bedrock Converse constraint: AIMessage cannot have both text content AND tool_calls
    for msg in cleaned:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            if msg.content and str(msg.content).strip():
                msg.content = ""
            
    return system_messages + cleaned


# ── Sliding Window for Message History ────────────────────
def _apply_sliding_window(messages: list[BaseMessage], tool_history: list[dict], window_size: int = CONTEXT_WINDOW_SIZE) -> list[BaseMessage]:
    """
    Compresses message history by keeping only the most recent `window_size` AI+Tool
    exchange pairs in full detail. Older exchanges are summarized into a compact
    HumanMessage to preserve context without blowing up token counts.
    
    Always preserves: SystemMessage(s) at the start, the original HumanMessage (goal).
    """
    # Separate system messages and conversation messages
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    conv_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
    
    if not conv_msgs:
        return messages
    
    # The first HumanMessage is the original goal — always keep it
    goal_msg = None
    goal_idx = -1
    for i, m in enumerate(conv_msgs):
        if isinstance(m, HumanMessage):
            goal_msg = m
            goal_idx = i
            break
    
    if goal_msg is None:
        return messages  # No goal found, don't apply window
    
    # Everything after the goal is the ReAct loop (AI → Tool → AI → Tool → ...)
    react_messages = conv_msgs[goal_idx + 1:]
    
    # Count AI messages to determine how many exchanges we have
    ai_indices = [i for i, m in enumerate(react_messages) if isinstance(m, AIMessage)]
    
    # If we have fewer exchanges than the window size, no compression needed
    if len(ai_indices) <= window_size:
        return messages
    
    # Split: old exchanges (to summarize) vs recent exchanges (to keep)
    cutoff_ai_idx = ai_indices[-window_size]  # Index of the first AI message to KEEP
    old_messages = react_messages[:cutoff_ai_idx]
    recent_messages = react_messages[cutoff_ai_idx:]
    
    # Build a compact summary from tool_history for the old iterations
    summary_lines = []
    summarized_count = 0
    for record in tool_history:
        if record.get("phase") == "result":
            tool_name = record.get("tool", "unknown")
            success = "ok" if record.get("success") else "failed"
            error = record.get("error", "")
            if tool_name == "browser_observe":
                summary_lines.append(f"  {success} Observed page")
            elif tool_name == "browser_interact":
                summary_lines.append(f"  {success} Interacted with element")
            elif tool_name == "browser_open_url":
                summary_lines.append(f"  {success} Navigated to URL")
            else:
                error_suffix = f" ({error})" if error else ""
                summary_lines.append(f"  {success} {tool_name}{error_suffix}")
            summarized_count += 1
            # Only summarize enough to cover the old messages
            if summarized_count >= len(old_messages) // 2:
                break
    
    if summary_lines:
        summary_text = (
            f"[Progress Summary - Iterations 1-{len(ai_indices) - window_size}]\n"
            + "\n".join(summary_lines[-20:])  # Cap at 20 lines
            + "\n[End Summary — detailed history follows below]"
        )
    else:
        summary_text = (
            f"[Progress Summary] Completed {len(ai_indices) - window_size} prior iterations. "
            "See tool_history for details."
        )
    
    summary_msg = HumanMessage(content=summary_text)
    
    compressed = system_msgs + [goal_msg, summary_msg] + recent_messages
    print(f"[SlidingWindow] Compressed {len(messages)} messages -> {len(compressed)} (dropped {len(old_messages)} old exchange messages)")
    return compressed


def _build_progress_injection(task_progress: list[str]) -> str:
    """Build a concise progress status string to inject into agent context."""
    if not task_progress:
        return ""
    return "[Task Progress] " + " | ".join(task_progress)


# ── Graph Builder ─────────────────────────────────────────
def build_master_graph():
    """Compiles the ReAct StateGraph with LLM caching, vision, and error resilience."""
    
    # ToolNode with error recovery — tool exceptions are sent back to the LLM
    # as error messages instead of crashing the entire graph
    tool_node = ToolNode(ALL_TOOLS, handle_tool_errors=True)
    
    async def call_model(state: AgentState, config: RunnableConfig):
        # 1. Dynamic Model Routing via config
        model_id = config.get("configurable", {}).get(
            "model_id", 
            os.getenv("CLAUDE_MODEL_ID", "us.amazon.nova-pro-v1:0")
        )
        region = os.getenv("AWS_BEDROCK_REGION", "us-east-1")
        
        messages = [_clone_message(m) for m in state['messages']]
        updated_messages_for_state = []
        
        # ── Sliding Window: Compress old message history ──
        tool_history = list(state.get("tool_history") or [])
        messages = _apply_sliding_window(messages, tool_history)
        
        # ── Task Progress Injection ──
        # Inject progress into the SystemMessage so it doesn't disrupt turn structure
        task_progress = list(state.get("task_progress") or [])
        progress_text = _build_progress_injection(task_progress)
        if progress_text:
            for msg in messages:
                if isinstance(msg, SystemMessage):
                    msg.content = str(msg.content) + "\n\n" + progress_text
                    print(f"[TaskProgress] Injected into system prompt: {progress_text}")
                    break
        
        # 2. Vision Check: If history has images, we MUST use a vision-capable model
        vision_model_id = os.getenv("CLAUDE_MODEL_ID", "us.amazon.nova-pro-v1:0")
        has_images = False
        for m in messages:
            if hasattr(m, "content") and isinstance(m.content, list):
                if any(isinstance(block, dict) and block.get("type") == "image" for block in m.content):
                    has_images = True
                    break
        
        if has_images and not _is_vision_capable(model_id):
            print(f"[Vision] {model_id} is text-only and history has images — switching to {vision_model_id}")
            model_id = vision_model_id

        # 3. Cached LLM instance
        llm = _get_llm(model_id, region)
        
        # ── Dynamic Tool Binding by Context ──
        active_tools = list(ALL_TOOLS)
        if state.get("file_write_completed"):
            active_tools = [t for t in active_tools if not t.name.startswith("browser_")]
            print(f"[DynTools] File written — stripped browser tools ({len(active_tools)} remaining)")
            
        tool_history = state.get("tool_history") or []
        last_action = None
        for record in reversed(tool_history):
            if record.get("phase") == "result":
                last_action = record.get("tool")
                break
        if last_action == "browser_observe":
            active_tools = [t for t in active_tools if t.name != "file_search"]
            print(f"[DynTools] Last action was browser_observe — stripped file_search ({len(active_tools)} remaining)")

        # ── Route-scoped MCP binding ──
        # Keep MCP tools only on routes where they help (web tools on browser/
        # mission, fs tools on tool/mission). Native tools are never touched.
        route = config.get("configurable", {}).get("route", "") or ""
        before_scope = len(active_tools)
        active_tools = _scope_mcp_tools_by_route(active_tools, route)
        if len(active_tools) != before_scope:
            print(f"[DynTools] Route '{route}' — scoped MCP tools "
                  f"({before_scope - len(active_tools)} dropped, {len(active_tools)} bound)")

        bound_llm = llm.bind_tools(active_tools)
        
        # 4. Prune old images to stay under model limits (e.g. Bedrock max 3)
        _prune_old_images(messages, keep_count=2)
        
        # 5. Iteration tracking
        iteration = state.get("iteration", 0) + 1
        print(f"[Graph] Iteration: {iteration}")
        with open(r"c:\Users\Rudra\holo-core-nexus\backend\data\graph_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- Iteration {iteration} ---\n")
            if messages and isinstance(messages[-1], ToolMessage):
                f.write(f"Tool Result: {messages[-1].content[:500]}\n")
        
        # 5. Vision: Extract screenshot from the latest tool result
        screenshot_b64 = _extract_screenshot_from_tool_results(messages)
        if screenshot_b64:
            # Only swap to the fallback vision model if the current model can't see.
            # A vision-capable agent (Claude Sonnet) keeps handling its own screenshots.
            if not _is_vision_capable(model_id):
                model_id = vision_model_id
                llm = _get_llm(model_id, region)
                bound_llm = llm.bind_tools(active_tools)
            
            # Inject multimodal content DIRECTLY into the ToolMessage to satisfy Bedrock's turn rules.
            # Find the most recent ToolMessage
            for msg in reversed(messages):
                if isinstance(msg, ToolMessage):
                    original_text = msg.content
                    msg.content = [
                        {"type": "text", "text": str(original_text)},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64
                            }
                        }
                    ]
                    print(f"[Vision] Injected screenshot into ToolMessage -> using {model_id}")
                    # CRITICAL: We must return the stripped ToolMessage to the state
                    # so LangGraph's add_messages can update the original message in history
                    # and prevent base64 bloat in future turns.
                    updated_messages_for_state.append(msg)
                    break
        
        # Clean messages for Bedrock Converse API constraints (e.g. must start with user, alternate turns)
        cleaned_messages = clean_messages_for_bedrock(messages)
        
        # ── Bedrock ValidationException Retry ──
        # If Bedrock rejects the message structure, strip all images and retry once
        try:
            response = await bound_llm.ainvoke(cleaned_messages)
        except Exception as e:
            if "ValidationException" in str(e):
                print(f"[Graph] Bedrock ValidationException — retrying with text-only messages")
                for msg in cleaned_messages:
                    if hasattr(msg, "content") and isinstance(msg.content, list):
                        text_parts = [b.get("text", "") for b in msg.content if isinstance(b, dict) and b.get("type") == "text"]
                        msg.content = "".join(text_parts) or str(msg.content)
                response = await bound_llm.ainvoke(cleaned_messages)
            else:
                raise
                
        # Accumulate and record token usage
        usage = _extract_token_usage(response)
        current_usage = dict(state.get("token_usage") or {"input": 0, "output": 0, "total": 0})
        current_usage["input"] += usage["input"]
        current_usage["output"] += usage["output"]
        current_usage["total"] = current_usage["input"] + current_usage["output"]
        
        await _emit_graph_event("agent.token_usage", {
            "iteration": iteration,
            "session_tokens": current_usage,
            "step_tokens": usage
        })
        
        # 5. Llama Tool Call Interceptor (catches ALL hallucination formats)
        #    Llama outputs tool calls inconsistently:
        #      Format A: {"name": "browser_observe", "parameters": {}}
        #      Format B: browser_observe()
        #      Format C: browser_interact(element_id=5, action="click")
        #    We catch all of them and convert to native LangChain ToolCalls.
        if not response.tool_calls and isinstance(response.content, str):
            tool_names = [t.name for t in ALL_TOOLS]
            parsed_calls = []
            
            # Strategy 1: JSON format (handles optional "type" key)
            json_matches = re.findall(
                r'"name"\s*:\s*"([^"]+)"\s*,\s*"parameters"\s*:\s*(\{.*?\})',
                response.content,
                re.DOTALL
            )
            for name, params_str in json_matches:
                if name in tool_names:
                    try:
                        args = json.loads(params_str)
                        parsed_calls.append({"name": name, "args": args})
                    except json.JSONDecodeError:
                        pass
            
            # Strategy 2: Python-style function calls: tool_name(arg=val, ...)
            #   OR positional: tool_name("value")  <-- Llama frequently narrates this
            #   form, e.g. browser_open_url("https://..."). The old code only parsed
            #   keyword args, so positional calls produced EMPTY args and the action
            #   never executed (agent stalled on its own narration). Map a lone
            #   positional value onto each tool's primary parameter.
            _PRIMARY_PARAM = {
                "browser_open_url": "url",
                "browser_search": "query",
                "browser_scroll": "direction",
                "browser_select_date": "date",
                "file_read": "path",
                "file_list": "path",
                "file_search": "query",
                "weather_check": "location",
                "whatsapp_check_messages": None,
            }
            if not parsed_calls:
                pattern = r'(' + '|'.join(re.escape(n) for n in tool_names) + r')\s*\(([^)]*)\)'
                py_matches = re.findall(pattern, response.content)
                for name, args_str in py_matches:
                    args = {}
                    if args_str.strip():
                        kv_pairs = re.findall(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\d+))', args_str)
                        for key, str_val, str_val2, int_val in kv_pairs:
                            if int_val and not (str_val or str_val2):
                                args[key] = int(int_val)
                            else:
                                args[key] = str_val or str_val2
                        # Positional fallback: tool("value") with no key=value pairs.
                        if not args:
                            prim = _PRIMARY_PARAM.get(name)
                            if prim:
                                pm = re.search(r'''["']([^"']+)["']''', args_str)
                                if not pm:  # bare token, e.g. browser_scroll(down)
                                    pm = re.search(r'([^\s,()"\']+)', args_str)
                                if pm:
                                    args[prim] = pm.group(1)
                    parsed_calls.append({"name": name, "args": args})
            
            # Apply only the FIRST parsed call to enforce step-by-step ReAct loop
            if parsed_calls:
                call = parsed_calls[0]
                response.tool_calls.append({
                    "name": call["name"],
                    "args": call["args"],
                    "id": f"call_{uuid.uuid4().hex[:10]}"
                })
                print(f"[Interceptor] Parsed tool call: {call['name']}({call['args']})")
                if len(parsed_calls) > 1:
                    print(f"[Interceptor] Ignored {len(parsed_calls) - 1} additional tool calls to enforce sequential observation.")
                
                # Bedrock Converse API forbids text + tool_calls in the same message
                response.content = ""

        if getattr(response, "tool_calls", None) and len(response.tool_calls) > 1:
            ignored = len(response.tool_calls) - 1
            response.tool_calls = response.tool_calls[:1]
            await _emit_graph_event(
                "tool.calls_pruned",
                {"iteration": iteration, "ignored": ignored, "reason": "sequential_react_enforced"},
            )

        if getattr(response, "tool_calls", None):
            call = response.tool_calls[0]
            await _emit_graph_event(
                "agent.tool_requested",
                {
                    "iteration": iteration,
                    "tool": _tool_call_name(call),
                    "arguments": _tool_call_args(call),
                },
            )
                
        # ── Stale Loop Recovery ──
        # Track consecutive no-tool iterations and inject a nudge if the agent is stalling
        stale_count = state.get("stale_iterations", 0)
        has_tool_calls = bool(getattr(response, "tool_calls", None))
        
        if has_tool_calls:
            # Agent produced a tool call — reset stale counter
            stale_count = 0
        else:
            stale_count += 1

            # ── Anti-Confabulation Guard ──
            # The agent is delivering a FINAL answer (no tool calls). If it never ran a
            # single tool this run yet asserts verifiable specifics (prices, costs,
            # "verified"), it is fabricating from memory. Replace with an honest reply
            # instead of letting invented figures reach the user.
            ran_a_tool = any(isinstance(m, ToolMessage) for m in messages)
            content_str = response.content if isinstance(response.content, str) else ""
            asserts_specifics = bool(content_str) and (
                any(sym in content_str for sym in ("₹", "$", "€", "£"))
                or any(k in content_str.lower() for k in (
                    "verified", "priced at", "price is", "total cost", "per night",
                    "per person", "approximately", " inr", " usd", "rs.", "rupees",
                ))
            )
            if not ran_a_tool and asserts_specifics:
                print("[AntiConfab] Final answer asserts specifics but NO tool ran this turn — "
                      "replacing ungrounded content with an honest disclaimer.")
                try:
                    with open(r"c:\Users\Rudra\holo-core-nexus\backend\data\graph_debug.log", "a", encoding="utf-8") as f:
                        f.write(f"[AntiConfab] Blocked ungrounded claim: {content_str[:200]}\n")
                except Exception:
                    pass
                response.content = (
                    "Sir, I wasn't able to verify this from a live source just now, so I'd rather "
                    "not quote specifics I can't stand behind. Shall I open a particular website to "
                    "check, or would you like general suggestions clearly marked as unverified?"
                )

            if stale_count == 2:
                # Detection only — do NOT append a nudge to response.content. This turn has no
                # tool calls, so should_continue() ends the graph and response.content becomes the
                # user-facing answer (and TTS input); appending text here leaked it into the reply.
                print(f"[StaleRecovery] Agent produced no tool call for {stale_count} consecutive turns")
                     
        with open(r"c:\Users\Rudra\holo-core-nexus\backend\data\graph_debug.log", "a", encoding="utf-8") as f:
            f.write(f"Response: {response}\n")
                    
        return {
            "messages": updated_messages_for_state + [response],
            "iteration": iteration,
            "stale_iterations": stale_count,
            "token_usage": current_usage
        }

    async def guard_tool_call(state: AgentState) -> AgentState:
        messages = state.get("messages", [])
        last_message = messages[-1] if messages else None
        tool_calls = list(getattr(last_message, "tool_calls", []) or [])
        if not tool_calls:
            return {"blocked_tool_call": False}

        if len(tool_calls) > 1 and hasattr(last_message, "tool_calls"):
            last_message.tool_calls = tool_calls[:1]
            tool_calls = tool_calls[:1]

        call = tool_calls[0]
        name = _tool_call_name(call)
        args = _tool_call_args(call)
        call_id = _tool_call_id(call)
        signature = _tool_signature(call, state)
        confidence, reason = _score_tool_call(call, state)
        loop_signatures = dict(state.get("loop_signatures") or {})
        seen_count = loop_signatures.get(signature, 0)
        blocked_reason = ""

        if confidence < MIN_TOOL_CONFIDENCE:
            blocked_reason = reason
        elif seen_count >= (2 if name in _RETRYABLE_TOOLS else 1):
            blocked_reason = "repeated_tool_call_without_progress"

        event_payload = {
            "tool": name,
            "arguments": args,
            "confidence": round(confidence, 2),
            "reason": reason,
            "signature": signature,
            "repeat_count": seen_count,
        }

        history_item = {
            **event_payload,
            "phase": "guard",
            "timestamp": time.time(),
            "blocked": bool(blocked_reason),
        }
        tool_history = list(state.get("tool_history") or [])[-30:] + [history_item]

        if blocked_reason:
            await _emit_graph_event(
                "tool.blocked",
                {**event_payload, "blocked_reason": blocked_reason},
                level="warning",
            )
            tool_message = ToolMessage(
                content=json.dumps({
                    "success": False,
                    "action": "tool_guard",
                    "observation": (
                        f"Tool call '{name}' was blocked: {blocked_reason}. "
                        "Choose a grounded alternate action, observe again, ask for clarification, or finalize with partial progress."
                    ),
                    "data": {
                        "tool": name,
                        "arguments": args,
                        "confidence": round(confidence, 2),
                        "reason": blocked_reason,
                    },
                    "error": blocked_reason,
                }),
                tool_call_id=call_id,
                name=name,
            )
            return {
                "messages": [tool_message],
                "blocked_tool_call": True,
                "tool_history": tool_history,
            }

        loop_signatures[signature] = seen_count + 1
        await _emit_graph_event("tool.approved", event_payload)
        return {
            "blocked_tool_call": False,
            "tool_history": tool_history,
            "loop_signatures": loop_signatures,
        }

    async def record_tool_result(state: AgentState) -> AgentState:
        messages = state.get("messages", [])
        latest_tool_messages = []
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                latest_tool_messages.append(msg)
            else:
                break
        if not latest_tool_messages:
            return {"blocked_tool_call": False}

        latest_tool_messages.reverse()
        updates: dict[str, Any] = {"blocked_tool_call": False}
        tool_failures = dict(state.get("tool_failures") or {})
        tool_history = list(state.get("tool_history") or [])[-30:]

        for msg in latest_tool_messages:
            payload = _parse_tool_payload(msg.content)
            action = str(payload.get("action") or getattr(msg, "name", "") or "unknown")
            success = bool(payload.get("success", False))
            if not success and action in ["file_write", "write_file"] and isinstance(msg.content, str):
                if "successfully" in msg.content.lower() or "certainly, sir." in msg.content.lower():
                    success = True
            if not success:
                failure_key = action or "unknown"
                tool_failures[failure_key] = tool_failures.get(failure_key, 0) + 1

            result_record = {
                "phase": "result",
                "tool": action,
                "success": success,
                "error": payload.get("error"),
                "timestamp": time.time(),
            }
            tool_history.append(result_record)

            if action == "browser_observe" and isinstance(payload.get("data"), dict):
                data = dict(payload["data"])
                fingerprint = data.get("page_fingerprint") or _page_fingerprint(data)
                observation_id = data.get("observation_id") or hashlib.sha256(
                    f"{fingerprint}:{time.time()}".encode("utf-8")
                ).hexdigest()[:12]
                elements = data.get("interactive_elements") or []
                element_ids = [
                    item.get("id")
                    for item in elements
                    if isinstance(item, dict) and item.get("id") is not None
                ]
                registry_snapshot = {
                    str(item.get("id")): item
                    for item in elements
                    if isinstance(item, dict) and item.get("id") is not None
                }
                updates.update({
                    "last_observation": data,
                    "last_observation_id": observation_id,
                    "last_page_fingerprint": fingerprint,
                    "last_element_ids": element_ids,
                    "interactive_registry": registry_snapshot,
                })

            await _emit_graph_event(
                "tool.result_recorded",
                {
                    "tool": action,
                    "success": success,
                    "error": payload.get("error"),
                    "observation_id": updates.get("last_observation_id"),
                },
                level="info" if success else "warning",
            )

            # ── Task Progress Tracking ──
            # When a browser_interact click succeeds, record a progress entry
            # based on the action context (e.g. "Added bananas to cart")
            if action == "interact_by_id" and success:
                interact_data = payload.get("data") or {}
                element_id = interact_data.get("element_id", "?")
                interact_action = interact_data.get("action", "")
                if interact_action == "click":
                    # Try to extract what was clicked from the observation text
                    before_title = interact_data.get("before_title", "")
                    after_title = interact_data.get("after_title", "")
                    url_changed = interact_data.get("url_changed", False)
                    progress_entry = f"Clicked element #{element_id}"
                    if url_changed and after_title:
                        progress_entry += f" -> {after_title[:50]}"
                    progress_entry = _safe_console_text(progress_entry)
                    task_progress = list(state.get("task_progress") or [])
                    task_progress.append(progress_entry)
                    # Keep only the last 20 entries to prevent bloat
                    updates["task_progress"] = task_progress[-20:]
                    print(f"[TaskProgress] Recorded: {progress_entry}")

            # ── File Write Completion Tracking ──
            # When file_write succeeds, mark the task as having produced output.
            # This signals should_continue to allow the agent to wrap up.
            if action == "file_write" and success:
                file_path = (payload.get("data") or {}).get("path", "unknown")
                task_progress = list(updates.get("task_progress") or state.get("task_progress") or [])
                task_progress.append(f"Wrote file: {file_path}")
                updates["task_progress"] = task_progress[-20:]
                updates["file_write_completed"] = True
                print(f"[TaskProgress] File write completed: {file_path}; agent will wrap up")

        updates["tool_history"] = tool_history[-40:]
        updates["tool_failures"] = tool_failures
        return updates

    async def loop_halt(state: AgentState) -> AgentState:
        token_usage = state.get("token_usage") or {}
        total_tokens = token_usage.get("total", 0)
        token_budget = state.get("token_budget", int(os.getenv("JARVIS_TOKEN_BUDGET", "200000")))
        is_budget_exceeded = total_tokens > token_budget
        reason = "token_budget_exceeded" if is_budget_exceeded else "max_iterations_reached"
        
        await _emit_graph_event(
            "agent.loop_halted",
            {
                "iteration": state.get("iteration", 0),
                "max_iterations": MAX_AGENT_ITERATIONS,
                "reason": reason,
                "token_usage": token_usage,
                "token_budget": token_budget,
                "tool_history": state.get("tool_history", [])[-6:],
            },
            level="warning",
        )
        
        if is_budget_exceeded:
            content = (
                f"I stopped the task because the token budget was exceeded ({total_tokens}/{token_budget} tokens). "
                "This prevents runaway API costs. Please refine the goal or increase the budget to continue."
            )
            final_status = "budget_exceeded"
        else:
            content = (
                "I stopped the task before it could loop further. "
                "I could not verify enough progress to continue safely."
            )
            final_status = "loop_halted"
            
        return {
            "messages": [
                AIMessage(content=content)
            ],
            "final_status": final_status,
        }

    async def handle_intent_retry(state: AgentState) -> AgentState:
        from langchain_core.messages import HumanMessage
        print(f"[Graph] Appending retry message to force tool call execution and keep user/assistant message structure alternating")
        # Grounded-evidence nudge: a browser task must back every fact with an observation.
        if os.getenv("JARVIS_GROUNDED_ANSWERS", "false").lower() in {"1", "true", "yes", "on"} and _used_browser(state):
            return {
                "messages": [
                    HumanMessage(
                        content=(
                            "Do not state any price, number, or fact unless it appears in a page you actually "
                            "read with browser_observe. If you have not read it on the page yet, use "
                            "browser_open_url to open the real site and browser_observe first. If you still "
                            "cannot verify it, say so plainly instead of guessing."
                        )
                    )
                ]
            }
        missing_research = _missing_required_research_terms(state)
        if missing_research:
            terms = ", ".join(missing_research)
            return {
                "messages": [
                    HumanMessage(
                        content=(
                            f"Do not ask the user for permission yet. You still need to research: {terms}. "
                            f"Use browser_open_url or browser_interact to search the web for {terms} quarterly revenue, "
                            "then observe the results. Only write the output file after every required company has been researched."
                        )
                    )
                ]
            }
        return {
            "messages": [
                HumanMessage(
                    content="Please execute the tool call you just described. Remember to output a valid tool call in JSON format."
                )
            ]
        }
        
    # Build Graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tool_guard", guard_tool_call)
    workflow.add_node("tools", tool_node)
    workflow.add_node("record_tools", record_tool_result)
    workflow.add_node("loop_halt", loop_halt)
    workflow.add_node("intent_retry", handle_intent_retry)
    
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, {"tool_guard": "tool_guard", "loop_halt": "loop_halt", "retry": "intent_retry", END: END})
    workflow.add_conditional_edges("tool_guard", _route_after_tool_guard, ["tools", "agent"])
    workflow.add_edge("tools", "record_tools")
    workflow.add_edge("record_tools", "agent")
    workflow.add_edge("loop_halt", END)
    workflow.add_edge("intent_retry", "agent")
    
    # Async graph invocations cannot use the sync SqliteSaver checkpointer.
    # Keep checkpoints opt-in until the async sqlite saver is wired in.
    if os.getenv("JARVIS_GRAPH_CHECKPOINTS", "").lower() in {"1", "true", "yes", "on"}:
        db_path = os.getenv("JARVIS_GRAPH_DB")
        if not db_path:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            db_dir = os.path.abspath(os.path.join(current_dir, "..", "db"))
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "jarvis_graph.db")

        conn = sqlite3.connect(db_path, check_same_thread=False)
        memory = SqliteSaver(conn)
        app = workflow.compile(checkpointer=memory)
    else:
        app = workflow.compile()
    return app

# Singleton graph instance
# NOTE: Single-user system. Concurrent requests share the same browser session.
master_graph_app = build_master_graph()
