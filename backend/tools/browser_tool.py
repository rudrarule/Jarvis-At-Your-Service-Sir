"""
browser_tool.py — Autonomous Browser Interaction Layer
Powered by async Playwright. Maintains a persistent stateful browser session
to support LangGraph ReAct agent loops and multi-step workflows.
"""
import asyncio
import base64
import json
import os
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout, Page, Browser, BrowserContext
from tools.browser_state import observe_page_state, get_active_registry, get_accessibility_tree


def _format_response(success: bool, action: str, observation: str, data: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "success": success,
        "action": action,
        "observation": observation,
        "data": data,
        "error": error
    }


def _debug_dir() -> Optional[str]:
    path = os.getenv("JARVIS_E2E_DEBUG_DIR")
    if not path:
        return None
    os.makedirs(path, exist_ok=True)
    return path


async def _capture_debug_artifacts(page: Page, label: str, extra: Optional[dict[str, Any]] = None) -> None:
    """Persist page artifacts for e2e failure triage when debug mode is enabled."""
    path = _debug_dir()
    if not path:
        return

    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("_")[:80] or "browser"
    stamp = f"{int(time.time() * 1000)}_{safe_label}"
    meta: dict[str, Any] = {"label": label, "extra": extra or {}}
    try:
        meta["url"] = page.url
        meta["title"] = await page.title()
        meta["visible_text"] = (await page.evaluate("() => document.body ? document.body.innerText : ''") or "")[:8000]
    except Exception as exc:
        meta["metadata_error"] = str(exc)

    try:
        await page.screenshot(path=os.path.join(path, f"{stamp}.png"), full_page=True)
        meta["screenshot"] = f"{stamp}.png"
    except Exception as exc:
        meta["screenshot_error"] = str(exc)

    try:
        html = await page.content()
        html_name = f"{stamp}.html"
        with open(os.path.join(path, html_name), "w", encoding="utf-8") as fh:
            fh.write(html)
        meta["html"] = html_name
    except Exception as exc:
        meta["html_error"] = str(exc)

    with open(os.path.join(path, f"{stamp}.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2, default=str)

class BrowserStateManager:
    _playwright = None
    _browser: Optional[Browser] = None
    _context: Optional[BrowserContext] = None
    _page: Optional[Page] = None
    _is_cdp: bool = False  # True when attached to a user-run Chrome over CDP
    _lock = asyncio.Lock()

    @classmethod
    async def get_page(cls) -> Page:
        async with cls._lock:
            if cls._page and not cls._page.is_closed():
                return cls._page

            if not cls._playwright:
                import sys
                if sys.platform == 'win32':
                    # A Proactor loop is required to SPAWN a browser subprocess.
                    # CDP-attach (preferred) does not spawn, so this only matters for
                    # the launch fallback. Best-effort; harmless if the loop already exists.
                    try:
                        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                    except Exception:
                        pass
                cls._playwright = await async_playwright().start()

            from dotenv import load_dotenv
            env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
            load_dotenv(env_path, override=True)

            if not cls._context:
                cls._context = await cls._acquire_context()

            try:
                cls._page = cls._context.pages[0] if cls._context.pages else await cls._context.new_page()

                # Anti-detection stealth scripts (best-effort: may be unsupported on an
                # attached page; only affects future navigations, never blocks).
                try:
                    await cls._page.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                    )
                except Exception:
                    pass

                return cls._page
            except Exception as e:
                # If the context crashed (TargetClosedError), wipe it and recursively rebuild
                print(f"[BrowserStateManager] Context dead, rebuilding: {e}")
                cls._context = None
                cls._page = None
                # Release the lock briefly to avoid deadlocks on recursive call
                pass

        # Call outside the lock if we had an exception
        return await cls.get_page()

    @classmethod
    async def _acquire_context(cls) -> BrowserContext:
        """Acquire a browser context using the most reliable strategy available.

        Strategy 1 - CDP attach (preferred; enabled by BROWSER_CDP_URL):
          Connects to an ALREADY-RUNNING Chrome via the DevTools protocol. This does
          NOT spawn a browser subprocess, so it sidesteps the Windows SelectorEventLoop
          `NotImplementedError` that breaks launch_persistent_context, and it reuses the
          user's real, logged-in profile (login flows just work).

          Start Chrome once, e.g.:
            chrome.exe --remote-debugging-port=9222 --user-data-dir="C:/jarvis-chrome"
          then set in backend/.env:
            BROWSER_CDP_URL=http://localhost:9222

        Strategy 2 - launch a managed Chromium (original behavior; fallback).
        """
        cdp_url = os.getenv("BROWSER_CDP_URL", "").strip()
        if cdp_url:
            try:
                cls._browser = await cls._playwright.chromium.connect_over_cdp(cdp_url, timeout=15000)
                contexts = cls._browser.contexts
                ctx = contexts[0] if contexts else await cls._browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                )
                cls._is_cdp = True
                print(f"[BrowserStateManager] Attached to running Chrome over CDP at {cdp_url} "
                      f"({len(ctx.pages)} open tab(s)). Using the real, logged-in browser.")
                return ctx
            except Exception as e:
                print(f"[BrowserStateManager] CDP attach to {cdp_url} failed ({e}); "
                      f"falling back to launching a managed Chromium.")

        cls._is_cdp = False
        return await cls._launch_persistent_context()

    @classmethod
    async def _launch_persistent_context(cls) -> BrowserContext:
        # Force foreground browser mode regardless of terminal state
        headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
        user_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "browser_user_data"))
        launch_args = {
            "headless": headless,
            "viewport": {'width': 1280, 'height': 800},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "args": ["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }
        try:
            return await cls._playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                **launch_args,
            )
        except NotImplementedError:
            # Windows SelectorEventLoop cannot spawn a subprocess. Retrying with a
            # different profile hits the SAME error, so fail loudly with the actual fix
            # instead of silently spawning throwaway browser_user_data_* profiles.
            print(
                "[BrowserStateManager] launch_persistent_context raised NotImplementedError: "
                "the running event loop is a SelectorEventLoop and cannot spawn a browser "
                "subprocess. FIX: set BROWSER_CDP_URL (e.g. http://localhost:9222) to attach to "
                "a Chrome started with --remote-debugging-port=9222, OR run the server on a "
                "WindowsProactorEventLoop."
            )
            raise
        except Exception as e:
            fallback_dir = os.path.abspath(os.path.join(
                os.path.dirname(__file__),
                "..",
                f"browser_user_data_{os.getpid()}_{int(asyncio.get_running_loop().time() * 1000)}",
            ))
            print(f"[BrowserStateManager] Persistent launch failed ({e}), using temporary profile: {fallback_dir}")
            return await cls._playwright.chromium.launch_persistent_context(
                user_data_dir=fallback_dir,
                **launch_args,
            )

    @classmethod
    async def close_all(cls):
        async with cls._lock:
            # When attached to the user's real Chrome over CDP, do NOT close their
            # context/tabs. browser.close() on a CDP connection only detaches Playwright
            # and leaves the user's Chrome (and logins) running.
            if cls._is_cdp:
                if cls._browser:
                    try:
                        await cls._browser.close()  # disconnect CDP session only
                    except Exception:
                        pass
                cls._browser = None
                cls._context = None
                cls._page = None
                cls._is_cdp = False
                if cls._playwright:
                    try:
                        await cls._playwright.stop()
                    except Exception:
                        pass
                    cls._playwright = None
                return

            if cls._context:
                try:
                    await cls._context.close()
                except Exception:
                    pass
                cls._context = None
            if cls._browser: # Keep for backwards compatibility if needed
                try:
                    await cls._browser.close()
                except Exception:
                    pass
                cls._browser = None
            if cls._playwright:
                try:
                    await cls._playwright.stop()
                except Exception:
                    pass
                cls._playwright = None
            cls._page = None

# --- Screenshot for Vision ---

def _compress_screenshot(screenshot_bytes: bytes, target_width: int = 640, target_height: int = 400) -> bytes:
    """Resize screenshot to reduce base64 payload size for vision models."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(screenshot_bytes))
        img = img.resize((target_width, target_height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        compressed = buf.getvalue()
        print(f"[Screenshot] Compressed {len(screenshot_bytes)} -> {len(compressed)} bytes ({target_width}x{target_height})")
        return compressed
    except ImportError:
        print("[Screenshot] Pillow not available, skipping compression")
        return screenshot_bytes
    except Exception as e:
        print(f"[Screenshot] Compression failed ({e}), using original")
        return screenshot_bytes

async def take_screenshot() -> dict:
    """Takes a screenshot of the current browser viewport and returns it as base64 PNG."""
    try:
        page = await BrowserStateManager.get_page()
        screenshot_bytes = await page.screenshot(type="png")
        screenshot_bytes = _compress_screenshot(screenshot_bytes)
        b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")
        print(f"[Screenshot] Captured viewport ({len(screenshot_bytes)} bytes)")
        return _format_response(True, "take_screenshot", "Screenshot captured", {"image_base64": b64_image})
    except Exception as e:
        return _format_response(False, "take_screenshot", "Failed to capture screenshot", error=str(e))

# --- Navigation & Control ---

def _sanitize_url_arg(raw: str) -> str:
    """Extract just the URL from an argument.

    Llama frequently passes the whole instruction as the url, e.g.
    'https://skyscanner.co.in and tell me the title', which then fails DNS with
    ERR_NAME_NOT_RESOLVED. Keep only the URL token.
    """
    if not raw or not isinstance(raw, str):
        return raw
    raw = raw.strip().strip('"\'')
    m = re.search(r'https?://[^\s"\'<>]+', raw)
    if m:
        return m.group(0).rstrip('.,)\'"')
    m = re.search(r'\b[\w-]+(?:\.[\w-]+)+(?:/[^\s"\'<>]*)?', raw)  # bare domain
    if m:
        return m.group(0).rstrip('.,)\'"')
    return raw.split()[0] if raw.split() else raw


async def open_url(url: str) -> dict:
    url = _sanitize_url_arg(url)
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    try:
        page = await BrowserStateManager.get_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if os.getenv("JARVIS_E2E_CAPTURE_EACH_ACTION", "").lower() in {"1", "true", "yes", "on"}:
            await _capture_debug_artifacts(page, "after_open_url", {"target_url": url})
        return _format_response(True, "open_url", f"Navigated to {url}", {"url": page.url})
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        with open(r"c:\Users\Rudra\holo-core-nexus\backend\data\graph_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[Browser Error] {trace}\n")
        err_msg = str(e) if str(e) else type(e).__name__
        try:
            page = await BrowserStateManager.get_page()
            await _capture_debug_artifacts(page, "open_url_failed", {"target_url": url, "error": err_msg})
        except Exception:
            pass
        return _format_response(False, "open_url", f"Failed to navigate to {url}", error=err_msg)

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

async def extract_links(limit: int = 50) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        links = await page.evaluate(
            """(limit) => Array.from(document.querySelectorAll('a[href]')).slice(0, limit).map((a) => ({
                text: (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 120),
                url: a.href
            }))""",
            limit,
        )
        return _format_response(True, "extract_links", f"Extracted {len(links)} links", {"links": links})
    except Exception as e:
        return _format_response(False, "extract_links", "Failed to extract links", error=str(e))

async def extract_buttons(limit: int = 50) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        buttons = await page.evaluate(
            """(limit) => Array.from(document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]')).slice(0, limit).map((button) => ({
                text: (button.innerText || button.value || button.getAttribute('aria-label') || '').trim().slice(0, 120),
                disabled: Boolean(button.disabled || button.getAttribute('aria-disabled') === 'true')
            }))""",
            limit,
        )
        return _format_response(True, "extract_buttons", f"Extracted {len(buttons)} buttons", {"buttons": buttons})
    except Exception as e:
        return _format_response(False, "extract_buttons", "Failed to extract buttons", error=str(e))

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
        script = r"""() => {
            if (window.__jarvis_elements) {
                document.querySelectorAll('.jarvis-marker').forEach(e => e.remove());
            }
            window.__jarvis_elements = {};
            let counter = 1;
            const elements = [];
            
            function esc(value) {
                return window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/"/g, '\\"');
            }

            function stableSelector(el) {
                if (el.id) return '#' + esc(el.id);
                const jarvisId = el.getAttribute('data-jarvis-id');
                if (jarvisId) return `[data-jarvis-id="${jarvisId}"]`;
                const aria = el.getAttribute('aria-label');
                if (aria) return `${el.tagName.toLowerCase()}[aria-label="${esc(aria)}"]`;
                const name = el.getAttribute('name');
                if (name) return `${el.tagName.toLowerCase()}[name="${esc(name)}"]`;
                return el.tagName.toLowerCase();
            }

            const interactables = document.querySelectorAll('a, button, input:not([type="hidden"]), select, textarea, [role="button"], [role="link"], [contenteditable="true"]');
            
            interactables.forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0 || rect.top < 0 || rect.left < 0) return;
                
                const id = counter++;
                window.__jarvis_elements[id] = el;
                el.setAttribute('data-jarvis-id', id);
                
                const ariaLabel = el.getAttribute('aria-label') || '';
                const role = el.getAttribute('role') || '';
                const placeholder = el.placeholder || '';
                let text = el.innerText || el.value || placeholder || ariaLabel || el.getAttribute('title') || '';
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
                        role: role,
                        type: el.type || '',
                        text: text,
                        aria_label: ariaLabel,
                        placeholder: placeholder,
                        context: context || '',
                        selector: stableSelector(el),
                        bbox: {
                            x: Math.round(rect.left),
                            y: Math.round(rect.top),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        },
                        enabled: !(el.disabled || el.getAttribute('aria-disabled') === 'true'),
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
                if (!e.role) delete e.role;
                if (!e.aria_label) delete e.aria_label;
                if (!e.placeholder) delete e.placeholder;
            });
            return elements;
        }"""
        
        elements = await page.evaluate(script)
        # Limit to top 75 to give more context while preventing explosion
        elements = elements[:75]
        return _format_response(True, "inject_element_markers", f"Marked {len(elements)} elements", {"elements": elements})
    except Exception as e:
        return _format_response(False, "inject_element_markers", "Failed to mark elements", error=str(e))

async def interact_by_id(element_id: int, action: str, text: str = "", press_enter: bool = True) -> dict:
    try:
        page = await BrowserStateManager.get_page()
        capture_each = os.getenv("JARVIS_E2E_CAPTURE_EACH_ACTION", "").lower() in {"1", "true", "yes", "on"}
        
        selector = f"[data-jarvis-id='{element_id}']"
        element = page.locator(selector).first
        
        # Ensure element exists
        if await element.count() == 0:
            if capture_each:
                await _capture_debug_artifacts(page, "interact_by_id_missing_element", {"element_id": element_id, "action": action})
            return _format_response(False, "interact_by_id", f"Element ID {element_id} not found on page.")

        before_url = page.url
        before_title = await page.title()
        before_value = ""
        try:
            before_value = await element.input_value(timeout=1000)
        except Exception:
            before_value = ""
        
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
        if capture_each:
            await _capture_debug_artifacts(page, "before_interact_by_id", {"element_id": element_id, "action": action, "text": text})
            
        if action == "click":
            await element.click(force=True, timeout=5000)
        elif action == "type":
            # Playwright fill perfectly triggers React state
            await element.fill(text, timeout=5000)
            if press_enter:
                await element.press("Enter", timeout=5000)
                # Auto-scroll down after search submission to reveal results below the fold
                # On e-commerce sites (Amazon, Flipkart, BigBasket), results are always below the search bar
                await page.wait_for_timeout(2000)  # Wait for search results to load
                await page.mouse.wheel(0, 400)  # Scroll past the search bar area
                await page.wait_for_timeout(500)
                print(f"[Browser] Auto-scrolled down 400px after search submission")
        else:
            return _format_response(False, "interact_by_id", f"Unknown action '{action}'")
            
        # Give the page a moment to load
        await page.wait_for_timeout(3000)
        after_url = page.url
        after_title = await page.title()
        after_value = ""
        try:
            refreshed = page.locator(selector).first
            if await refreshed.count() > 0:
                after_value = await refreshed.input_value(timeout=1000)
        except Exception:
            after_value = ""
        if capture_each:
            await _capture_debug_artifacts(
                page,
                "after_interact_by_id",
                {"element_id": element_id, "action": action, "text": text, "before_url": before_url, "after_url": after_url},
            )

        return _format_response(
            True,
            "interact_by_id",
            f"Successfully executed '{action}' on element {element_id}",
            {
                "element_id": element_id,
                "action": action,
                "before_url": before_url,
                "after_url": after_url,
                "before_title": before_title,
                "after_title": after_title,
                "url_changed": before_url != after_url,
                "title_changed": before_title != after_title,
                "value_changed": before_value != after_value,
            },
        )
            
    except Exception as e:
        try:
            page = await BrowserStateManager.get_page()
            await _capture_debug_artifacts(page, "interact_by_id_failed", {"element_id": element_id, "action": action, "text": text, "error": str(e)})
        except Exception:
            pass
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

def _clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", urllib.parse.unquote(text)).strip()


def _normalize_ddg_url(url: str) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    return url


def _extract_search_results_from_html(html: str, limit: int = 5) -> list[dict[str, str]]:
    results = []
    for href, label in re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html or "", flags=re.IGNORECASE | re.DOTALL):
        url = _normalize_ddg_url(href)
        if not url.startswith(("http://", "https://")):
            continue
        if "duckduckgo.com" in urllib.parse.urlparse(url).netloc.lower():
            continue
        title = _clean_html_text(label)
        if not title:
            continue
        if any(existing["url"] == url for existing in results):
            continue
        results.append({"title": title[:160], "url": url, "snippet": ""})
        if len(results) >= limit:
            break
    return results


def _format_search_results(query: str, results: list[dict[str, str]] | None) -> str:
    if not results:
        return f"I searched for '{query}', sir, but found no results."

    lines = [f"Here are the search results for '{query}':"]
    for idx, item in enumerate(results[:5], start=1):
        snippet = str(item.get("snippet") or "").strip()
        if len(snippet) > 220:
            snippet = snippet[:217].rstrip() + "..."
        lines.append(f"{idx}. {item.get('title', 'Untitled')}")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append(f"   Source: {item.get('url', '')}")
    return "\n".join(lines)


async def _ddg_api_search(query: str) -> list[dict[str, str]] | None:
    """Fetch lightweight DuckDuckGo HTML results without requiring a browser."""
    try:
        async with __import__("httpx").AsyncClient(timeout=12.0) as client:
            response = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
        return _extract_search_results_from_html(response.text)
    except Exception as exc:
        print(f"[BrowserSearch] DDG lightweight search failed: {exc}")
        return None


async def _playwright_search(query: str) -> list[dict[str, str]] | None:
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        page = await BrowserStateManager.get_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(".result, a[href]", timeout=8000)
        results = await page.evaluate(
            """() => Array.from(document.querySelectorAll('.result')).slice(0, 5).map((item) => {
                const link = item.querySelector('.result__a') || item.querySelector('a[href]');
                const snippet = item.querySelector('.result__snippet');
                return link ? {
                    title: link.textContent.trim(),
                    url: link.href,
                    snippet: snippet ? snippet.textContent.trim() : ''
                } : null;
            }).filter(Boolean)"""
        )
        return results or []
    except Exception as exc:
        print(f"[BrowserSearch] Playwright search failed: {exc}")
        return None


async def _open_visible_browser(query: str) -> str:
    encoded_query = urllib.parse.quote(query)
    url = f"https://duckduckgo.com/?q={encoded_query}"
    result = await open_url(url)
    if result.get("success"):
        return f"Opening browser for '{query}', sir. The tab will remain active."
    return f"I couldn't open the browser search, sir: {result.get('error') or 'unknown error'}"


async def browser_search(query: str, open_visible: bool = False) -> str:
    """
    Search the web using a lightweight DuckDuckGo request first, then Playwright
    as a fallback. Visible mode opens the persistent browser session.
    """
    if open_visible:
        return await _open_visible_browser(query)

    results = await _ddg_api_search(query)
    if not results:
        results = await _playwright_search(query)
    return _format_search_results(query, results)

def browser_search_sync(query: str, open_visible: bool = False) -> str:
    """Synchronous wrapper for browser_search."""
    return asyncio.run(browser_search(query, open_visible))


async def observe_with_registry(
    include_screenshot: bool = False,
    include_ax_tree_text: bool = True,
    max_elements: int = 120,
) -> dict:
    """
    Unified observation using virtual registry and accessibility tree.
    """
    try:
        page = await BrowserStateManager.get_page()
        observation = await observe_page_state(
            page=page,
            include_screenshot=include_screenshot,
            include_ax_tree_text=include_ax_tree_text,
            max_elements=max_elements,
        )
        return _format_response(
            True,
            "observe_with_registry",
            "Observed page state via virtual registry",
            observation,
        )
    except Exception as e:
        return _format_response(
            False,
            "observe_with_registry",
            "Failed to observe page state with registry",
            error=str(e),
        )


async def interact_by_registry_id(
    element_id: str,
    action: str,
    text: str = "",
    press_enter: bool = True,
) -> dict:
    """
    Interact with an element using its registry ID (numeric index or stable hash ID).
    """
    try:
        page = await BrowserStateManager.get_page()
        registry = get_active_registry(page)
        
        # Try numeric index first
        try:
            if isinstance(element_id, int):
                idx = element_id
            else:
                idx = int(element_id)
            res = await registry.interact(idx, action, text, press_enter)
        except (ValueError, TypeError):
            # Try stable hash ID
            entry = registry.get_by_id(element_id)
            if not entry:
                return _format_response(
                    False,
                    "interact_by_registry_id",
                    f"Element registry ID '{element_id}' not found. Re-observe the page.",
                )
            res = await registry.interact(entry.index, action, text, press_enter)
            
        if res.get("success"):
            return _format_response(
                True,
                "interact_by_registry_id",
                f"Successfully executed '{action}' on element {element_id}",
                res,
            )
        else:
            return _format_response(
                False,
                "interact_by_registry_id",
                res.get("error", "Interaction failed"),
                error=res.get("error"),
            )
    except Exception as e:
        return _format_response(
            False,
            "interact_by_registry_id",
            f"Failed to interact with element {element_id}",
            error=str(e),
        )


_MONTHS_FULL = ["january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december"]


def _parse_date_arg(s: str):
    """Parse '2026-06-18' | '18 June 2026' | 'June 18, 2026' | '18th June 2026'."""
    if not s:
        return None
    t = s.strip().lower()
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\s+(\d{4})', t)
        if m:
            d, mon_name, y = int(m.group(1)), m.group(2), int(m.group(3))
        else:
            m = re.search(r'\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})', t)
            if not m:
                return None
            mon_name, d, y = m.group(1), int(m.group(2)), int(m.group(3))
        mo = next((i + 1 for i, mn in enumerate(_MONTHS_FULL) if mn.startswith(mon_name[:3])), None)
        if not mo:
            return None
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return {"day": d, "month_num": mo, "month": _MONTHS_FULL[mo - 1], "year": y}


async def select_calendar_date(date_str: str, which: str = "departure") -> dict:
    """Deterministically click the EXACT calendar cell for a date.

    Removes date selection from the LLM's fuzzy element-id guessing (the source of
    date hallucination). Matches day + month + year in the cell's accessible name,
    pages forward through months if the target isn't visible yet, and never clicks a
    nearby/guessed date.
    """
    t = _parse_date_arg(date_str)
    if not t:
        return _format_response(False, "select_calendar_date",
                                f"Could not parse date '{date_str}'. Use e.g. '2026-06-18' or '18 June 2026'.",
                                error="unparseable_date")

    # ── PAST-DATE / HALLUCINATED-YEAR CORRECTION ────────────────
    # Models frequently emit a stale year (e.g. "2024-07-20" when today is
    # 2026). A travel date can never be in the past, so roll the year forward
    # to the next upcoming occurrence of that month+day. This is deterministic
    # and prevents the picker from paging fruitlessly toward a dead year.
    from datetime import date as _date

    def _safe_date(y, mo, d):
        try:
            return _date(y, mo, d)
        except ValueError:
            return None

    today = _date.today()
    parsed = _safe_date(t["year"], t["month_num"], t["day"])
    if parsed and parsed < today:
        candidate = _safe_date(today.year, t["month_num"], t["day"])
        if not candidate or candidate < today:
            candidate = _safe_date(today.year + 1, t["month_num"], t["day"])
        if candidate:
            print(f"[Calendar] Corrected past/stale date {parsed.isoformat()} -> {candidate.isoformat()}")
            t["year"] = candidate.year

    day, month, year = str(t["day"]), t["month"], str(t["year"])
    mon3 = month[:3]
    which = (which or "").strip().lower()
    # Lookahead: name must contain the day (as a whole number), the month (full or
    # 3-letter), and the year — in any order.
    name_re = re.compile(rf"(?=.*\b{day}\b)(?=.*(?:{month}|{mon3}))(?=.*{year})", re.IGNORECASE)
    roles = ["gridcell", "button", "option", "link", "cell"]
    next_labels = ["Next", "Forward", "next month", "Next month", "forward one month", "Move forward"]

    try:
        page = await BrowserStateManager.get_page()
    except Exception as e:
        return _format_response(False, "select_calendar_date", "Browser not available", error=str(e))

    for _attempt in range(14):  # up to ~13 months of forward paging
        for role in roles:
            try:
                loc = page.get_by_role(role, name=name_re)
                n = await loc.count()
            except Exception:
                continue
            if n <= 0:
                continue
            target_loc = loc.first
            if n > 1 and which:
                for i in range(min(n, 12)):
                    try:
                        nm = (await loc.nth(i).get_attribute("aria-label")) or (await loc.nth(i).inner_text())
                    except Exception:
                        nm = ""
                    if which in (nm or "").lower():
                        target_loc = loc.nth(i)
                        break
            try:
                await target_loc.scroll_into_view_if_needed(timeout=4000)
                await target_loc.click(timeout=4000)
                await page.wait_for_timeout(900)
                print(f"[Calendar] Selected {which or 'date'} {day} {month} {year} via role={role}")
                return _format_response(
                    True, "select_calendar_date",
                    f"Selected {which or ''} date {day} {month.title()} {year}".strip(),
                    {"day": int(day), "month": month, "year": int(year), "which": which, "role": role},
                )
            except Exception:
                continue
        # Target not visible -> try to advance the calendar one month.
        advanced = False
        for label in next_labels:
            try:
                nb = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
                if await nb.count() > 0:
                    await nb.first.click(timeout=3000)
                    await page.wait_for_timeout(600)
                    advanced = True
                    break
            except Exception:
                continue
        if not advanced:
            break

    return _format_response(
        False, "select_calendar_date",
        f"Could not find {which or ''} date {day} {month.title()} {year} in the open calendar. "
        "Make sure the date picker is open, then retry.".strip(),
        error="date_cell_not_found",
    )


async def get_page_accessibility_tree() -> dict:
    """
    Convenience function to get the current page's pruned accessibility tree.
    """
    try:
        page = await BrowserStateManager.get_page()
        tree = await get_accessibility_tree(page)
        return _format_response(
            True,
            "get_page_accessibility_tree",
            "Extracted page accessibility tree",
            {"tree": tree},
        )
    except Exception as e:
        return _format_response(
            False,
            "get_page_accessibility_tree",
            "Failed to extract accessibility tree",
            error=str(e),
        )
