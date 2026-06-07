# J.A.R.V.I.S Browser-Agent Debugging — Handoff Summary

Self-contained context for continuing this work. Repo root: `C:\Users\Rudra\holo-core-nexus`.

## 1. Project & goal
Personal "Jarvis" assistant. Python FastAPI backend (`backend/`), React/Vite frontend, exposed via ngrok (`https://wreckage-uneatable-conch.ngrok-free.dev`, tunnels `localhost:8000`). Goal of this session: make **browser automation accurate** (it was clicking wrong elements / hallucinating). Test case throughout: *"find a one-way flight Delhi→Goa, 18 June 2026, cheapest fare."*

## 2. Architecture — the LIVE path (only this matters)
```
frontend → main.py → services/llm_service.py (generate_response)
   → Tier 3 → workflows/master_graph.py (master_graph_app, LangGraph ReAct loop)
   → workflows/tool_wrapper.py (@tool defs, ALL_TOOLS)
   → tools/browser_tool.py (Playwright actions, BrowserStateManager)
   → tools/browser_state.py (ElementRegistry: scan/observe/resolve)
```
- Tier 3 routing in `llm_service.py` ~line 1593: triggers on `langgraph_intents` (search/open/find/weather/etc.) or `is_complex_query`, then calls `master_graph_app.ainvoke(..., config={configurable:{model_id: selected_model}})`.
- `master_graph.call_model` reads `model_id` from config; on tool-call failure it has a **Llama hallucination interceptor** (parses `tool(...)` from prose).
- **NOT live / ignore:** `workflows/v2/*` (planner + browser_agent) and `workflows/mission_graph.py`. Good ideas (date guard, autocomplete follow-up, success-criteria verify) but unwired. Decision: keep master_graph canonical, port v2 tactics as needed.
- Full design rationale in repo: `BROWSER_AGENT_REMEDIATION.md`.

## 3. Root causes diagnosed (with proof)
1. **Browser wouldn't launch** — `BrowserStateManager.get_page` used `launch_persistent_context` (spawns a Chromium subprocess) → Windows `NotImplementedError` when the server's event loop is a SelectorEventLoop (happens under `uvicorn --reload`; `python main.py` sets ProactorEventLoop). Logs showed `NotImplementedError` ×46.
2. **Confabulation** — when browser failed, agent fell back to `browser_search` (DuckDuckGo), which returned an SEO title *"$49 Flights from New Delhi to Goa"*, and the model reported "$49" as a real fare. (Real fare ≈ ₹7,442, verified via Google Flights.)
3. **Stable-ID collisions** — `ElementRegistry._generate_stable_id` hashed only `role:name:tag:selector`, so duplicate elements (e.g. many "Add to cart") collapsed to one entry; indices mis-mapped → clicked wrong element. Reproduced: two distinct buttons → identical `el_02070f0a`.
4. **Fuzzy locator resolution** — `resolve_locator` tried `get_by_role(name=...)` first and picked `.first` visible → wrong sibling. (Live proof: on Skyscanner it clicked the date button instead of the city, picked "Bangkok" instead of Goa, selected June 1 not June 18.)
5. **Observation truncation** — scanned 120 elements but only sent 50 to the LLM.
6. **Model tool-calling unreliability (current blocker)** — Llama 3.3 70B frequently **narrates** ("I will call browser_open_url...") instead of emitting a tool call, so nothing executes and the loop ends IDLE.

## 4. Fixes applied this session (all in repo)
| # | File | Change | Status |
|---|---|---|---|
| Browser launch | `tools/browser_tool.py` `BrowserStateManager` | Added CDP-attach: `_acquire_context` tries `connect_over_cdp(BROWSER_CDP_URL)` before launching; `_launch_persistent_context` re-raises `NotImplementedError` with guidance instead of spawning throwaway profiles; `close_all` won't kill the user's CDP browser | ✅ verified live (browser launches, navigates) |
| URL hygiene | `tools/browser_tool.py` `_sanitize_url_arg` + `open_url` | Extracts the URL token from args like `"https://x.com and tell me..."` | ✅ unit-tested |
| press_enter | `workflows/tool_wrapper.py` `browser_interact` | Coerces string `"false"`→`False` (Llama sends strings) | ✅ |
| #1 collisions | `tools/browser_state.py` | `ElementRegistryEntry` gained `ref/dom_path/dom_index`; scan JS emits `domPath/domIndex`; `_generate_stable_id` now mixes dom_path + bbox bucket; dedup suffix; `_ref_map`; `_observation_id`; `get_by_ref` | ✅ unit-tested (distinct IDs now) |
| #2 resolution | `tools/browser_state.py` `resolve_locator` | Identity-first order (exact selector → dom_path → fallbacks → role+name → text); `_disambiguate` picks match nearest scanned bbox (never blind `.first`); `_dom_path_to_css` | ✅ unit-tested |
| Confabulation guard | `workflows/tool_wrapper.py` `browser_search` | Appends `[UNVERIFIED]` label; docstring says never quote prices from it | ✅ (live run later honestly said "couldn't load" instead of faking) |
| Date picker | `tools/browser_tool.py` `select_calendar_date` + `_parse_date_arg`; `tool_wrapper.py` `browser_select_date` (in `ALL_TOOLS`); prompt section in `llm_service.py` | Deterministic: finds exact day+month+year cell, pages months, refuses wrong date | ✅ unit-tested (matches 18 Jun, rejects Jun 8 / Jun 2025 / Jul 18) |
| Interceptor | `workflows/master_graph.py` call_model | Now parses **positional** tool calls `browser_open_url("url")` (was keyword-only) via `_PRIMARY_PARAM` map → executes instead of stalling | ✅ unit-tested parsing; **runtime effect unconfirmed** |
| Model swap | `llm_service.py` ~1597, `master_graph.py` | Tier 3 model now `os.getenv("JARVIS_AGENT_MODEL_ID", "us.amazon.nova-pro-v1:0")`; added `_is_vision_capable()` so Claude/Nova/Maverick aren't downgraded to the Maverick vision model on screenshots | ✅ edited; **runtime effect unconfirmed** |

## 5. Environment / config (on user's Windows machine)
- `backend/.env`: `BROWSER_CDP_URL=http://localhost:9222`, `BROWSER_HEADLESS=false`, `BROWSER_OBSERVE_SCREENSHOTS=true`, `AWS_BEDROCK_REGION=us-east-1`, `CLAUDE_MODEL_ID=us.meta.llama4-maverick-17b-instruct-v1:0` (this is the Maverick *vision* model — do NOT repurpose).
- New override: `JARVIS_AGENT_MODEL_ID` controls the Tier-3 agent model (default now `us.amazon.nova-pro-v1:0`). Claude Sonnet was attempted but **not available** in their Bedrock account, so they switched to **Amazon Nova Pro**.
- Chrome must run with `--remote-debugging-port=9222 --user-data-dir="C:/jarvis-chrome"` for CDP attach.
- Launch: `start.ps1` runs `python main.py` (ProactorEventLoop ✅) + ngrok. Avoid `startup.bat` (`uvicorn --reload` → SelectorEventLoop → NotImplementedError). A recurring failure was **stale process on port 8000** — must hard-kill before relaunch or new code doesn't load.

## 6. Verified working
- CDP browser launch: `open https://www.skyscanner.co.in/` → `{"success": true, ...navigated...}`. NotImplementedError gone.
- From/To autocomplete fills correctly (user confirmed).
- No more confabulation (honest "couldn't load" instead of fake "$49").
- All grounding fixes unit-tested green.

## 7. OPEN ISSUE — the current blocker
On the full flight query the agent still **narrates the tool call and stops** (e.g. `Executing: browser_open_url("https://www.google.com/flights")` then IDLE) — the browser never opens. The interceptor fix *should* catch that positional call and execute it, but it didn't, which means **either**:
- (most likely) the **Tier-3 Nova call is erroring → falling back to the legacy `_route_hybrid_llm` path**, which narrates but has no interceptor and never drives the browser; or
- the restart loaded **stale `master_graph.py`** (orphan process on port 8000).

## 8. NEXT STEP (do this first)
Need the **backend console** (PowerShell running `python main.py`) — the assistant could not read it (sandbox log mount was frozen all session). After running a flight query, capture the last ~20 lines, looking for:
- `[Tier3] Routing -> us.amazon.nova-pro-v1:0` (did Tier3 run on Nova?)
- `[Graph] Created new LLM instance: ...`
- `[Interceptor] Parsed tool call: ...` (is new interceptor code live?)
- `[Tier3] Falling back to legacy routing...` (← if present, Nova is erroring — prime suspect)
- `ValidationException` / `AccessDenied` / "inference profile" / any Nova error
Or: `Select-String -Path backend\data\graph_debug.log -Pattern "model_name=|Tier3|Falling back|Interceptor|ValidationException" | Select-Object -Last 20`

Then:
- If **falling back / Nova error**: fix the Nova model ID/access (confirm exact inference-profile ID in Bedrock console; ensure `langchain_aws` version supports Nova tool-use via Converse `bind_tools`). Until Tier-3 model calls succeed, no browser fix matters.
- If **stale code**: hard-kill port 8000, relaunch via `python main.py`, retest.
- If Nova confirmed but still narrates: strengthen `handle_intent_retry`/interceptor to force tool-only output, or (best long-term) use a stronger tool-calling model.

## 9. Caveats for the next assistant
- The substrate (launch, grounding, date tool, confabulation guard) is fixed and unit-tested. The remaining problem is **model tool-calling reliability**, not the browser code.
- Don't trust "a response came back" as proof of which model ran — a failed Bedrock call silently falls back to Llama/Ollama. Confirm via `model_name=` in `graph_debug.log` or `[Tier3] Routing` in console.
- Claude Pro (claude.ai) ≠ API access; their Bedrock is the model source. Sonnet unavailable → using Nova Pro.
- `git` is available; consider committing before further changes.
