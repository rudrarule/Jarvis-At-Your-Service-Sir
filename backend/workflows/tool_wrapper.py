"""
tool_wrapper.py — LangChain tool wrappers for J.A.R.V.I.S. LangGraph Agent
Wraps browser, whatsapp, file system, and weather tools into LangChain @tool decorators.
"""

from langchain_core.tools import tool
from tools.browser_tool import (
    open_url, get_current_url, get_page_title, 
    extract_visible_text, wait_for_navigation,
    inject_element_markers, interact_by_id, scroll_page, go_back
)
from tools.whatsapp_tool import (
    whatsapp_briefing as _wa_briefing,
    whatsapp_unread as _wa_unread,
    whatsapp_missed_calls as _wa_missed,
    whatsapp_send as _wa_send,
)
from tools.file_system_tool import (
    read_file as _read_file,
    write_file as _write_file,
    list_directory as _list_dir,
    search_files as _search_files,
)
from tools.weather_tool import get_weather as _get_weather


# ═══════════════════════════════════════════════════════════
# BROWSER TOOLS
# ═══════════════════════════════════════════════════════════

@tool
async def browser_open_url(url: str) -> dict:
    """
    Opens the browser to a specific URL. 
    Use this to navigate to a new website. Make sure the URL starts with http:// or https://.
    Returns observation on success or failure.
    """
    return await open_url(url)

@tool
async def browser_interact(element_id: int, action: str, text: str = "") -> dict:
    """
    Interact with a specific UI element using its numerical ID from browser_observe.
    Actions: 'click', 'type'.
    If action is 'type', provide the 'text' argument.
    Use this to click buttons, follow links, or fill forms flawlessly.
    """
    return await interact_by_id(element_id, action, text)

@tool
async def browser_scroll(direction: str = "down") -> dict:
    """
    Scrolls the webpage up or down. Valid directions: 'up', 'down'.
    Use this if the element you need is not currently visible in the observation.
    """
    return await scroll_page(direction)

@tool
async def browser_observe() -> dict:
    """
    Extracts a compressed, structured observation of the current webpage.
    Returns the page title, URL, summarized visible text, and a numbered list of interactive elements.
    You MUST use the returned element IDs with browser_interact to click or type.
    """
    url_res = await get_current_url()
    title_res = await get_page_title()
    text_res = await extract_visible_text()
    markers_res = await inject_element_markers()
    
    visible_text = text_res.get("data", {}).get("text", "")
    compressed_text = visible_text[:1000] + ("..." if len(visible_text) > 1000 else "")
    
    elements_list = (markers_res.get("data") or {}).get("elements", [])
    inputs = [e for e in elements_list if e.get("tag") == "input"]
    buttons = [e for e in elements_list if e.get("tag") == "button"]
    links = [e for e in elements_list if e.get("tag") == "a"]
    print(f"[Observation] {len(elements_list)} elements: {len(inputs)} inputs, {len(buttons)} buttons, {len(links)} links")
    
    return {
        "success": True,
        "action": "browser_observe",
        "observation": "Extracted structured page data and interactive element IDs",
        "data": {
            "url": (url_res.get("data") or {}).get("url", ""),
            "title": (title_res.get("data") or {}).get("title", ""),
            "summary": compressed_text,
            "interactive_elements": (markers_res.get("data") or {}).get("elements", [])
        }
    }

@tool
async def browser_get_status() -> dict:
    """
    Gets the current URL and page title to understand where the browser is currently located.
    """
    url_res = await get_current_url()
    title_res = await get_page_title()
    return {
        "success": url_res.get("success") or title_res.get("success"), 
        "action": "browser_get_status", 
        "observation": "Extracted current status of the browser.",
        "data": {
            "url": url_res.get("data", {}).get("url") if url_res.get("success") else None,
            "title": title_res.get("data", {}).get("title") if title_res.get("success") else None
        }
    }

@tool
async def browser_go_back() -> dict:
    """
    Clicks the browser's 'Back' button to return to the previous page.
    Use this if you clicked the wrong link, encountered an error, or need to return to search results.
    """
    return await go_back()


# ═══════════════════════════════════════════════════════════
# WHATSAPP TOOLS
# ═══════════════════════════════════════════════════════════

@tool
async def whatsapp_check_messages() -> str:
    """
    Check unread WhatsApp messages and missed calls. Returns a summary of who messaged you.
    Use when user says 'check my messages', 'who messaged me', 'whatsapp briefing'.
    """
    print("[Tool] Checking WhatsApp messages...")
    return await _wa_briefing()

@tool
async def whatsapp_send_message(contact: str, message: str) -> str:
    """
    Send a WhatsApp message to a contact.
    contact: the person's name (e.g. 'mom', 'Rahul') or phone number.
    message: the message text to send.
    Use when user says 'text mom', 'send whatsapp to X', 'tell X that Y'.
    """
    print(f"[Tool] Sending WhatsApp to '{contact}': '{message[:40]}...'")
    return await _wa_send(contact, message)


# ═══════════════════════════════════════════════════════════
# FILE SYSTEM TOOLS
# ═══════════════════════════════════════════════════════════

@tool
def file_read(path: str) -> str:
    """
    Read a file from the workspace. Returns the file contents.
    The path is relative to the workspace directory (e.g. 'notes.txt', 'projects/readme.md').
    Allowed extensions: .txt, .md, .json, .py
    """
    print(f"[Tool] Reading file: {path}")
    return _read_file(path)

@tool
def file_write(path: str, content: str) -> str:
    """
    Write or overwrite a file in the workspace.
    The path is relative to the workspace directory (e.g. 'shopping_list.txt').
    Allowed extensions: .txt, .md, .json, .py
    """
    print(f"[Tool] Writing file: {path}")
    return _write_file(path, content)

@tool
def file_list(path: str = "") -> str:
    """
    List files and folders in a workspace directory.
    Leave path empty to list the root workspace. Use a relative path for subdirectories.
    """
    print(f"[Tool] Listing directory: {path or 'workspace/'}")
    return _list_dir(path)

@tool
def file_search(query: str) -> str:
    """
    Search for files by name in the workspace.
    Returns matching file paths. Use when user says 'find my resume', 'where is config.json'.
    """
    print(f"[Tool] Searching files: {query}")
    return _search_files(query)


# ═══════════════════════════════════════════════════════════
# WEATHER TOOLS
# ═══════════════════════════════════════════════════════════

@tool
def weather_check(location: str = "") -> str:
    """
    Get the current weather for a location.
    If no location provided, returns weather for the user's current location.
    Examples: 'Faridabad', 'New York', 'London'.
    """
    print(f"[Tool] Getting weather for: {location or 'current location'}")
    return _get_weather(location)


# ═══════════════════════════════════════════════════════════
# TOOL GROUPS — used by master_graph.py
# ═══════════════════════════════════════════════════════════

BROWSER_TOOLS = [
    browser_open_url,
    browser_interact,
    browser_scroll,
    browser_observe,
    browser_get_status,
    browser_go_back
]

WHATSAPP_TOOLS = [
    whatsapp_check_messages,
    whatsapp_send_message,
]

FILE_TOOLS = [
    file_read,
    file_write,
    file_list,
    file_search,
]

WEATHER_TOOLS = [
    weather_check,
]

# All tools available to the LangGraph agent
ALL_TOOLS = BROWSER_TOOLS + WHATSAPP_TOOLS + FILE_TOOLS + WEATHER_TOOLS
