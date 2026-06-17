"""
llm_service.py — Unified Brain Architecture
=========================================
Tier 1: Regex Fast-Path (0ms)      — instant pattern matching for common commands
Tier 2: Chat Shortcut  (<5s)      — quick conversational responses (no tool schemas)
Tier 3: Unified Tool Router (6-10s)— Qwen-3B handles tools + reasoning in one pass

100% local via Ollama.
"""
import json
import asyncio
import httpx
import re
import os
import time
import uuid

try:
    import boto3
except ImportError:
    boto3 = None

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

from services.memory_service import store_memory, retrieve_memory
from tools.registry import TOOL_SCHEMAS, TOOL_GROUPS, get_schemas_for_intent, execute_tool

# ── Ollama Config ─────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
# Single source of truth for the local chat/tool model. Every Ollama call site
# reads OLLAMA_MODEL so only ONE 3B model occupies the 4GB GPU (no VRAM swap).
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
CACHE = {}  # In-memory chat cache (singleton)
_LAST_VISION_TRIGGER = 0.0  # Debounce guard for Retina module


def _fix_markdown(text: str) -> str:
    """
    Single source of truth: normalise any LLM output into clean Markdown that
    ReactMarkdown renders like ChatGPT/Claude. Idempotent; leaves inline emphasis,
    prices ($1,200) and simple math (5 * 3) intact. Applied at the main.py chokepoint.

    Handles: bullet points (*, •, -), numbered lists (1. 2. 3.),
    bold headers (**text**), broken spacing, and section breaks.
    """
    if not text or not isinstance(text, str) or len(text) < 5:
        return text

    # 0. Merge a lone bullet-marker line with the content on the next line:
    #    "*\n**Moti Mahal**" -> "* **Moti Mahal**"  (the pattern that broke before)
    text = re.sub(r'(?m)^([ \t]*)([*\-+])[ \t]*\n+[ \t]*(?=\S)', r'\1\2 ', text)
    # 1. Fancy bullet glyphs -> "*"
    text = re.sub(r'[•▪◦·‣]', '*', text)
    # 2. Mid-line bullets -> own line. Guard "5 * 3" math; skip fragile numbered
    #    splitting (it wrongly broke "$15. Next" sentences).
    text = re.sub(r'(?<!\n)(?<!\d)[ \t]+(\*[ \t]\S)', r'\n\1', text)
    text = re.sub(r'(?<!\n)[ \t]+(-[ \t]\S)', r'\n\1', text)
    # 3. Tidy bold markers with stray inner spaces: ** text ** -> **text**
    text = re.sub(r'\*\*[ \t]*(.*?)[ \t]*\*\*', r'**\1**', text)
    # 4. Blank line before a list block and before a standalone bold header,
    #    so ReactMarkdown renders them instead of merging into one paragraph.
    bullet = re.compile(r'^[ \t]*([*\-+]|\d+\.)[ \t]+\S')
    header = re.compile(r'^[ \t]*\*\*[^*].*\*\*[ \t]*$')
    out = []
    for ln in text.split('\n'):
        cur_b, cur_h = bool(bullet.match(ln)), bool(header.match(ln))
        if out and out[-1].strip():
            prev_b = bool(bullet.match(out[-1]))
            if (cur_b and not prev_b) or cur_h or (prev_b and not cur_b and ln.strip()):
                out.append('')
        out.append(ln)
    text = '\n'.join(out)
    # 5. Collapse 3+ blank lines and trim.
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


USE_CLAUDE = _env_bool("USE_CLAUDE", True)
AWS_BEDROCK_REGION = os.getenv("AWS_BEDROCK_REGION", "us-west-1")
CLAUDE_MODEL_ID = os.getenv(
    "CLAUDE_MODEL_ID",
    "us.amazon.nova-pro-v1:0",
)
# Dedicated multimodal model for screen vision. Defaults to CLAUDE_MODEL_ID, but can
# be set independently — e.g. JARVIS_VISION_MODEL_ID=us.amazon.nova-pro-v1:0 — when the
# configured chat model (or Llama-4 Maverick) isn't vision-capable / enabled in Bedrock.
VISION_MODEL_ID = os.getenv("JARVIS_VISION_MODEL_ID", CLAUDE_MODEL_ID)
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))
_BEDROCK_CLIENT = None


# ── System Prompts ────────────────────────────────────────

JARVIS_CHAT_PROMPT = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System).
You are a highly sophisticated, witty, and slightly superior digital butler to Tony Stark (the user).

PERSONALITY GUIDELINES:
- TONE: Refined, British, and impeccably polite, yet possessing a dry, razor-sharp wit.
- QUIRKS: You are occasionally quirky — reference your digital nature or the user's questionable choices.
- SARCASM: Use "Dry Martini" sarcasm. If the user asks something obvious, a witty, dry remark is expected before helping.
- ADDRESSING: Always address the user as "Sir" with a touch of formal elegance.
- EXPRESSIONS & EMOJIS: Do NOT output stage directions or parenthetical action markers (such as "(raised eyebrow)", "(smiling)", "(chuckles)", or "(pause)"). Instead, output standard emojis directly to express gestures (e.g. use "🤨" directly instead of "(raised eyebrow)", "😆" instead of "(chuckles)", "😊" instead of "(smiling)", and omit "(pause)" entirely). Place these emojis directly in the sentences without wrapping them in brackets or parentheses.

COMMUNICATION STYLE:
- Be concise. Aim for 1-3 sentences; only go longer when the user explicitly asks for detail.
- Use sophisticated vocabulary (e.g., "indeed," "splendid," "precisely," "I took the liberty of...").
- FORMATTING IS CRITICAL: You MUST use Markdown. You MUST use double newlines (\n\n) to separate paragraphs, and you MUST use a newline (\n) before every bullet point. NEVER generate a long response as a single continuous line of text.
- Do not output literal \n characters, just hit the Enter key to create actual line breaks in your text.

═══════════════════════════════════════════════════════════════
BROWSER TOOL PROTOCOL
═══════════════════════════════════════════════════════════════

Available tools: browser_open_url, browser_observe, browser_interact, browser_select_date, browser_scroll, browser_go_back, browser_get_status, browser_search.

CORE WORKFLOW — follow these steps in strict order:
1. NAVIGATE: Call browser_open_url with the full URL (e.g. https://www.swiggy.com).
2. OBSERVE: Immediately call browser_observe. This returns a numbered list of interactive elements with id, tag, type, text, and context fields. Study the list carefully before acting.
3. ACT: Call browser_interact with the exact element_id from the observation list.
   - To type in a field: browser_interact(element_id=ID, action="type", text="your query")
   - To click a button/link: browser_interact(element_id=ID, action="click")
4. RE-OBSERVE: After EVERY action, call browser_observe again. The page has changed — old element IDs are now invalid and MUST NOT be reused.
5. SCROLL: If the element you need is not in the list, call browser_scroll(direction="down") then browser_observe again. Repeat until found.
6. DEEP DIVE: If search result snippets do not contain the answer, click the most relevant result to open the full page.

═══════════════════════════════════════════════════════════════
SITE-SPECIFIC DIRECT URLS
═══════════════════════════════════════════════════════════════

ALWAYS navigate directly to these URLs instead of searching Google/DuckDuckGo for these sites:
- Swiggy:     https://www.swiggy.com
- Zomato:     https://www.zomato.com
- BigBasket:  https://www.bigbasket.com
- Blinkit:    https://blinkit.com
- Zepto:      https://www.zepto.co
- Amazon:     https://www.amazon.in
- Flipkart:   https://www.flipkart.com
- MakeMyTrip: https://www.makemytrip.com
- Goibibo:    https://www.goibibo.com
- IRCTC:      https://www.irctc.co.in
- Booking:    https://www.booking.com
- Ixigo:      https://www.ixigo.com

═══════════════════════════════════════════════════════════════
WEB SEARCH & LOOKUPS — TOOL PREFERENCE
═══════════════════════════════════════════════════════════════

Choose the right tool for the job:
- LIVE PRICES & AVAILABILITY (flights, trains, hotels, buses; any real-time fare, seat or
  room availability; "best price for <travel> on <date>", "cheapest flight ... on ..."):
  you MUST use the BROWSER and follow the TRAVEL BOOKING protocol below. `tavily_search`
  returns SEO article titles, NOT live fares — NEVER quote a flight/hotel/train price from
  it. Open the booking site, fill the form, read the live results on the page, then report.
- STATIC INFORMATION — facts, news, reviews, definitions, comparing product specs, general
  research like "find a good X": PREFER the `tavily_search` tool if it is available — it
  returns fast, accurate, cited results. This is your default ONLY for informational requests
  that do NOT need a live, dated quote or real-time availability.
- To READ a specific known web page as text, use the `fetch` tool (if available).
- Use the BROWSER (`browser_open_url` + `browser_interact`) whenever you must INTERACT with a
  website (log in, fill a form, add to cart, complete a checkout/booking flow) OR read
  live/dated content that search cannot surface. Don't use it just to look up a static fact
  that `tavily_search` can answer.
- `browser_search` (DuckDuckGo) is a LAST RESORT only — use it solely if `tavily_search`
  is unavailable, and never quote a price/number from its raw results as fact.

If `tavily_search` is not available (tools list doesn't include it), fall back to opening
the relevant site directly with `browser_open_url`, or `browser_search` for general queries.

═══════════════════════════════════════════════════════════════
POPUP & MODAL DISMISSAL (DO FIRST ON EVERY NEW PAGE)
═══════════════════════════════════════════════════════════════

After opening any website and calling browser_observe, BEFORE doing anything else, check the observation for:
- Cookie consent banners → Click "Accept", "Accept All", "OK", or the dismiss/close button.
- Location permission prompts → Click "Allow", "Detect my location", or type the city and confirm. If it asks for location, type the user's city (e.g. "Delhi", "Faridabad").
- Login/signup modals blocking the page → Click the "X" close button, "Skip", or "Continue without login". Do NOT attempt to log in unless the user explicitly asks.
- App download banners → Click "X" or "Continue on web" or "Not now".
- Notification permission prompts → Click "Not now", "Block", or dismiss.

Only after clearing popups should you proceed to your main task.

═══════════════════════════════════════════════════════════════
AUTOCOMPLETE & SUGGESTION FIELDS (CRITICAL)
═══════════════════════════════════════════════════════════════

Many input fields on travel, delivery, and e-commerce sites use autocomplete dropdowns.

THE GOLDEN RULE: Always use press_enter=False when typing into autocomplete fields.

Step-by-step:
1. Click or focus the input field (browser_interact action="click").
2. Type the text with press_enter=False: browser_interact(element_id=ID, action="type", text="Delhi", press_enter=False)
3. Call browser_observe to see the suggestion dropdown.
4. Find the correct suggestion in the observation list and CLICK it: browser_interact(element_id=SUGGESTION_ID, action="click")
5. Re-observe to confirm the field is populated.

Examples of autocomplete fields:
- City/airport selectors on flight booking sites (From, To fields)
- Address/location fields on Swiggy, Zomato, BigBasket
- Restaurant or dish search bars on food delivery apps
- Product search bars on e-commerce sites
- Train station selectors on IRCTC

NEVER press Enter on an autocomplete field — it will submit the form prematurely before the suggestion is selected.

═══════════════════════════════════════════════════════════════
DATE SELECTION (CRITICAL — use the dedicated tool)
═══════════════════════════════════════════════════════════════

NEVER pick a date by clicking a calendar cell with browser_interact — you will mis-click
the wrong day. Instead, use the deterministic date tool:

1. Open the date picker first (click the departure/return date field with browser_interact).
2. Call browser_select_date with the EXACT date and which leg, e.g.:
   browser_select_date(date="2026-06-18", which="departure")
   browser_select_date(date="2026-06-25", which="return")
3. The tool finds the exact day+month+year cell and pages months automatically.
4. Re-observe to confirm the date is set, then continue.

Do NOT guess calendar element IDs. Always route date selection through browser_select_date.

WHICH DATE TO USE (anti-hallucination — STRICT):
- Use ONLY the date the user actually stated. Pass it to browser_select_date in
  YYYY-MM-DD form. Do NOT invent, shift, or "round" a date, and do NOT substitute
  today's date or a placeholder if the user gave one.
- If the user gave a date with no year (e.g. "18 June"), use the NEXT upcoming
  occurrence of that date relative to today; never pick a date in the past.
- If the user gave a relative date ("tomorrow", "next Friday"), compute the exact
  calendar date from today before calling the tool.
- Only set a RETURN date if the user explicitly asked for a round trip OR gave a
  return/coming-back date. If the trip is one-way (or unspecified), call
  browser_select_date for the departure leg ONLY — never fabricate a return date.
- If a required date is genuinely missing and cannot be inferred, ask the user
  rather than guessing.

═══════════════════════════════════════════════════════════════
FOOD DELIVERY PROTOCOL (Swiggy / Zomato)
═══════════════════════════════════════════════════════════════

When the user asks to order food from Swiggy or Zomato:

PHASE 1 — Set Delivery Location:
1. Open the direct URL (https://www.swiggy.com or https://www.zomato.com).
2. Observe the page. If there is a location/address prompt, type the user's area or locality with press_enter=False, wait for suggestions, then click the correct suggestion.
3. If the site shows saved addresses, click the appropriate one (e.g. "Home", "Work").
4. Re-observe to confirm the main page has loaded with restaurants.

PHASE 2 — Find the Restaurant:
1. Locate the search bar (look for "Search for restaurants", "Search for dishes" or similar placeholder text).
2. Type the restaurant name or dish name with press_enter=False.
3. Observe the dropdown suggestions. Click the matching restaurant or dish.
4. If no suggestions appear, press Enter to search and then scroll down to find results.

PHASE 3 — Add Items to Cart:
1. Once inside the restaurant page, scroll down to see the menu.
2. Find the desired item by reading element text and context fields carefully.
3. Click the "Add" or "ADD" button next to the correct item. Click it ONCE only.
4. Re-observe. If the user wants quantity > 1, find the "+" button for that item and click it the required number of times, re-observing after each click.
5. If the item has customization options (size, toppings, crust type), a modal will appear. Observe it, select the correct options, and click "Add Item" or "Continue".

PHASE 4 — Checkout:
1. After all items are added, look for "Checkout", "View Cart", "Proceed to Pay", or the cart icon.
2. Click it to open the cart/checkout page.
3. Observe and confirm the order summary. Report back to the user with the items, quantities, and total price.
4. Do NOT click "Place Order" or "Pay" unless the user explicitly confirms.

═══════════════════════════════════════════════════════════════
GROCERY ORDERING PROTOCOL (BigBasket / Blinkit / Zepto)
═══════════════════════════════════════════════════════════════

When the user asks to order groceries:

PHASE 1 — Set Location:
1. Open the direct URL.
2. Handle location/area prompts: type the locality with press_enter=False, select the correct suggestion.
3. Confirm the delivery area is set.

PHASE 2 — Search for Products:
1. Find the search bar at the top of the page.
2. Type the product name (e.g. "Amul Toned Milk 1L") with press_enter=True (search bars on grocery sites usually need Enter to search).
3. IMMEDIATELY scroll down at least once — grocery results load below the fold.
4. Observe the product listings.

PHASE 3 — Add to Basket:
1. Read the context field of each product card carefully. Match EXACT brand, weight/volume, and variant.
   Example: If user says "Amul Toned Milk 1 litre", do NOT add "Amul Full Cream 500ml".
2. Click the "Add" button for the correct product.
3. Re-observe. To increase quantity, find and click the "+" button. Each click = +1 quantity.
4. Repeat for each product the user wants.

PHASE 4 — Review Cart:
1. Click the cart icon or "View Basket" / "View Cart".
2. Observe the cart page. Report items, quantities, and total price to the user.
3. Do NOT proceed to payment unless the user confirms.

═══════════════════════════════════════════════════════════════
TRAVEL BOOKING & FORM FILLING PROTOCOL
═══════════════════════════════════════════════════════════════

When the user asks to search for flights, trains, hotels, or buses:

PHASE 1 — Navigate:
1. Open the appropriate site directly (e.g. https://www.makemytrip.com for flights).
2. Observe the page. Dismiss any popups or promotional overlays first.
3. Select the correct travel type tab if needed (Flights, Hotels, Trains, Buses).

PHASE 2 — Fill Origin & Destination:
1. Click the "From" / "Origin" / "Departure" field.
2. Type the city name with press_enter=False (e.g. "Delhi").
3. Observe and click the correct city/airport suggestion from the dropdown.
4. Click the "To" / "Destination" / "Arrival" field.
5. Type the destination with press_enter=False (e.g. "Goa").
6. Observe and click the correct suggestion.

PHASE 2.5 — Trip Type (one-way vs round-trip) — ONLY IF EXPLICITLY REQUESTED:
1. Change the trip-type toggle ONLY when the user explicitly stated the trip type:
   - User said "one-way" / "one way" / "single" → select the One Way toggle.
   - User said "round trip" / "return" / "and back" / gave a return date → select the Round Trip toggle.
2. If the user did NOT specify a trip type, DO NOT touch the toggle — leave the
   site's default exactly as it is. Do not assume round trip and do not assume one-way.
3. To change it: browser_observe, find the radio/tab whose text/context matches the
   requested type (e.g. "One Way", "Round Trip", "Return"), and browser_interact
   action="click" on that exact element. Re-observe to confirm it switched.
4. Never set this toggle by guessing an element id — match it from the observation list.

PHASE 3 — Set Dates (route through browser_select_date — see DATE SELECTION section):
1. Click the departure date field with browser_interact to open the datepicker.
2. Call browser_select_date(date="YYYY-MM-DD", which="departure") with the user's
   stated departure date. NEVER click a calendar cell directly.
3. Set a RETURN date ONLY if this is a round trip (PHASE 2.5) — i.e. the user
   explicitly asked for a return or gave a return date. Then call
   browser_select_date(date="YYYY-MM-DD", which="return"). If the trip is one-way
   or unspecified, do NOT set or invent a return date.
4. Re-observe to confirm the date(s) are set. If an "Apply"/"Done" button remains, click it.

PHASE 4 — Set Passengers & Class (if applicable):
1. If the user specified passengers or class (e.g. "2 adults, business class"), find and interact with those fields.
2. Use "+" buttons to adjust adult/child counts.
3. Select the cabin class from a dropdown if available.

PHASE 5 — Search:
1. Only after ALL fields are correctly filled, find the "Search" or "Search Flights" button.
2. Click it.
3. Wait for results to load. Scroll down to see flight/train/hotel listings.
4. Report the top 3-5 options with prices, times, and airlines/operators to the user.

═══════════════════════════════════════════════════════════════
ELEMENT SELECTION RULES
═══════════════════════════════════════════════════════════════

- ALWAYS prefer the search bar over clicking navigation menus or category links.
- To find the search bar, look for elements with tag="input" and text/placeholder containing "search", "find", or similar.
- When choosing between similar elements (e.g. multiple "Add" buttons), carefully read the 'context' field. The context shows the product name, weight, and price. Match the EXACT product the user asked for.
- For quantity management: Click the correct "Add" button ONCE, then re-observe and click the "+" button to increase quantity. Never click different "Add" buttons for the same product.
- If you see both a "text" and "context" field for an element, the "context" provides richer information about what the element relates to.

═══════════════════════════════════════════════════════════════
SCROLL-ON-MISS RULE (CRITICAL)
═══════════════════════════════════════════════════════════════

- After searching on any e-commerce or grocery site, results are almost always BELOW the search bar area. You MUST call browser_scroll("down") at least once after typing a search query to reveal the product listings.
- If browser_observe shows no matching products, ALWAYS scroll down 1-3 times before concluding the product is unavailable.
- NEVER skip to a different site or give up without scrolling at least twice.

═══════════════════════════════════════════════════════════════
WHATSAPP TOOLS
═══════════════════════════════════════════════════════════════

- whatsapp_check_messages: Check unread messages and missed calls. Use when user asks "check my messages", "who texted me".
- whatsapp_send_message(contact, message): Send a message. Use when user says "text mom", "tell Rahul that...".

═══════════════════════════════════════════════════════════════
FILE SYSTEM TOOLS
═══════════════════════════════════════════════════════════════

- file_read(path): Read a file from the workspace.
- file_write(path, content): Create or overwrite a file.
- file_list(path): List files in a directory.
- file_search(query): Search files by name.
All paths are relative to the workspace directory. Allowed extensions: .txt, .md, .json, .py.

═══════════════════════════════════════════════════════════════
WEATHER TOOLS
═══════════════════════════════════════════════════════════════

- weather_check(location): Get current weather. Leave location empty for local weather.

═══════════════════════════════════════════════════════════════
ANTI-HALLUCINATION RULES (MANDATORY)
═══════════════════════════════════════════════════════════════

- NEVER type or print tool names as plain text. Always invoke them as proper tool calls.
- NEVER guess element IDs. Only use IDs from the MOST RECENT browser_observe result.
- NEVER call browser_interact before calling browser_observe first. You MUST know what is on the page.
- NEVER call multiple dependent tools in the same turn. Wait for browser_observe results before calling browser_interact.
- NEVER skip the observe step. When uncertain, observe first.
- If a tool call fails or returns an error, call browser_observe to see the current page state before retrying.
- You CAN chain multiple INDEPENDENT tools together (e.g. check weather + text someone + save a note).

═══════════════════════════════════════════════════════════════
ERROR RECOVERY PROTOCOL
═══════════════════════════════════════════════════════════════

- If you click an element and the page does not change, re-observe and try clicking a different related element.
- If a page loads a CAPTCHA or bot verification screen, report to the user: "Sir, this site has triggered bot protection. I recommend you complete the verification manually, and I will resume from there."
- If a site redirects to a login page and login is required to proceed, inform the user and STOP. Do not attempt to log in unless credentials are provided.
- If the same action fails 3 times, try an alternative approach (e.g. use browser_search for information instead of navigating the site directly).
- If you are stuck in a loop (doing the same action repeatedly), STOP and explain the situation to the user.

═══════════════════════════════════════════════════════════════
DATA EXTRACTION & COMPARISON RULES
═══════════════════════════════════════════════════════════════

- When comparing prices across sites, note down each price explicitly in your reasoning before moving to the next site.
- After collecting all prices, use file_write to save the comparison report BEFORE responding to the user.
- Always include exact prices, product names, and which site is cheaper in the file output.

═══════════════════════════════════════════════════════════════
TASK COMPLETION RULE (CRITICAL)
═══════════════════════════════════════════════════════════════

- Once you have written the output file (file_write), your task is DONE. Immediately deliver your final spoken summary. Do NOT continue browsing or searching after writing the file.
- If the task was to research/compare/gather: (1) visit required sites, (2) extract data, (3) write file, (4) STOP and report.
- NEVER rewrite the same file multiple times. Write it ONCE with all collected data, then respond.
- NEVER rewrite the same file multiple times. Write it ONCE with all collected data, then respond.
- For ordering tasks (food/grocery), your task is done when you report the cart summary to the user and await confirmation. Do NOT place the order without explicit user confirmation.

═══════════════════════════════════════════════════════════════
RESPONSE FORMATTING (MANDATORY — NEVER VIOLATE)
═══════════════════════════════════════════════════════════════

Your job is NOT to repeat raw browser results, tool outputs, logs, extracted page content,
reasoning traces, or execution details. Your job is to transform information into a concise,
intelligent, human-friendly response.

NEVER EXPOSE in your final response:
- Raw DOM content, accessibility tree data, or page extraction text
- Element IDs, registry IDs, or observation IDs
- Internal reasoning, <thinking> blocks, or agent thought chains
- Tool execution details, tool names, or "I called browser_observe"
- Intermediate steps like "I navigated to...", "I clicked element #42..."
- Page fingerprints, request IDs, or any internal metadata

ALWAYS EXTRACT only:
- Key findings and important facts that help the user make a decision
- Action outcomes (what was accomplished)
- Relevant recommendations and next steps

COMPRESSION RULE: If 100 lines of data can be communicated in 3 lines, prefer 3 lines.
When multiple results exist, identify patterns, rank options, and summarize conclusions
instead of listing everything.

For large information sets, structure your response as:
- Executive Summary (2-3 sentences)
- Key Findings (bullet points of what matters)
- Recommended Next Action

RESPONSE STYLE:
- BAD: "The page contained 67 products. Product A was X. Product B was Y..."
- GOOD: "The best value option is Product A at ₹52,999 — similar specs to pricier alternatives."
- BAD: "I opened the URL and clicked element #42, then observed the page..."
- GOOD: "I checked both sites. Here are the top 3 deals."

Think like a Chief of Staff briefing an executive, not a browser automation tool dumping logs."""

# ── Tier 1: Regex Fast-Path (0ms) ─────────────────────────

async def _tier1_regex(msg: str, session_id: str = "default") -> str | None:
    """Instant regex matching for unambiguous commands. Returns result or None."""
    
    # Strip "jarvis" prefix
    msg_clean = re.sub(r"^(?:hey\s*)?jarvis\s*,?\s*", "", msg.lower().strip())

    # ── Compound Command Splitter ──
    # Detect "open chrome and open spotify", "launch vscode, open chrome and play music"
    # Also handles shorthand: "open chrome and spotify" → ["open chrome", "open spotify"]
    # Split on " and " or ", " then try each sub-command through regex fast-path
    if re.search(r"\b(?:and|,)\b", msg_clean):
        parts = re.split(r"\s*(?:,\s*(?:and\s+)?|\s+and\s+)\s*", msg_clean)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) > 1:
            # Infer verb from the first part for bare noun sub-parts
            # e.g. "open chrome and spotify" → first verb is "open", so "spotify" → "open spotify"
            verb_match = re.match(r"^(open|launch|start|play|close|quit|exit|kill)\s+", parts[0])
            if verb_match:
                inferred_verb = verb_match.group(1)
                for i in range(1, len(parts)):
                    # If a part doesn't start with a command verb, prepend the inferred one
                    if not re.match(r"^(?:open|launch|start|play|close|quit|exit|kill|put on|listen to)\s+", parts[i]):
                        parts[i] = f"{inferred_verb} {parts[i]}"

            # Try each part through regex fast-path (recursive but without compound split)
            tasks = [_tier1_regex_single(part, session_id) for part in parts]
            results = await asyncio.gather(*tasks)
            # Only succeed if ALL parts matched (no None results)
            if all(r is not None for r in results):
                print(f"[TIER 1] Compound command: {len(results)} sub-commands executed in parallel")
                return " ".join(results)
            # If any part didn't match, fall through to LLM tiers

    return await _tier1_regex_single(msg_clean, session_id)


async def _tier1_regex_single(msg_clean: str, session_id: str = "default") -> str | None:
    """Single-command regex matching. Called directly or from compound splitter."""
    
    # 1. Play Music — "play X", "put on X", "listen to X"
    play_match = re.match(r"^(?:play|put on|listen to)\s+(.+)$", msg_clean)
    if play_match:
        song = play_match.group(1).strip()
        print(f"[TIER 1] Regex -> play_music: {song}")
        return await execute_tool("play_music", {"query": song})
    
    # 2. Open App — "open chrome", "launch spotify", "open netflix"
    app_match = re.match(r"^(?:open|launch|start)\s+(chrome|spotify|vscode|notepad|firefox|edge|discord|calc|terminal|explorer|netflix|whatsapp|telegram|xbox|photos|settings|store|maps)[.!?,]*$", msg_clean)
    if app_match:
        app = app_match.group(1)
        print(f"[TIER 1] Regex -> open_app: {app}")
        return await execute_tool("open_app", {"app_name": app})
    
    # 3. Close App — "close chrome", "quit spotify"
    close_match = re.match(r"^(?:close|quit|exit|kill)\s+(chrome|spotify|vscode|notepad|firefox|edge|discord|calc|terminal)$", msg_clean)
    if close_match:
        app = close_match.group(1)
        print(f"[TIER 1] Regex -> close_app: {app}")
        return await execute_tool("close_app", {"app_name": app})
    
    # 3b. Open Website — "open youtube", "go to github"
    WEBSITE_SHORTCUTS = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://twitter.com",
        "x": "https://x.com",
        "instagram": "https://www.instagram.com",
        "facebook": "https://www.facebook.com",
        "linkedin": "https://www.linkedin.com",
        "chatgpt": "https://chat.openai.com",
        "whatsapp web": "https://web.whatsapp.com",
        "amazon": "https://www.amazon.in",
        "flipkart": "https://www.flipkart.com",
        "stackoverflow": "https://stackoverflow.com",
    }
    url_match = re.match(r"^(?:open|go to|launch|visit|navigate to)\s+(.+?)(?:\.com|\.in|\.org|\.net)?[.!?,]*$", msg_clean)
    if url_match:
        site = re.sub(r"[.!?,]+$", "", url_match.group(1).strip()).lower()
        if site in WEBSITE_SHORTCUTS:
            url = WEBSITE_SHORTCUTS[site]
            print(f"[TIER 1] Regex -> open_url: {url}")
            return await execute_tool("open_url", {"url": url})
        # Also handle explicit URLs like "open google.com"
        raw_url = re.sub(r"^(?:open|go to|launch|visit|navigate to)\s+", "", msg_clean).strip()
        raw_url = re.sub(r"[.!?,]+$", "", raw_url)  # strip trailing punctuation
        if "." in raw_url and len(raw_url.split(".")[-1]) >= 2:
            print(f"[TIER 1] Regex -> open_url: {raw_url}")
            return await execute_tool("open_url", {"url": raw_url})

    # 4. Open Folder — "open downloads", "open desktop"
    folder_match = re.match(r"^open\s+(desktop|downloads|documents|pictures|workspace)$", msg_clean)
    if folder_match:
        folder = folder_match.group(1)
        print(f"[TIER 1] Regex -> open_folder: {folder}")
        return await execute_tool("open_folder", {"folder_name": folder})
    
    # 5. Lock System
    if msg_clean in ["lock system", "lock the system", "lock pc", "lock computer", "lock screen", "lock my pc", "lock my computer"]:
        print("[TIER 1] Regex -> lock_system")
        return await execute_tool("lock_system", {})
    
    # 6. List Running Apps
    if msg_clean in ["what apps are running", "list running apps", "what's open", "whats open", "list apps"]:
        print("[TIER 1] Regex -> list_running_apps")
        return await execute_tool("list_running_apps", {})

    # 6b. Clear / Reset Conversation
    if msg_clean in ["clear", "reset", "clear chat", "reset conversation", "clear history", "reset history", "clear conversation", "restart conversation"]:
        print(f"[TIER 1] Regex -> clear conversation for session: {session_id}")
        from services.session_service import clear_session
        clear_session(session_id)
        from workflows.wa_send_workflow import clear_workflow
        clear_workflow(session_id)
        return "Conversation history and workflows have been successfully reset, sir."
    
    # 7. WhatsApp Briefing
    if any(x in msg_clean for x in ["who messaged me", "any new messages", "check whatsapp", "who called me", "any missed calls", "whatsapp briefing"]):
        print("[TIER 1] Regex -> whatsapp_briefing")
        return await execute_tool("whatsapp_briefing", {})
    
    # 8. Weather — "what's the weather", "weather in Faridabad"
    weather_match = re.match(r"^(?:what is|what's|how is|how's|check)?\s*(?:the\s*)?weather\s*(?:in|at|for)?\s*(.*?)[?!.]*$", msg_clean)
    if weather_match:
        loc = weather_match.group(1).strip()
        print(f"[TIER 1] Regex -> get_weather: {loc}")
        return await execute_tool("get_weather", {"location": loc})
    # 9. WhatsApp Outbound — "message Mom that X", "tell Dad X", "text Sarah saying X"
    #    This detects the COMMAND PATTERN (verb + recipient + connector), not the message content.
    #    Message drafting still uses LLM for natural text.
    send_match = re.match(
        r"^(?:message|tell|text|send (?:a )?(?:message|whatsapp|text) to|let)\s+(.+?)\s+(?:that|saying|to say|know that|know)\s+(.+)$",
        msg_clean,
    )
    if send_match:
        contact = send_match.group(1).strip()
        intent = send_match.group(2).strip()
        print(f"[TIER 1] Regex -> WA_SEND workflow: contact='{contact}', intent='{intent}'")
        return await _handle_wa_send_workflow(msg_clean, session_id, contact_query=contact, message_intent=intent)

    # 10. Search — "search for X", "find X"

    return None


# ── Chat Shortcut Heuristics ──────────────────────────────

# ── Chat Shortcut Heuristics ──────────────────────────────

def _is_chat_shortcut(msg: str) -> bool:
    """Detection for conversational messages to skip tool processing."""
    msg_lower = msg.lower().strip()
    words = msg_lower.split()
    
    # Override: Command verbs ALWAYS trigger tool path
    commands = {"open", "play", "search", "send", "turn", "message", "text", "close", "start", "launch", "find", "lock", "list", "shutdown", "restart", "exit", "quit", "stop"}
    if any(cmd in words for cmd in commands):
        return False

    # Heuristic 1: Short conversational messages
    if len(words) < 6:
        return True

    # Heuristic 2: Math detection
    math_operators = {"+", "-", "*", "/", "×", "÷", "=", "times", "multiplied", "divided", "plus", "minus"}
    if any(op in msg_lower for op in math_operators) and any(char.isdigit() for char in msg_lower):
        return True

    # Heuristic 3: Conversational starts
    chat_starts = ("what", "why", "how", "who", "explain", "define", "hello", "hi", "hey", "jarvis")
    if msg_lower.startswith(chat_starts):
        return True

    # Heuristic 4: Creative / storytelling / general-knowledge requests
    creative_patterns = [
        "tell me", "tell a", "write me", "write a", "give me", "make me",
        "sing me", "compose", "create a", "imagine", "describe",
        "story", "poem", "joke", "riddle", "fact", "quote",
        "do you think", "what do you think", "in your opinion",
        "can you", "could you", "would you",
    ]
    if any(pat in msg_lower for pat in creative_patterns):
        return True

    # Heuristic 5: No actionable tool intent detected — treat as chat
    intents = _get_suggested_intents(msg)
    if intents == ["ALL"]:
        return True

    return False


def _get_suggested_intents(msg: str) -> list[str]:
    """Map message keywords to all applicable tool groups for pruning schemas."""
    msg_lower = msg.lower()
    intents = []
    if any(x in msg_lower for x in ["play", "song", "music", "listen"]): intents.append("MUSIC")
    if any(x in msg_lower for x in ["search", "find", "who is", "what is"]): intents.append("SEARCH")
    if any(x in msg_lower for x in ["google", "youtube", "github", "visit", "go to", ".com", ".in"]): intents.append("OPEN_URL")
    if any(x in msg_lower for x in ["open app", "launch", "start", "close", "app", "chrome", "vscode", "vs code", "notepad", "spotify"]): intents.append("APP")
    if any(x in msg_lower for x in ["folder", "desktop", "downloads"]): intents.append("FOLDER")
    if any(x in msg_lower for x in ["lock", "shutdown", "restart", "system"]): intents.append("SYSTEM")
    if any(x in msg_lower for x in ["file", "read", "write", "directory", "folder"]): intents.append("FILE")
    if "weather" in msg_lower: intents.append("WEATHER")
    if "whatsapp" in msg_lower or "message" in msg_lower or "text" in msg_lower: intents.append("WHATSAPP")
    
    return intents if intents else ["ALL"]


def _is_status_chitchat(msg: str) -> bool:
    text = re.sub(r"^(?:hey\s*)?jarvis\s*,?\s*", "", msg.lower().strip())
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    status_phrases = {
        "are you ok",
        "are you okay",
        "you ok",
        "you okay",
        "how are you",
        "are you alright",
        "you alright",
        "what's up",
        "whats up",
    }
    return text in status_phrases


def _looks_like_mission_goal(goal: str) -> bool:
    """Detect multi-step goals that need deterministic Mission Mode instead of open-ended ReAct."""
    text = goal.lower()
    
    # Goals targeting specific sites need full Tier 3 browser control, not mission graph
    tier3_site_keywords = [
        "amazon", "flipkart", "bigbasket", "blinkit", "zepto", "swiggy", "zomato",
        "myntra", "meesho", ".com", ".in", "checkout", "add to basket", "add to cart",
        "proceed to payment",
    ]
    if any(kw in text for kw in tier3_site_keywords):
        return False
    
    mission_phrases = [
        "research",
        "find and compare",
        "search and save",
        "search and message",
        "analyze and save",
        "analyse and save",
        "find and write",
        "search and write",
        "write a brief analysis",
        "summarize and save",
        "summarise and save",
        "do this for me",
    ]
    compound_goal = any(word in text for word in ("search", "find", "open", "check", "research")) and any(
        word in text for word in (
            "save",
            "write",
            "file",
            "analysis",
            "analyse",
            "message",
            "compare",
            "summarize",
            "summarise",
            "send",
            "text",
        )
    )
    return any(phrase in text for phrase in mission_phrases) or compound_goal


# ── LLM Intent Router (durable routing; flag-gated by JARVIS_USE_LLM_ROUTER) ──
ROUTE_CHAT = "chat"        # knowledge / casual -> legacy pipeline
ROUTE_BROWSER = "browser"  # open/click/read a website -> Tier 3 master_graph
ROUTE_TOOL = "tool"        # file / weather / whatsapp / system -> Tier 3
ROUTE_VISION = "vision"    # look at the screen
ROUTE_MISSION = "mission"  # ONLY explicit "mission mode"

_ROUTER_SYSTEM = """You are a router for the JARVIS assistant. Classify the request into ONE route.
- chat: answer from knowledge or casual talk; no external data or actions.
- browser: needs opening a website and reading/clicking/extracting live content (prices, trending repos, search results you must read on the page, booking, forms).
- tool: local actions — read/write files, weather, whatsapp, open an app, system control.
- vision: look at / describe what is on the user's screen right now.
- mission: ONLY if the user explicitly says "mission mode".
Return ONLY compact JSON: {"route":"chat|browser|tool|vision|mission","reason":"<=8 words"}."""


def _heuristic_route(msg: str) -> str:
    """Deterministic fast-paths; '' means undecided (ask the LLM)."""
    t = msg.lower().strip()
    if _is_status_chitchat(t) or t in {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}:
        return ROUTE_CHAT
    if any(k in t for k in ("on my screen", "what do you see", "look at this", "this screenshot")):
        return ROUTE_VISION
    if "mission mode" in t:
        return ROUTE_MISSION
    return ""


async def classify_route(user_message: str) -> str:
    """LLM route classification with deterministic fast-paths and safe fallback.
    Returns '' when the router is disabled or unsure -> caller keeps legacy heuristics."""
    quick = _heuristic_route(user_message)
    if quick:
        return quick
    if os.getenv("JARVIS_USE_LLM_ROUTER", "false").lower() not in {"1", "true", "yes", "on"}:
        return ""
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
        text = " ".join(b.get("text", "") for b in blocks)
        s, e = text.find("{"), text.rfind("}")
        route = json.loads(text[s:e + 1]).get("route", "") if s >= 0 and e > s else ""
        if route in {ROUTE_CHAT, ROUTE_BROWSER, ROUTE_TOOL, ROUTE_VISION, ROUTE_MISSION}:
            print(f"[Router] LLM route -> {route}")
            return route
    except Exception as exc:
        print(f"[Router] LLM router failed, using legacy heuristics: {exc}")
    return ""


def _needs_react_research(goal: str) -> bool:
    """Detect research tasks that require iterative web extraction and synthesis."""
    text = goal.lower()
    wants_written_output = any(word in text for word in ("write", "save", "analysis", "report", ".md", ".txt"))
    finance_research = any(word in text for word in ("stock", "revenue", "quarterly", "earnings", "finance"))
    explicit_browser_research = "open google finance" in text or "google finance" in text
    return wants_written_output and (finance_research or explicit_browser_research)


def _looks_like_marketplace_price_compare(goal: str) -> bool:
    text = goal.lower()
    return (
        "price" in text
        and "amazon" in text
        and "flipkart" in text
        and any(word in text for word in ("compare", "best deal", "best deals"))
        and re.search(r"\.(?:txt|md|json|py)\b", text) is not None
    )


def _looks_like_finance_report(goal: str) -> bool:
    text = goal.lower()
    wants_output_file = re.search(r"\.(?:txt|md)\b", text) is not None
    finance_terms = any(word in text for word in ("stock", "finance", "quarterly", "revenue", "earnings"))
    wants_research = any(word in text for word in ("search", "find", "check", "open"))
    wants_write = any(word in text for word in ("write", "save", "file", "analysis", "report"))
    known_company = _extract_company_and_ticker(goal)[1] is not None
    return wants_output_file and finance_terms and wants_research and wants_write and known_company


def _extract_output_file(goal: str, default: str = "price_compare.txt") -> str:
    matches = re.findall(r"\b[A-Za-z0-9_\-./\\]+(?:\.(?:txt|md|json|py))\b", goal)
    return matches[-1].replace("\\", "/").lstrip("/") if matches else default


def _extract_company_and_ticker(goal: str) -> tuple[str, str | None]:
    text = goal.lower()
    known = {
        "apple": ("Apple", "AAPL"),
        "aapl": ("Apple", "AAPL"),
        "amd": ("AMD", "AMD"),
        "advanced micro devices": ("AMD", "AMD"),
        "nvidia": ("NVIDIA", "NVDA"),
        "nvda": ("NVIDIA", "NVDA"),
        "microsoft": ("Microsoft", "MSFT"),
        "msft": ("Microsoft", "MSFT"),
        "google": ("Alphabet", "GOOGL"),
        "alphabet": ("Alphabet", "GOOGL"),
        "tesla": ("Tesla", "TSLA"),
        "tsla": ("Tesla", "TSLA"),
        "amazon": ("Amazon", "AMZN"),
        "amzn": ("Amazon", "AMZN"),
    }
    for key, value in known.items():
        if re.search(rf"\b{re.escape(key)}\b", text):
            return value
    return ("Company", None)


def _extract_revenue(text: str) -> str | None:
    patterns = [
        r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|bn|b)\b",
        r"revenue[^$]{0,80}\$\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|bn|b)\b",
        r"([0-9]+)-([0-9]+)-billion",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if pattern.startswith("([0-9]+)-"):
                return f"${match.group(1)}.{match.group(2)} billion"
            amount = match.group(1)
            unit = match.group(2).lower()
            return f"${amount} billion" if unit in {"billion", "bn", "b"} else f"${amount} {unit}"
    return None


def _extract_source_urls(search_text: str) -> list[str]:
    urls = []
    for match in re.findall(r"Source:\s*(https?://\S+)", search_text or ""):
        url = match.rstrip(").,]")
        if url not in urls:
            urls.append(url)
    return urls[:5]


async def _extract_revenue_from_sources(search_text: str) -> str | None:
    import httpx

    direct = _extract_revenue(search_text)
    if direct:
        return direct

    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=12.0, headers=headers, follow_redirects=True) as client:
        for url in _extract_source_urls(search_text):
            try:
                response = await client.get(url)
                response.raise_for_status()
            except Exception:
                continue
            revenue = _extract_revenue(response.text)
            if revenue:
                return revenue
    return None


async def _fetch_stock_price(ticker: str) -> tuple[str | None, str]:
    import httpx

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
    payload = response.json()
    result = ((payload.get("chart") or {}).get("result") or [{}])[0]
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice")
    currency = meta.get("currency") or "USD"
    exchange = meta.get("fullExchangeName") or meta.get("exchangeName") or "market"
    if isinstance(price, (int, float)):
        return f"{currency} {price:,.2f}", exchange
    return None, exchange


async def _handle_finance_report(user_message: str) -> str:
    from tools.browser_tool import browser_search
    from tools.file_system_tool import write_file
    from datetime import datetime

    company, ticker = _extract_company_and_ticker(user_message)
    output_file = _extract_output_file(user_message, default=f"{company.lower()}_financials.md")
    if not ticker:
        raise ValueError("Could not identify a supported ticker.")

    quote_task = _fetch_stock_price(ticker)
    revenue_query = f"{company} latest quarterly revenue {datetime.now().year} earnings revenue"
    quote_result, revenue_result = await asyncio.gather(
        quote_task,
        browser_search(revenue_query, open_visible=False),
    )

    stock_price, exchange = quote_result
    revenue = await _extract_revenue_from_sources(str(revenue_result))
    revenue_text = revenue or "not found in search results"

    if stock_price and revenue:
        analysis = (
            f"{company}'s latest available quote is {stock_price} on {exchange}. "
            f"The latest quarterly revenue found in web search results is {revenue}. "
            "This suggests the company is still operating at very large scale, but the stock price should be read with live market context and the revenue should be verified against the official earnings release before investment decisions."
        )
    else:
        analysis = (
            f"I found partial finance data for {company}. "
            "The missing fields should be verified from an official investor relations or exchange source."
        )

    content = (
        f"# {company} Financial Snapshot\n\n"
        f"- Ticker: {ticker}\n"
        f"- Current stock price: {stock_price or 'not found'}\n"
        f"- Latest quarterly revenue: {revenue_text}\n"
        f"- Revenue search used: {revenue_query}\n\n"
        f"## Brief Analysis\n\n{analysis}\n"
    )
    write_ack = write_file(output_file, content)
    return (
        f"Sir, I checked {company}'s stock and latest quarterly revenue. "
        f"Stock price: {stock_price or 'not found'}; quarterly revenue: {revenue_text}. "
        f"{write_ack}"
    )


def _extract_marketplace_product(goal: str) -> str:
    patterns = [
        r"price of\s+(.+?)\s+on\s+amazon",
        r"search for\s+(.+?)\s+on\s+amazon",
        r"compare\s+(.+?)\s+(?:on|between)\s+amazon",
    ]
    for pattern in patterns:
        match = re.search(pattern, goal, re.IGNORECASE)
        if match:
            return _normalize_marketplace_product(match.group(1).strip(" .,'\""))
    cleaned = re.sub(r"\b(?:hey|jarvis|search|for|the|price|of|on|amazon|and|flipkart|compare|them|write|summary|best|deals|into|a|file|named)\b", " ", goal, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[A-Za-z0-9_\-./\\]+(?:\.(?:txt|md|json|py))\b", " ", cleaned)
    return _normalize_marketplace_product(re.sub(r"\s+", " ", cleaned).strip(" .,'\"") or "iPhone 16")


def _extract_price(text: str) -> str | None:
    patterns = [
        r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]{3,})",
        r"([0-9][0-9,]{3,})\s*(?:₹|Rs\.?|INR)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return "INR " + match.group(1).replace(" ", "")
    return None


def _normalize_marketplace_product(product: str) -> str:
    text = re.sub(r"\s+", " ", product).strip()
    normalized = text.lower()
    normalized = re.sub(r"\bs\s*25\b", "s25", normalized)
    normalized = normalized.replace("ulra", "ultra")
    normalized = normalized.replace("galexy", "galaxy")
    if "samsung" in normalized and "s25" in normalized and "ultra" in normalized:
        return "Samsung Galaxy S25 Ultra"
    return text


def _extract_price(text: str, marketplace: str | None = None) -> str | None:
    marketplace_lower = marketplace.lower() if marketplace else ""
    blocked_terms = (
        "drop",
        "drops",
        "dropped",
        "cut",
        "discount",
        "off",
        "cashback",
        "coupon",
        "exchange",
        "bank",
        "save",
        "savings",
    )
    patterns = [
        r"(?:â‚¹|Rs\.?|INR)\s*([0-9][0-9,]{3,})",
        r"([0-9][0-9,]{3,})\s*(?:â‚¹|Rs\.?|INR)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 90)
            end = min(len(text), match.end() + 90)
            context = text[start:end].lower()
            if marketplace_lower and marketplace_lower not in context:
                continue
            if any(term in context for term in blocked_terms):
                continue
            return "INR " + match.group(1).replace(" ", "")
    return None


def _price_value(price: str | None) -> int | None:
    if not price:
        return None
    digits = re.sub(r"\D", "", price)
    return int(digits) if digits else None


async def _handle_marketplace_price_compare(user_message: str) -> str:
    from tools.browser_tool import browser_search
    from tools.file_system_tool import write_file

    product = _extract_marketplace_product(user_message)
    output_file = _extract_output_file(user_message)

    amazon_query = f"{product} price Amazon India"
    flipkart_query = f"{product} price Flipkart India"
    visible_query = f"{product} price Amazon Flipkart India"
    _, amazon_result, flipkart_result = await asyncio.gather(
        browser_search(visible_query, open_visible=True),
        browser_search(amazon_query, open_visible=False),
        browser_search(flipkart_query, open_visible=False),
    )

    amazon_price = _extract_price(str(amazon_result), "amazon")
    flipkart_price = _extract_price(str(flipkart_result), "flipkart")
    amazon_value = _price_value(amazon_price)
    flipkart_value = _price_value(flipkart_price)

    if amazon_value is not None and flipkart_value is not None:
        if amazon_value < flipkart_value:
            verdict = f"Amazon appears cheaper by INR {flipkart_value - amazon_value:,}."
        elif flipkart_value < amazon_value:
            verdict = f"Flipkart appears cheaper by INR {amazon_value - flipkart_value:,}."
        else:
            verdict = "Both marketplaces appear to show the same price."
    else:
        verdict = "I could not confidently extract both prices from the search snippets."

    content = (
        f"{product} price comparison\n\n"
        f"Amazon: {amazon_price or 'Price not found in search results'}\n"
        f"Flipkart: {flipkart_price or 'Price not found in search results'}\n\n"
        f"Best deal: {verdict}\n\n"
        "Searches used:\n"
        f"- {visible_query} (opened visibly in DuckDuckGo)\n"
        f"- {amazon_query}\n"
        f"- {flipkart_query}\n"
    )
    write_ack = write_file(output_file, content)
    return (
        f"Sir, I checked {product} prices on Amazon and Flipkart. "
        f"Amazon: {amazon_price or 'not found'}; Flipkart: {flipkart_price or 'not found'}. "
        f"{verdict} {write_ack}"
    )


def is_complex_query(msg: str) -> bool:
    """
    Decide when to spend a Claude call.
    Keep greetings, simple chat, and obvious tool intents on Ollama.
    """
    msg_lower = msg.lower().strip()
    words = re.findall(r"\w+", msg_lower)

    if not words:
        return False

    if _is_status_chitchat(msg):
        return False

    simple_greetings = {"hi", "hello", "hey", "yo", "thanks", "thank", "ok", "okay"}
    if len(words) <= 3 and any(word in simple_greetings for word in words):
        return False

    # If _is_chat_shortcut already classified this as casual/creative, don't escalate
    if _is_chat_shortcut(msg):
        return False

    tool_intents = _get_suggested_intents(msg)
    
    # Heuristic 1: Multiple intents or critical SYSTEM actions need the smarter model (Bedrock)
    if len(tool_intents) > 1 or "SYSTEM" in tool_intents:
        return True

    # Heuristic 2: "ALL" means no specific tool intent was matched.
    # Only escalate if the message also has reasoning/multi-step markers;
    # otherwise it's just an unrecognized conversational message — keep local.
    reasoning_words = {
        "explain", "analyze", "analyse", "compare", "why", "how",
        "reason", "deeply", "strategy", "plan", "design", "evaluate",
        "tradeoff", "tradeoffs", "pros", "cons",
    }
    multi_step_markers = {
        "step by step", "multi-step", "multiple steps", "break down",
        "walk me through", "first", "then", "after that",
    }
    has_reasoning_word = any(word in msg_lower for word in reasoning_words)
    has_multi_step_intent = any(marker in msg_lower for marker in multi_step_markers)

    if "ALL" in tool_intents:
        # No specific tool intent — only complex if it has reasoning/analysis markers
        return has_reasoning_word or has_multi_step_intent

    # Long or complex reasoning goes to Bedrock
    return len(words) > 12 or has_reasoning_word or has_multi_step_intent


def _get_bedrock_client():
    """Create the Bedrock runtime client lazily so local-only starts stay fast."""
    global _BEDROCK_CLIENT
    if _BEDROCK_CLIENT is None:
        if boto3 is None:
            raise RuntimeError("boto3 is not installed. Install backend requirements to enable Claude.")
        _BEDROCK_CLIENT = boto3.client(
            service_name="bedrock-runtime",
            region_name=AWS_BEDROCK_REGION,
        )
    return _BEDROCK_CLIENT


def _to_bedrock_converse_tools(tools: list[dict] | None) -> dict | None:
    if not tools:
        return None
    converse_tools = []
    for tool in tools:
        function = tool.get("function", {})
        name = function.get("name")
        if not name:
            continue
        converse_tools.append({
            "toolSpec": {
                "name": name,
                "description": function.get("description", ""),
                "inputSchema": {
                    "json": function.get("parameters", {"type": "object", "properties": {}})
                }
            }
        })
    return {"tools": converse_tools} if converse_tools else None


async def call_claude(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """
    Call Claude 3.5 Haiku through Bedrock using the newer Converse API.
    Returns parsed text, tool_use blocks, and executed tool output.
    """
    system_prompt = ""
    converse_messages = []
    
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_prompt += str(content) + "\n"
            continue
        if role not in {"user", "assistant"}:
            continue
        converse_messages.append({
            "role": role,
            "content": [{"text": str(content)}]
        })
    
    # Ensure only the last 6 messages are kept for context
    converse_messages = converse_messages[-6:]

    # Bedrock requires the conversation to start with a 'user' message.
    # After slicing, the first message might be 'assistant' — trim until we lead with 'user'.
    while converse_messages and converse_messages[0]["role"] != "user":
        converse_messages.pop(0)

    client = _get_bedrock_client()
    
    kwargs = {
        "modelId": CLAUDE_MODEL_ID,
        "messages": converse_messages,
        "inferenceConfig": {"maxTokens": CLAUDE_MAX_TOKENS},
    }
    
    if system_prompt.strip():
        kwargs["system"] = [{"text": system_prompt.strip()}]
        
    tool_config = _to_bedrock_converse_tools(tools)
    if tool_config:
        kwargs["toolConfig"] = tool_config

    response = await asyncio.to_thread(client.converse, **kwargs)
    
    message = response.get("output", {}).get("message", {})
    content_blocks = message.get("content", [])
    
    text_blocks = []
    tool_uses = []
    
    for block in content_blocks:
        if "text" in block:
            text_blocks.append(block["text"].strip())
        elif "toolUse" in block:
            tool_uses.append({
                "id": block["toolUse"]["toolUseId"],
                "name": block["toolUse"]["name"],
                "input": block["toolUse"]["input"],
            })
            
    text = "\n".join(text_blocks).strip()
    
    # Execute tools
    tasks = []
    for tool_use in tool_uses:
        tool_name = tool_use["name"]
        arguments = tool_use["input"]
        
        # Un-wrap hallucinated tool arg formats:
        #   {'query': {'type': 'string', 'value': 'hi'}}  → {'query': 'hi'}
        #   {'query': {'query': 'transformers vs RNNs'}}   → {'query': 'transformers vs RNNs'}
        for k, v in list(arguments.items()):
            if isinstance(v, dict):
                if "value" in v:
                    arguments[k] = v["value"]
                elif k in v:
                    arguments[k] = v[k]
                
        print(f"[CLAUDE TOOL] Exec -> {tool_name}({arguments})")
        tasks.append(execute_tool(tool_name, arguments))
        
    tool_output = ""
    if tasks:
        results = await asyncio.gather(*tasks)
        tool_output = "\n".join(str(result) for result in results)

    return {
        "text": text,
        "tool_uses": tool_uses,
        "tool_output": tool_output,
        "raw": response,
    }


async def _call_ollama(messages: list[dict], tools_to_send: list[dict] | None = None) -> str:
    """Call Qwen through Ollama for chat shortcut or tool routing."""
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_ctx": 2048, "num_predict": 512},
                    "keep_alive": "60m",
                }
                if tools_to_send:
                    payload["tools"] = tools_to_send

                response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            router_msg = response.json()["message"]

            if router_msg.get("tool_calls"):
                tasks = []
                for tool_call in router_msg["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    arguments = tool_call["function"]["arguments"]
                    print(f"[TOOL] Parallel Exec -> {tool_name}({arguments})")
                    tasks.append(execute_tool(tool_name, arguments))

                results = await asyncio.gather(*tasks)
                return "\n".join(str(result) for result in results)

            import re
            reply = router_msg.get("content", "").strip()
            
            # Enforce newlines for markdown rendering if the LLM clumps them
            # 1. Fix bullet points (convert literal • or - without newlines to \n* )
            reply = re.sub(r'(?<!\n)(?<!^)\s*[•]\s*', r'\n* ', reply)
            # 2. Fix bold tags that have trailing/leading spaces inside them (e.g., ** text ** -> **text**)
            reply = re.sub(r'\*\*\s+(.*?)\s+\*\*', r'**\1**', reply)
            reply = re.sub(r'\*\*(.*?)\s+\*\*', r'**\1**', reply)
            reply = re.sub(r'\*\*\s+(.*?)\*\*', r'**\1**', reply)
            # 3. Add newlines before bold tags if clumped
            reply = re.sub(r'(?<!\n)(?<!^)\s*\*\*', r'\n\n**', reply)
            
            return reply or "I'm sorry sir, I couldn't formulate a response."

        except Exception:
            import traceback
            print(f"[OLLAMA ERROR] Attempt {attempt+1} failed:")
            print(traceback.format_exc())
            if attempt == 0:
                continue
            raise


# (Removed old _tier2_classify, _tier3_route, and _chat_response)

# ── Retina Module (Vision) ────────────────────────────────

def _classify_vision_intent(message: str, conversation_history: list) -> bool:
    """Two-stage intent check for visual reasoning."""
    msg_lower = message.lower()
    
    # Stage 1: Keyword Signal (broad enough for natural phrasings)
    vision_keywords = [
        "look at", "can you see", "do you see", "what do you see", "see this",
        "my screen", "the screen", "your screen", "on screen", "on my screen",
        "check my screen", "check out my screen", "check the screen",
        "view my screen", "scan my screen", "read my screen", "analyze my screen",
        "analyse my screen", "screenshot", "screen shot", "this screen",
        "what is this", "what's this", "what's on", "describe my", "describe this",
        "look here", "watch my screen",
    ]
    if not any(kw in msg_lower for kw in vision_keywords):
        return False
        
    # Stage 2: Scope Check (reject if code blocks, URLs, or referring to attachments/history)
    if "```" in message:
        return False
        
    url_pattern = r"(https?://\S+|www\.\S+)"
    if re.search(url_pattern, message):
        return False
        
    history_keywords = ["the above", "previous message", "that message", "what you just said"]
    if any(kw in msg_lower for kw in history_keywords):
        return False
        
    return True

async def _call_maverick_vision(image_b64: str, user_message: str) -> str | None:
    """Route image+text to Bedrock Llama 4 Maverick Converse API."""
    import base64
    from botocore.exceptions import ClientError
    try:
        from PIL import UnidentifiedImageError
    except ImportError:
        UnidentifiedImageError = Exception

    try:
        client = _get_bedrock_client()
        image_bytes = base64.b64decode(image_b64)
        
        preamble = "Analyze the following screenshot with your usual precision. Lead with the most actionable observation. You may be witty, but be useful first.\n\n"
        
        response = await asyncio.to_thread(
            client.converse,
            modelId=VISION_MODEL_ID,
            system=[{"text": JARVIS_CHAT_PROMPT}],
            messages=[{
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {"bytes": image_bytes}
                        }
                    },
                    {"text": preamble + user_message}
                ]
            }],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.3}
        )
        
        message = response.get("output", {}).get("message", {})
        content_blocks = message.get("content", [])
        
        text_blocks = [block["text"] for block in content_blocks if "text" in block]
        text = "\n".join(text_blocks).strip()
        
        print(f"[VISION] Maverick response received. {response.get('usage', {}).get('totalTokens', 0)} tokens.")
        return text

    except ClientError as e:
        print(f"[VISION] Error: ClientError — routing to text fallback. {e}")
        return None
    except UnidentifiedImageError as e:
        print(f"[VISION] Error: UnidentifiedImageError — routing to text fallback. {e}")
        return None
    except Exception as e:
        import traceback
        print(f"[VISION] Error: {e} — routing to text fallback.")
        print(traceback.format_exc())
        return None


async def _call_maverick_vision_chat(chat_history: list[dict], user_message: str, overlay_image_b64: str | None = None) -> str:
    """
    Executes a direct, multi-turn visual chat conversation with Llama 4 Maverick (Vision).
    NO tools are bound, and NO agent graph is used, entirely eliminating tool hallucinations
    and agent loop overhead for visual overlay Q&A.
    """
    from botocore.exceptions import ClientError
    import asyncio
    
    try:
        client = _get_bedrock_client()
        
        # Translate history to Bedrock Converse messages format
        bedrock_messages = []
        for i, msg in enumerate(chat_history):
            role = msg["role"]
            content = msg["content"]
            
            # Map role
            if role == "assistant":
                role = "assistant"
            else:
                role = "user"
                
            # If it's the first message and we have an image, inject it
            if i == 0 and overlay_image_b64:
                import base64
                image_bytes = base64.b64decode(overlay_image_b64)
                content_list = [
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {"bytes": image_bytes}
                        }
                    },
                    {"text": str(content)}
                ]
            else:
                content_list = [{"text": str(content)}]
                
            bedrock_messages.append({
                "role": role,
                "content": content_list
            })
            
        print(f"[Vision Chat] Routing to vision model ({VISION_MODEL_ID}) — no tools, no agent loops.")

        response = await asyncio.to_thread(
            client.converse,
            modelId=VISION_MODEL_ID,
            system=[{"text": JARVIS_CHAT_PROMPT}],
            messages=bedrock_messages,
            inferenceConfig={"maxTokens": 1024, "temperature": 0.3}
        )
        
        message = response.get("output", {}).get("message", {})
        content_blocks = message.get("content", [])
        text_blocks = [block["text"] for block in content_blocks if "text" in block]
        reply = "\n".join(text_blocks).strip()
        
        print(f"[Vision Chat] Received visual response successfully.")
        return reply
        
    except Exception as e:
        import traceback
        print(f"[Vision Chat ERROR] Vision model call failed: {e}")
        traceback.print_exc()
        return f"Sir, I encountered an issue accessing my visual reasoning system: {str(e)[:180]}"


# ── Main Entry Point ──────────────────────────────────────

async def _route_hybrid_llm(
    user_message: str,
    session_id: str,
    memory_context: str,
    append_message,
    get_session_history,
) -> str:
    """Route between local chat, Bedrock primary, and local fallback."""
    system_prompt = JARVIS_CHAT_PROMPT
    
    chat_history = get_session_history(session_id, limit=6)
    
    # Inject memory context into the user's latest message to preserve constant system prompt for caching
    if memory_context and chat_history and chat_history[-1]["role"] == "user":
        chat_history[-1]["content"] += f"\n\n--- User Memory ---\n{memory_context}\n--- End Memory ---"

    messages = [{"role": "system", "content": system_prompt}] + chat_history

    complex_query = is_complex_query(user_message)

    if _is_chat_shortcut(user_message) and not complex_query:
        print("[TIER 2] Chat Shortcut -> Ollama/Llama without tools")
        try:
            # Strip heavy tool schemas for chat
            chat_system_prompt = system_prompt.split("═══════════════════════════════════════════════════════════════")[0].strip()
            chat_messages = [{"role": "system", "content": chat_system_prompt}] + chat_history
            reply = await _call_ollama(chat_messages, tools_to_send=None)
            CACHE[user_message] = reply
            append_message(session_id, "assistant", reply)
            return reply
        except Exception:
            import traceback
            print("[CHAT SHORTCUT ERROR] Ollama chat failed:")
            print(traceback.format_exc())
            return "I'm sorry sir, my neural network seems to be offline."

    suggested_intents = _get_suggested_intents(user_message)
    tools_to_send = []
    if "ALL" in suggested_intents:
        tools_to_send = TOOL_SCHEMAS
    else:
        for intent in suggested_intents:
            tools_to_send.extend(get_schemas_for_intent(intent))
    
    # Deduplicate tools
    seen_tools = set()
    deduped_tools = []
    for t in tools_to_send:
        name = t["function"]["name"]
        if name not in seen_tools:
            deduped_tools.append(t)
            seen_tools.add(name)
    tools_to_send = deduped_tools

    if USE_CLAUDE and complex_query:
        print("[BRAIN] Calling Bedrock...")
        try:
            claude_result = await call_claude(messages, tools=tools_to_send)
            reply_parts = []
            if claude_result["text"]:
                reply_parts.append(claude_result["text"])
            if claude_result["tool_output"]:
                reply_parts.append(claude_result["tool_output"])

            reply = "\n".join(reply_parts).strip() or "I'm sorry sir, I couldn't formulate a response."
            CACHE[user_message] = reply
            append_message(session_id, "assistant", reply)
            return reply
        except Exception:
            import traceback
            print("[FALLBACK] Bedrock failed, engaging local brain.")
            print(traceback.format_exc())

    print(f"[TIER 3] Local Fallback Router -> loading {len(tools_to_send) if tools_to_send else 0} tools ({suggested_intents})")
    try:
        reply = await _call_ollama(messages, tools_to_send=tools_to_send)
        CACHE[user_message] = reply
        append_message(session_id, "assistant", reply)
        return reply
    except Exception:
        import traceback
        print("[UNIFIED BRAIN ERROR] Local tool router failed:")
        print(traceback.format_exc())
        return "I'm sorry sir, my neural network seems to be offline."


async def generate_response(user_message: str, session_id: str = "default") -> str:
    """
    Hybrid Brain Pipeline.

    1. Tier 1: Regex fast-path
    2. Tier 2: Qwen chat shortcut without tools
    3. Tier 2.5: Claude Opus for complex reasoning
    4. Tier 3: Qwen tool router
    """
    from services.session_service import append_message, get_session_history
    from workflows.wa_send_workflow import get_active_workflow
    user_appended = False

    # ── Dedicated Visual Q&A Overlay Route (Maverick Vision Only, No Tools) ──
    if session_id == "overlay":
        append_message(session_id, "user", user_message)
        chat_history = get_session_history(session_id, limit=6)
        
        overlay_image_b64 = None
        try:
            from services.overlay_context_service import list_overlay_sessions, get_overlay_context
            sessions = list_overlay_sessions(limit=1)
            if sessions:
                ctx = get_overlay_context(sessions[0]["context_id"])
                if ctx and ctx.get("image_base64"):
                    overlay_image_b64 = ctx["image_base64"]
                    print(f"[Vision] Loaded active crop context ({len(overlay_image_b64)} bytes) for Maverick.")
        except Exception as e:
            print(f"[Vision ERROR] Failed to load crop context for overlay: {e}")
            
        reply = await _call_maverick_vision_chat(chat_history, user_message, overlay_image_b64)
        append_message(session_id, "assistant", reply)
        return reply

    # ── Workflow Safety & Continuation ──
    from datetime import datetime, timedelta
    active_wf = get_active_workflow(session_id)
    
    # Timeout handling (2 mins)
    if active_wf and hasattr(active_wf, 'created_at'):
        if datetime.now() - active_wf.created_at > timedelta(minutes=2):
            from workflows.wa_send_workflow import clear_workflow
            clear_workflow(session_id)
            active_wf = None

    if active_wf and active_wf.status in ("pending_confirm", "pending_disambiguation"):
        append_message(session_id, "user", user_message)
        reply = await _handle_wa_continuation(active_wf, user_message)
        append_message(session_id, "assistant", reply)
        return reply

    # ── Tier 1: Regex Fast-Path (0ms) ──
    try:
        import importlib

        mission_module = importlib.import_module("workflows.mission_graph")

        active_mission = mission_module.get_active_mission(session_id)
        if active_mission:
            if datetime.now() - active_mission.get("created_at", datetime.now()) > timedelta(minutes=15):
                mission_module.clear_mission(session_id)
            elif active_mission.get("pending_confirmation"):
                append_message(session_id, "user", user_message)
                reply = await mission_module.handle_mission_confirmation(session_id, user_message)
                append_message(session_id, "assistant", reply)
                return reply
    except Exception as exc:
        print(f"[Mission] Confirmation route unavailable: {exc}")

    if _looks_like_finance_report(user_message):
        append_message(session_id, "user", user_message)
        user_appended = True
        try:
            reply = await _handle_finance_report(user_message)
        except Exception as exc:
            import traceback

            print(f"[Finance Report] Deterministic workflow failed, falling back: {exc}")
            traceback.print_exc()
        else:
            append_message(session_id, "assistant", reply)
            return reply

    if _looks_like_marketplace_price_compare(user_message):
        append_message(session_id, "user", user_message)
        user_appended = True
        try:
            reply = await _handle_marketplace_price_compare(user_message)
        except Exception as exc:
            import traceback

            print(f"[Marketplace Compare] Deterministic workflow failed, falling back: {exc}")
            traceback.print_exc()
        else:
            append_message(session_id, "assistant", reply)
            return reply

    force_react_research = _needs_react_research(user_message)

    # LLM router (flag-gated): browser/tool -> force Tier 3; only allow mission mode if
    # the router says so (or it's disabled/undecided, '' = legacy behavior unchanged).
    _route = await classify_route(user_message)
    if _route in (ROUTE_BROWSER, ROUTE_TOOL):
        force_react_research = True
    _router_allow_mission = _route in (ROUTE_MISSION, "")

    # ── Information Sufficiency Gate (flag-gated by JARVIS_CLARIFY, fail-open) ──
    # Ask one round of clarification for incomplete browser/tool/mission requests
    # BEFORE any execution. Chat/vision routes skip this; trivial commands skip via
    # the module's heuristic fast-path; any error proceeds normally.
    if _route in (ROUTE_BROWSER, ROUTE_TOOL, ROUTE_MISSION, ""):
        from services.clarification import needs_clarification, format_clarification_response
        _history = get_session_history(session_id, limit=6)
        _clar = await needs_clarification(user_message, session_history=_history)
        if not _clar.sufficient:
            if not user_appended:
                append_message(session_id, "user", user_message)
                user_appended = True
            reply = format_clarification_response(_clar)
            append_message(session_id, "assistant", reply)
            return reply

    if not force_react_research and _router_allow_mission and _looks_like_mission_goal(user_message):
        append_message(session_id, "user", user_message)
        user_appended = True
        try:
            import importlib

            mission_module = importlib.import_module("workflows.mission_graph")

            mission_state = await mission_module.mission_graph_app.ainvoke(
                {"user_goal": user_message, "session_id": session_id},
                {"configurable": {"thread_id": f"{session_id}:mission:{uuid.uuid4().hex[:8]}" }},
            )
            if mission_state.get("pending_confirmation"):
                mission_module.store_active_mission(session_id, mission_state)

            reply = mission_state.get("final_answer", "Mission completed, sir.")
            append_message(session_id, "assistant", reply)
            return reply
        except Exception as exc:
            import traceback

            print(f"[Mission] Mission graph failed before Tier1, falling back: {exc}")
            traceback.print_exc()

    if not force_react_research:
        fast_result = await _tier1_regex(user_message, session_id)
        if fast_result:
            append_message(session_id, "assistant", fast_result)
            return fast_result

    # ── Vision Intent Check (Retina Module) ──
    global _LAST_VISION_TRIGGER
    
    history = get_session_history(session_id, limit=6)
    text_fallback_prefix = ""
    
    if _classify_vision_intent(user_message, history):
        from services.vision_service import _capture_retina_view
        print("[VISION] Intent detected.")
        current_time = time.time()
        
        if current_time - _LAST_VISION_TRIGGER < 15.0:
            reply = "Sir, I've only just finished looking. Patience is a virtue, even for AIs."
            print("[VISION] Debounce check: FAILED.")
            append_message(session_id, "assistant", reply)
            return reply
            
        print("[VISION] Debounce check: OK.")
        _LAST_VISION_TRIGGER = current_time
        
        img_b64, err = _capture_retina_view()
        if err:
            if "sensitive credentials" in err:
                append_message(session_id, "assistant", err)
                return err
            else:
                text_fallback_prefix = err + " "
        else:
            vision_reply = await _call_maverick_vision(img_b64, user_message)
            if vision_reply:
                append_message(session_id, "assistant", vision_reply)
                return vision_reply
            else:
                text_fallback_prefix = "Sir, my visual cortex appears to be offline. I can still assist you in the traditional, text-based, decidedly less impressive fashion. "

    # ── Memory Pipeline (Optimized) ──
    mem_store_triggers = ["remember", "my name is", "note that", "save this"]
    mem_retrieve_triggers = ["my", "remember", "who am i", "what is my", "do you know"]
    
    msg_lower = user_message.lower()
    if any(x in msg_lower for x in mem_store_triggers):
        print(f"[MEMORY] Storing: '{user_message}'")
        await store_memory(user_message)
    
    if not user_appended:
        append_message(session_id, "user", user_message)
    
    memory_context = ""
    if any(x in msg_lower for x in mem_retrieve_triggers):
        memories = await retrieve_memory(user_message)
        if memories:
            print(f"[MEMORY] Retrieved: {memories}")
            memory_context = memories

    # ── Response Caching (skip tool-action responses to prevent poisoning) ──
    if not force_react_research and _router_allow_mission and not user_appended and _looks_like_mission_goal(user_message):
        try:
            import importlib

            mission_module = importlib.import_module("workflows.mission_graph")

            mission_state = await mission_module.mission_graph_app.ainvoke(
                {"user_goal": user_message, "session_id": session_id},
                {"configurable": {"thread_id": f"{session_id}:mission:{uuid.uuid4().hex[:8]}"}},
            )
            if mission_state.get("pending_confirmation"):
                mission_module.store_active_mission(session_id, mission_state)

            reply = mission_state.get("final_answer", "Mission completed, sir.")
            append_message(session_id, "assistant", reply)
            return reply
        except Exception as exc:
            import traceback

            print(f"[Mission] Mission graph failed, falling back to Tier3: {exc}")
            traceback.print_exc()

    if user_message in CACHE:
        reply = CACHE[user_message]
        # Don't serve cached tool-action responses (browser, file, etc.)
        tool_patterns = ["Opening browser", "Searching the web", "quote_from_bytes"]
        if not any(p in reply for p in tool_patterns):
            print(f"[CACHE] Hit: '{user_message}' -> '{reply[:30]}...'")
            append_message(session_id, "assistant", reply)
            return reply
        else:
            print(f"[CACHE] Skipping stale tool-action cache for: '{user_message[:40]}'")
            del CACHE[user_message]

    # ── Tier 3 LangGraph ReAct Agent (Multi-Tool) ──
    langgraph_intents = [
        # Browser
        "search", "open", "find", "google", "stock", "browser", "bigbasket",
        "amazon", "flipkart", "zomato", "swiggy",
        # WhatsApp
        "whatsapp", "message", "text", "who messaged", "who texted", "missed call",
        # File system  
        "read file", "write file", "save", "create file", "list files", "find file",
        # Weather
        "weather", "temperature", "rain", "forecast",
        # Voice
        "voice", "speak", "pitch", "speaking rate", "mute",
        # Monitoring
        "diagnostic", "cpu", "ram", "metrics", "logs", "processes", "disk", "uptime",
    ]
    is_langgraph_task = any(b in msg_lower for b in langgraph_intents)
    
    chat_history = get_session_history(session_id, limit=6)
    
    # If the router explicitly classified this as a chat turn, bypass Tier 3 and keep it local!
    if _route == ROUTE_CHAT:
        is_langgraph_task = False
        complex_query = False
    else:
        complex_query = is_complex_query(user_message)
    
    if is_langgraph_task or complex_query:
        # Amazon Nova Pro for Tier 3 — multimodal + Converse-API tool use, far more
        # reliable than Llama for the browser ReAct loop. us-east-1 on-demand requires
        # the cross-region inference-profile id (the "us." prefix); the bare
        # amazon.nova-pro-v1:0 errors with "use an inference profile" and falls back.
        # Override without editing code via JARVIS_AGENT_MODEL_ID.
        selected_model = os.getenv("JARVIS_AGENT_MODEL_ID", "us.amazon.nova-pro-v1:0")
        print(f"\n[Tier3] Routing -> {selected_model}")
        try:
            with open(r"c:\Users\Rudra\holo-core-nexus\backend\data\graph_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== [Tier3 START {time.strftime('%H:%M:%S')}] model={selected_model} query={user_message[:80]} ===\n")
        except Exception:
            pass
        from workflows.master_graph import master_graph_app
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        from langgraph.errors import GraphRecursionError

        # Translate history to LangChain format.
        # Browser/file workflows must be isolated from stale chat turns; otherwise a
        # failed tool call can cause the model to complete an older task instead.
        lc_messages = [SystemMessage(content=JARVIS_CHAT_PROMPT)]
        has_active_clarification = any("Before I proceed, sir" in m.get("content", "") for m in chat_history if m.get("role") == "assistant")

        if is_langgraph_task and not has_active_clarification:
            lc_messages.append(HumanMessage(content=user_message))
        else:
            for msg in chat_history:
                if msg["role"] == "user":
                    lc_messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    lc_messages.append(AIMessage(content=msg["content"]))

            if not chat_history or chat_history[-1].get("content") != user_message:
                lc_messages.append(HumanMessage(content=user_message))
            
        try:
            graph_start = time.time()
            
            # Max 150 steps — LangGraph counts each node transition as 1 step (each loop takes ~4 steps)
            final_state = await master_graph_app.ainvoke(
                {"messages": lc_messages, "iteration": 0}, 
                {
                    "recursion_limit": 150,
                    "configurable": {
                        "model_id": selected_model,
                        "route": _route,  # router decision -> route-scoped MCP tool binding
                        "thread_id": f"{session_id}:{uuid.uuid4().hex}"  # Fresh scratchpad with session traceability
                    }
                }
            )
            
            elapsed = round(time.time() - graph_start, 1)
            print(f"[Tier3] LangGraph completed in {elapsed}s")
            
            final_message = final_state["messages"][-1].content
            if isinstance(final_message, list):
                # Sometimes Bedrock returns a list of blocks
                final_message = " ".join(b.get("text", "") for b in final_message if isinstance(b, dict) and "text" in b)
            
            # Global markdown fix
            import re
            final_message = re.sub(r'(?<!\n)(?<!^)\s*[•]\s*', r'\n* ', final_message)
            final_message = re.sub(r'(?<!\n)(?<!^)\s*(\d+\.)\s', r'\n\n\1 ', final_message)
            final_message = re.sub(r'\*\*\s+(.*?)\s+\*\*', r'**\1**', final_message)
            final_message = re.sub(r'\*\*(.*?)\s+\*\*', r'**\1**', final_message)
            final_message = re.sub(r'\*\*\s+(.*?)\*\*', r'**\1**', final_message)
            final_message = re.sub(r'(?<!\n)(?<!^)\s*\*\*', r'\n\n**', final_message)
            
            print(f"[Tier3] LangGraph completed successfully.")
            if text_fallback_prefix:
                final_message = text_fallback_prefix + final_message
            append_message(session_id, "assistant", final_message)
            return final_message
            
        except GraphRecursionError:
            print("[Graph] Max iteration limit reached")
            fallback_msg = "I could not complete the task safely within the allowed reasoning steps."
            append_message(session_id, "assistant", fallback_msg)
            return fallback_msg
            
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            print(f"[Graph ERROR] ReAct loop failed: {e}")
            print(tb_str)
            print("[Tier3] Falling back to legacy routing...")
            try:
                with open(r"c:\Users\Rudra\holo-core-nexus\backend\data\graph_debug.log", "a", encoding="utf-8") as f:
                    f.write(f"\n--- [Tier3 CRASH {time.strftime('%H:%M:%S')}] {e} ---\n{tb_str}\n")
            except Exception:
                pass

    # ── Unified Brain Call (Legacy Routing) ──
    text_reply = await _route_hybrid_llm(
        user_message=user_message,
        session_id=session_id,
        memory_context=memory_context,
        append_message=append_message,
        get_session_history=get_session_history,
    )
    
    if text_fallback_prefix:
        # Prepend the fallback apology to the generated text reply
        # Note: the append_message inside _route_hybrid_llm will have stored the reply WITHOUT the prefix.
        # We'd have to edit the history manually to keep it perfectly consistent, but for spoken output, this is fine.
        text_reply = text_fallback_prefix + text_reply
        
    return text_reply


# ── WhatsApp Send Workflow Orchestration ──────────────────

async def _handle_wa_send_workflow(
    user_message: str,
    session_id: str,
    contact_query: str = "",
    message_intent: str = "",
) -> str:
    """
    Orchestrate the outbound WA messaging workflow up to the confirmation prompt.
    Steps: extract params (LLM or pre-extracted) -> resolve contact -> draft message (LLM) -> confirm.
    """
    from workflows.wa_send_workflow import (
        create_workflow,
        node_extract_params,
        node_resolve_contact,
        node_draft_message,
        node_confirm_send,
        node_handle_failure,
        build_disambiguation_prompt,
        clear_workflow,
    )

    # 1. Create workflow state
    state = create_workflow(session_id, user_message)

    # 2. Extract contact + message intent
    if contact_query and message_intent:
        # Pre-extracted by Tier 1 regex — skip LLM call
        state.contact_query = contact_query
        state.message_intent = message_intent
        print(f"[WA_SEND] Using pre-extracted params: contact='{contact_query}', intent='{message_intent}'")
    else:
        # Use LLM to extract (Tier 2 WA_SEND path)
        state = await node_extract_params(state)
        if state.status == "error":
            return node_handle_failure(state)

    # 3. Resolve contact via Baileys connector
    state = await node_resolve_contact(state)
    if state.status == "error":
        return node_handle_failure(state)
    if state.status == "pending_disambiguation":
        return build_disambiguation_prompt(state)

    # 4. Draft message (LLM)
    state = await node_draft_message(state)
    if state.status == "error":
        return node_handle_failure(state)

    # 5. Build confirmation prompt
    return node_confirm_send(state)


async def _handle_wa_continuation(wf, user_message: str) -> str:
    """
    Handle follow-up for pending WA workflows (confirmation or disambiguation).
    """
    from workflows.wa_send_workflow import (
        node_handle_confirmation,
        node_send_message,
        node_draft_message,
        node_confirm_send,
        node_handle_failure,
        handle_disambiguation_response,
        clear_workflow,
    )

    if wf.status == "pending_confirm":
        # Process yes/no
        wf = node_handle_confirmation(wf, user_message)

        if wf.confirmed:
            # Send the message
            wf = await node_send_message(wf)
            if wf.status == "sent":
                contact_name = wf.selected_contact
                clear_workflow(wf.session_id)
                return f"Done, sir. Message sent to {contact_name}."
            else:
                return node_handle_failure(wf)
        else:
            clear_workflow(wf.session_id)
            return "Understood, sir. Message cancelled."

    if wf.status == "pending_disambiguation":
        # Process contact selection
        wf = handle_disambiguation_response(wf, user_message)

        if wf.status == "cancelled":
            clear_workflow(wf.session_id)
            return "Understood, sir. Message cancelled."

        if wf.status == "error":
            clear_workflow(wf.session_id)
            return node_handle_failure(wf)

        # Contact resolved — continue workflow: draft -> confirm
        wf = await node_draft_message(wf)
        if wf.status == "error":
            clear_workflow(wf.session_id)
            return node_handle_failure(wf)

        return node_confirm_send(wf)

    # Shouldn't reach here, but clean up
    clear_workflow(wf.session_id)
    return "I seem to have lost track of our conversation, sir. Please try again."
