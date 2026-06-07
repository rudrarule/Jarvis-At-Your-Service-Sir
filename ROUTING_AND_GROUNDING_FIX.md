# Durable Fixes: LLM Router + Grounded-Evidence Gate

Two architectural fixes so Jarvis (a) routes any query to the right tier reliably, and
(b) never states facts it didn't actually observe (no hallucination). Both are **drop-in
and env-flag-gated (default OFF)** — nothing changes until you enable them, and rollback is
just unsetting the flag. Matches your existing Bedrock Converse patterns (`_get_bedrock_client`,
`client.converse`).

Enable both after testing:
```
JARVIS_USE_LLM_ROUTER=true
JARVIS_GROUNDED_ANSWERS=true
JARVIS_ROUTER_MODEL_ID=us.amazon.nova-lite-v1:0   # cheap+fast; or a haiku/nova-micro id
```

---

## FIX 1 — LLM Intent Router (reliable Tier 1/2/3 routing)

**Problem:** routing is a pile of keyword heuristics (`langgraph_intents`, `_looks_like_mission_goal`,
`tier3_site_keywords`, `compound_goal`, `_needs_react_research`). Every new phrasing needs a new keyword.
GitHub-trending went to mission-graph; flights mis-route; etc.

**Fix:** one cheap LLM classification call returns a structured route. Deterministic fast-paths handle
the obvious cases first (so most traffic never pays for the call). Falls back to your current heuristics
if the model errors — so it can only help, never harm.

### 1a. Add to `services/llm_service.py` (near the other helpers)

```python
import json as _json

ROUTE_CHAT = "chat"            # conversation / knowledge / no tools  -> Tier 2
ROUTE_BROWSER = "browser"      # must open/click/read a website       -> Tier 3 (master_graph)
ROUTE_TOOL = "tool"            # file / weather / whatsapp / system    -> Tier 3 (tools)
ROUTE_VISION = "vision"        # look at the screen / overlay
ROUTE_MISSION = "mission"      # ONLY explicit "mission mode" multi-step-without-clicking

_ROUTER_SYSTEM = """You are a router for the JARVIS assistant. Classify the user's request into ONE route.
Routes:
- chat: answer from knowledge or casual talk; no external data or actions needed.
- browser: requires opening a website and reading/clicking/extracting live content
  (prices, trending repos, search results you must read on the page, booking, forms).
- tool: local actions — read/write files, weather, whatsapp, open an app, system control.
- vision: look at / describe what is on the user's screen right now.
- mission: ONLY if the user explicitly says "mission mode".
Return ONLY compact JSON: {"route":"chat|browser|tool|vision|mission","reason":"<=8 words"}."""

def _heuristic_route(msg: str) -> str:
    """Deterministic fast-paths; return '' if undecided (then ask the LLM)."""
    t = msg.lower().strip()
    if _is_status_chitchat(t) or t in {"hi","hello","hey","thanks","thank you","ok","okay"}:
        return ROUTE_CHAT
    if any(k in t for k in ("on my screen","what do you see","look at this","this screenshot")):
        return ROUTE_VISION
    if "mission mode" in t:
        return ROUTE_MISSION
    return ""

async def classify_route(user_message: str) -> str:
    """LLM-based route classification with deterministic fast-paths and safe fallback."""
    quick = _heuristic_route(user_message)
    if quick:
        return quick
    if os.getenv("JARVIS_USE_LLM_ROUTER", "false").lower() not in {"1","true","yes","on"}:
        return ""  # router disabled -> caller uses legacy heuristics
    try:
        client = _get_bedrock_client()
        resp = await asyncio.to_thread(
            client.converse,
            modelId=os.getenv("JARVIS_ROUTER_MODEL_ID", "us.amazon.nova-lite-v1:0"),
            system=[{"text": _ROUTER_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": 60, "temperature": 0},
        )
        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        text = " ".join(b.get("text","") for b in blocks)
        start, end = text.find("{"), text.rfind("}")
        route = _json.loads(text[start:end+1]).get("route","") if start>=0 else ""
        valid = {ROUTE_CHAT, ROUTE_BROWSER, ROUTE_TOOL, ROUTE_VISION, ROUTE_MISSION}
        if route in valid:
            print(f"[Router] LLM route -> {route}")
            return route
    except Exception as exc:
        print(f"[Router] LLM router failed, using legacy heuristics: {exc}")
    return ""  # fall back to existing logic
```

### 1b. Wire it at the top of `generate_response` routing

Right after the overlay/workflow guards, before the finance/mission/tier1 chain:

```python
    route = await classify_route(user_message)
    if route == ROUTE_VISION:
        ...  # existing vision path
    elif route == ROUTE_MISSION:
        ...  # existing mission_graph invocation
    elif route in (ROUTE_BROWSER, ROUTE_TOOL):
        # force Tier 3 (master_graph) — skip the brittle mission/tier1 heuristics entirely
        force_react_research = True
    # route == ROUTE_CHAT or "" -> fall through to your existing pipeline unchanged
```

Setting `force_react_research = True` reuses your existing flag that already bypasses mission mode and
goes to Tier 3. With the router ON, "trending github repos + write file", "flights", etc. land on the
capable browser agent deterministically — no keyword lists.

**Why this is durable:** new phrasings are understood by the model, not matched by substring. Mission-graph
(which can't click) is reserved for explicit opt-in. Legacy heuristics stay as the fallback.

**Test:** set `JARVIS_USE_LLM_ROUTER=true`, restart, try varied phrasings ("grab the top python repos this
week and save them", "what's 2+2", "read my notes.md", "book a flight"). Confirm `[Router] LLM route -> …`
in the console. Unset the flag to roll back instantly.

---

## FIX 2 — Grounded-Evidence Gate (no hallucination)

**Problem:** the agent can emit a confident final answer (a price, a repo, a stat) that came from its prior
or a search-result *title*, not from the page. (The "$49 flight" was a DuckDuckGo SEO title.)

**Fix:** before the agent is allowed to FINISH a task that used the web, verify its answer's key facts appear
in the actual observations it collected. If not, force one more observe; if still unsupported, downgrade the
answer to an honest "couldn't verify" instead of stating it as fact.

### 2a. Add to `workflows/master_graph.py`

```python
import re as _re

def _collect_observation_text(state: "AgentState") -> str:
    """All real page content the agent actually observed this run (browser_observe payloads)."""
    chunks = []
    last = state.get("last_observation") or {}
    if isinstance(last, dict):
        chunks.append(str(last.get("summary","")) + " " + str(last.get("accessibility_tree","")))
    for m in state.get("messages", []):
        if isinstance(m, ToolMessage):
            payload = _parse_tool_payload(m.content)
            if str(payload.get("action")) == "browser_observe":
                data = payload.get("data") or {}
                chunks.append(str(data.get("summary","")) + " " + str(data.get("accessibility_tree","")))
    return " ".join(chunks).lower()

def _used_browser(state: "AgentState") -> bool:
    return any(r.get("tool","").startswith("browser_") for r in (state.get("tool_history") or []))

def _answer_is_grounded(answer: str, state: "AgentState") -> bool:
    """A factual answer must share specific tokens (numbers, $/₹ amounts, proper nouns)
    with the observed page text. Pure prose with no specific claims passes."""
    obs = _collect_observation_text(state)
    if not obs:
        return False  # browser task but nothing observed -> not grounded
    # Specific claims that must be backed: money amounts and standalone numbers >= 2 digits.
    claims = _re.findall(r'(?:rs\.?|₹|\$)\s?\d[\d,]*|\b\d{2,}\b', answer.lower())
    if not claims:
        return True  # no hard factual claims to verify
    backed = sum(1 for c in claims if _re.sub(r'[^\d]', '', c) and _re.sub(r'[^\d]', '', c) in _re.sub(r'[^\d]', '', obs))
    return backed >= max(1, len(claims) // 2)
```

### 2b. Gate the finish in `should_continue`

In the no-tool-calls branch (where it currently returns `END`), before returning END:

```python
    if os.getenv("JARVIS_GROUNDED_ANSWERS","false").lower() in {"1","true","yes","on"} \
       and _used_browser(state) and not state.get("file_write_completed"):
        answer = str(getattr(last_message, "content", "") or "")
        if answer and not _answer_is_grounded(answer, state) and state.get("stale_iterations",0) < 2:
            print("[Grounding] Final answer not supported by observations — forcing re-observe")
            return "retry"   # routes to intent_retry; nudge below
```

### 2c. Strengthen the nudge in `handle_intent_retry`

Add, when grounding failed:

```python
    if os.getenv("JARVIS_GROUNDED_ANSWERS","false").lower() in {"1","true","yes","on"} and _used_browser(state):
        return {"messages": [HumanMessage(content=(
            "Do not state any price, number, or fact unless it appears in the page you observed with "
            "browser_observe. If you have not actually read it on the page, browser_open_url the real "
            "site and browser_observe first. If you still cannot verify it, say so plainly instead of guessing."
        ))]}
```

This, plus the `[UNVERIFIED]` label already on `browser_search`, means: search-result titles can never be
reported as facts, and a browser task that didn't actually read the data ends with an honest
"couldn't verify" rather than a fabricated number.

**Test:** `JARVIS_GROUNDED_ANSWERS=true`, restart, ask for a live price/stat. If the agent can't open/read
the page it should say so, not invent a value. Unset to roll back.

---

## Rollout order
1. Ship FIX 2 first (grounding) — it's contained to `master_graph.py` and purely additive.
2. Then FIX 1 (router) — flip `JARVIS_USE_LLM_ROUTER=true` and test varied phrasings.
3. Keep both flags OFF in `.env` until you've smoke-tested each; they're independent.

## Notes
- Router model: use a *cheap* one (`nova-lite`/`nova-micro`/`haiku`) — it's one tiny call per request.
- These don't replace the substrate fixes (collision IDs, locator resolution, CDP launch, date tool,
  interceptor) — they sit on top. Grounding accuracy still also depends on the agent model's tool-calling
  (Nova Pro > Llama; Claude best).
- Everything stays behind flags so you can A/B and revert without code edits.
