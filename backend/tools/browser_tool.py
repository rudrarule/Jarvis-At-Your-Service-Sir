"""
browser_tool.py — Autonomous Browser Interaction Layer
Powered by async Playwright. Maintains a persistent stateful browser session
to support LangGraph ReAct agent loops and multi-step workflows.
"""
import asyncio
import os
import urllib.parse
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout, Page, Browser, BrowserContext

def _format_response(success: bool, action: str, observation: str, data: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "success": success,
        "action": action,
        "observation": observation,
        "data": data,
        "error": error
    }

class BrowserStateManager:
    _playwright = None
    _browser: Optional[Browser] = None
    _context: Optional[BrowserContext] = None
    _page: Optional[Page] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_page(cls) -> Page:
        async with cls._lock:
            if cls._page and not cls._page.is_closed():
                return cls._page
            
            if not cls._playwright:
                cls._playwright = await async_playwright().start()
            
            headless = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
            user_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "browser_user_data"))
            
            if not cls._context:
                cls._context = await cls._playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    viewport={'width': 1280, 'height': 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"]
                )
            
            cls._page = cls._context.pages[0] if cls._context.pages else await cls._context.new_page()
            
            # Anti-detection stealth scripts
            await cls._page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return cls._page

    @classmethod
    async def close_all(cls):
        async with cls._lock:
            if cls._context:
                await cls._context.close()
                cls._context = None
            if cls._browser: # Keep for backwards compatibility if needed
                await cls._browser.close()
                cls._browser = None
            if cls._playwright:
                await cls._playwright.stop()
                cls._playwright = None
            cls._page = None

# --- Navigation & Control ---

async def open_url(url: str) -> dict:
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    try:
        page = await BrowserStateManager.get_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return _format_response(True, "open_url", f"Navigated to {url}", {"url": page.url})
    except Exception as e:
        return _format_response(False, "open_url", f"Failed to navigate to {url}", error=str(e))

async def get_current_url() -> dict:
    try:
        page = await BrowserStateManager.get_page()
        return _format_response(True, "get_current_url", f"Current URL is {page.url}", {"url": page.url})
    except Exception as e:
        return _format_response(False, "get_current_url", "Failed to get current URL", error=str(e))

async def go_back() -> dict:
    try:
        page = await BrowserStateManager.get_page()
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
        return _format_response(True, "go_back", f"Navigated back to {page.url}", {"url": page.url})
    except Exception as e:
        return _format_response(False, "go_back", "Failed to navigate back", error=str(e))

async def refresh_page() -> dict:
    try:
        page = await BrowserStateManager.get_page()
        await page.reload(wait_until="domcontentloaded", timeout=15000)
        return _format_response(True, "refresh_page", "Page refreshed")
    except Exception as e:
        return _format_response(False, "refresh_page", "Failed to refresh", error=str(e))

async def scroll_page(direction: str = "down") -> dict:
    try:
        page = await BrowserStateManager.get_page()
        amount = 800 if direction == "down" else -800
        await page.evaluate(f"window.scrollBy(0, {amount});")
        await page.wait_for_timeout(1000)
        return _format_response(True, "scroll_page", f"Scrolled {direction}")
    except Exception as e:
        return _format_response(False, "scroll_page", "Failed to scroll", error=str(e))

async def close_browser() -> dict:
    try:
        await BrowserStateManager.close_all()
        return _format_response(True, "close_browser", "Browser session closed successfully.")
    except Exception as e:
        return _format_response(False, "close_browser", "Failed to close browser", error=str(e))

# --- Interaction Tools ---

async def click_element(selector: str) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        element = page.locator(selector).first
        await element.wait_for(state="visible", timeout=10000)
        await element.click(timeout=10000)
        return _format_response(True, "click_element", f"Clicked element matching selector: {selector}")
    except Exception as e:
        return _format_response(False, "click_element", f"Failed to click selector: {selector}", error=str(e))

async def click_by_text(text: str) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        element = page.get_by_text(text, exact=False).first
        await element.wait_for(state="visible", timeout=10000)
        await element.click(timeout=10000)
        return _format_response(True, "click_by_text", f"Clicked element containing text: {text}")
    except Exception as e:
        return _format_response(False, "click_by_text", f"Failed to click text: {text}", error=str(e))

async def type_text(selector: str, value: str) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        element = page.locator(selector).first
        await element.wait_for(state="visible", timeout=10000)
        await element.fill(value, timeout=10000)
        return _format_response(True, "type_text", f"Typed '{value}' into selector: {selector}")
    except Exception as e:
        return _format_response(False, "type_text", f"Failed to type into selector: {selector}", error=str(e))

async def press_key(key: str) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        await page.keyboard.press(key)
        return _format_response(True, "press_key", f"Pressed key: {key}")
    except Exception as e:
        return _format_response(False, "press_key", f"Failed to press key: {key}", error=str(e))

async def hover_element(selector: str) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        element = page.locator(selector).first
        await element.wait_for(state="visible", timeout=10000)
        await element.hover(timeout=10000)
        return _format_response(True, "hover_element", f"Hovered over selector: {selector}")
    except Exception as e:
        return _format_response(False, "hover_element", f"Failed to hover selector: {selector}", error=str(e))

async def scroll_page(direction: str, amount: int = 500) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        if direction.lower() == "down":
            await page.mouse.wheel(0, amount)
        elif direction.lower() == "up":
            await page.mouse.wheel(0, -amount)
        else:
            return _format_response(False, "scroll_page", "Invalid direction. Use 'up' or 'down'.")
        
        # Give it a moment to render after scrolling
        await asyncio.sleep(0.5)
        return _format_response(True, "scroll_page", f"Scrolled {direction} by {amount} pixels")
    except Exception as e:
        return _format_response(False, "scroll_page", "Failed to scroll", error=str(e))

async def select_dropdown(selector: str, value: str) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        element = page.locator(selector).first
        await element.wait_for(state="visible", timeout=10000)
        selected = await element.select_option(value, timeout=10000)
        return _format_response(True, "select_dropdown", f"Selected '{selected}' from dropdown: {selector}")
    except Exception as e:
        return _format_response(False, "select_dropdown", f"Failed to select from dropdown: {selector}", error=str(e))

# --- Extraction & Observation ---

async def extract_visible_text() -> dict:
    try:
        page = await BrowserStateManager.get_page()
        # Strip script/style tags and get visible text
        text = await page.evaluate("""() => {
            return document.body.innerText;
        }""")
        return _format_response(True, "extract_visible_text", f"Extracted {len(text)} characters", {"text": text[:5000]}) # Limit output size
    except Exception as e:
        return _format_response(False, "extract_visible_text", "Failed to extract text", error=str(e))

async def extract_element_text(selector: str) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        element = page.locator(selector).first
        await element.wait_for(state="visible", timeout=10000)
        text = await element.inner_text()
        return _format_response(True, "extract_element_text", f"Extracted text from {selector}", {"text": text})
    except Exception as e:
        return _format_response(False, "extract_element_text", f"Failed to extract text from {selector}", error=str(e))

async def inject_element_markers() -> dict:
    try:
        page = await BrowserStateManager.get_page()
        script = """() => {
            if (window.__jarvis_elements) {
                document.querySelectorAll('.jarvis-marker').forEach(e => e.remove());
            }
            window.__jarvis_elements = {};
            let counter = 1;
            const elements = [];
            
            const interactables = document.querySelectorAll('a, button, input:not([type="hidden"]), select, textarea, [role="button"]');
            
            interactables.forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0 || rect.top < 0 || rect.left < 0) return;
                
                const id = counter++;
                window.__jarvis_elements[id] = el;
                el.setAttribute('data-jarvis-id', id);
                
                let text = el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '';
                text = text.trim().substring(0, 50); // limit length
                
                // Grab parent context for disambiguation (e.g., product name + price near an ADD button)
                let context = '';
                // Walk UP the DOM tree to find a parent with meaningful product context (>30 chars)
                let node = el.parentElement;
                for (let i = 0; i < 8 && node; i++) {
                    let t = node.innerText.replace(/\u20b9/g, 'Rs').replace(/\s+/g, ' ').trim();
                    if (t.length > 30) {
                        context = t.substring(0, 150);
                        break;
                    }
                    node = node.parentElement;
                }
                
                if (text) {
                    elements.push({
                        id: id,
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        text: text,
                        context: context || '',
                        top: rect.top
                    });
                }
                
                // Visual marker
                const marker = document.createElement('div');
                marker.className = 'jarvis-marker';
                marker.innerText = id;
                marker.style.position = 'absolute';
                marker.style.top = (rect.top + window.scrollY) + 'px';
                marker.style.left = (rect.left + window.scrollX) + 'px';
                marker.style.backgroundColor = 'red';
                marker.style.color = 'white';
                marker.style.fontSize = '12px';
                marker.style.fontWeight = 'bold';
                marker.style.padding = '2px 4px';
                marker.style.zIndex = '999999';
                marker.style.pointerEvents = 'none';
                marker.style.borderRadius = '3px';
                document.body.appendChild(marker);
            });
            // Sort elements by Y position so visible ones come first
            elements.sort((a, b) => a.top - b.top);
            // Remove helper fields, strip empty context to save tokens
            elements.forEach(e => {
                delete e.top;
                if (!e.context) delete e.context;
            });
            return elements;
        }"""
        
        elements = await page.evaluate(script)
        # Limit to top 75 to give more context while preventing explosion
        elements = elements[:75]
        return _format_response(True, "inject_element_markers", f"Marked {len(elements)} elements", {"elements": elements})
    except Exception as e:
        return _format_response(False, "inject_element_markers", "Failed to mark elements", error=str(e))

async def interact_by_id(element_id: int, action: str, text: str = "") -> dict:
    try:
        page = await BrowserStateManager.get_page()
        
        selector = f"[data-jarvis-id='{element_id}']"
        element = page.locator(selector).first
        
        # Ensure element exists
        if await element.count() == 0:
            return _format_response(False, "interact_by_id", f"Element ID {element_id} not found on page.")
        
        # Scroll the element into view so the user can physically see what's happening
        await element.scroll_into_view_if_needed(timeout=5000)
        await page.wait_for_timeout(500)
        
        # Highlight the element briefly (green flash) for visual confirmation
        await page.evaluate("""(selector) => {
            const el = document.querySelector(selector);
            if (el) {
                el.style.outline = '3px solid #00ff00';
                el.style.outlineOffset = '2px';
                setTimeout(() => { el.style.outline = ''; el.style.outlineOffset = ''; }, 2000);
            }
        }""", selector)
        
        # Get element text for logging
        el_text = await element.inner_text() if action == "click" else text
        print(f"[Browser] {action.upper()} element #{element_id}: '{el_text[:60]}'")
            
        if action == "click":
            await element.click(force=True, timeout=5000)
        elif action == "type":
            # Playwright fill perfectly triggers React state
            await element.fill(text, timeout=5000)
            await element.press("Enter", timeout=5000)
        else:
            return _format_response(False, "interact_by_id", f"Unknown action '{action}'")
            
        # Give the page a moment to load
        await page.wait_for_timeout(3000)
        return _format_response(True, "interact_by_id", f"Successfully executed '{action}' on element {element_id}")
            
    except Exception as e:
        return _format_response(False, "interact_by_id", f"Failed to execute '{action}' on element {element_id}", error=str(e))

async def get_page_title() -> dict:
    try:
        page = await BrowserStateManager.get_page()
        title = await page.title()
        return _format_response(True, "get_page_title", f"Page title is '{title}'", {"title": title})
    except Exception as e:
        return _format_response(False, "get_page_title", "Failed to get title", error=str(e))

async def get_dom_snapshot() -> dict:
    try:
        page = await BrowserStateManager.get_page()
        snapshot = await page.evaluate("""() => {
            // Simplified snapshot for agent consumption
            function serialize(element) {
                if (element.nodeType === Node.TEXT_NODE) {
                    let text = element.textContent.trim();
                    return text ? text : null;
                }
                if (element.nodeType !== Node.ELEMENT_NODE) return null;
                
                const ignoreTags = ['SCRIPT', 'STYLE', 'SVG', 'PATH', 'META', 'LINK', 'NOSCRIPT'];
                if (ignoreTags.includes(element.tagName)) return null;

                const isInteractive = ['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(element.tagName) || element.getAttribute('role') === 'button';
                
                let res = { tag: element.tagName.toLowerCase() };
                if (element.id) res.id = element.id;
                if (element.className && typeof element.className === 'string') res.class = element.className;
                if (isInteractive) res.interactive = true;
                if (element.href) res.href = element.href;
                
                let children = [];
                for (let child of element.childNodes) {
                    let s = serialize(child);
                    if (s) children.push(s);
                }
                if (children.length === 1 && typeof children[0] === 'string') {
                    res.text = children[0];
                } else if (children.length > 0) {
                    res.children = children;
                }
                
                // Keep only elements with semantic value or text
                if (res.text || res.children || res.interactive) return res;
                return null;
            }
            return serialize(document.body);
        }""")
        return _format_response(True, "get_dom_snapshot", "Extracted simplified DOM snapshot", {"snapshot": snapshot})
    except Exception as e:
        return _format_response(False, "get_dom_snapshot", "Failed to extract DOM", error=str(e))

async def take_screenshot(path: str = "screenshot.png") -> dict:
    try:
        page = await BrowserStateManager.get_page()
        await page.screenshot(path=path)
        return _format_response(True, "take_screenshot", f"Screenshot saved to {path}", {"path": path})
    except Exception as e:
        return _format_response(False, "take_screenshot", "Failed to take screenshot", error=str(e))

# --- Waiting & Synchronization ---

async def wait_for_selector(selector: str, timeout: int = 15000) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout)
        return _format_response(True, "wait_for_selector", f"Selector {selector} is now visible")
    except Exception as e:
        return _format_response(False, "wait_for_selector", f"Timeout waiting for {selector}", error=str(e))

async def wait_for_text(text: str, timeout: int = 15000) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        await page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return _format_response(True, "wait_for_text", f"Text '{text}' is now visible")
    except Exception as e:
        return _format_response(False, "wait_for_text", f"Timeout waiting for text '{text}'", error=str(e))

async def wait_for_navigation(timeout: int = 15000) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        await page.wait_for_load_state("networkidle", timeout=timeout)
        return _format_response(True, "wait_for_navigation", "Page navigation/loading complete")
    except Exception as e:
        return _format_response(False, "wait_for_navigation", "Timeout waiting for navigation to settle", error=str(e))

# --- Backward Compatibility for current Registry ---

async def browser_search(query: str, open_visible: bool = False) -> str:
    """
    Legacy wrapper for the current registry execution.
    We maintain the old DuckDuckGo logic but route it through the new state manager
    so it doesn't break existing LLM expectations before LangGraph is deployed.
    """
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        # Override headless if open_visible is requested, though currently state manager initializes once.
        page = await BrowserStateManager.get_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        
        try:
            await page.wait_for_selector(".result", timeout=8000)
            results = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.result');
                    let text = '';
                    items.forEach((item, i) => {
                        if (i >= 5) return;
                        const link = item.querySelector('.result__a');
                        const snippet = item.querySelector('.result__snippet');
                        if (link) {
                            text += `\\nResult ${i+1}: ${link.textContent.trim()}\\nURL: ${link.href}\\nSnippet: ${snippet ? snippet.textContent.trim() : ''}\\n`;
                        }
                    });
                    return text;
                }
            """)
            if results:
                return f"Browser search completed. Found results:\\n{results}"
            else:
                return "Browser search completed but no results found on page."
        except PlaywrightTimeout:
            return "Timeout waiting for search results to load."
    except Exception as e:
        return f"Browser search failed: {e}"

def browser_search_sync(query: str, open_visible: bool = False) -> str:
    """Synchronous wrapper for browser_search."""
    return asyncio.run(browser_search(query, open_visible))
