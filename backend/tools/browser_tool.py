"""
browser_tool.py — Enhanced web search with content extraction.
Uses async Playwright for non-blocking execution.
"""
import asyncio
import urllib.parse
import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


async def _ddg_api_search(query: str) -> list[dict] | None:
    """
    Fast API search using DuckDuckGo HTML (no JS, no browser).
    Returns list of results or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            # Use DuckDuckGo HTML version — more stable than Lite
            url = "https://html.duckduckgo.com/html/"
            payload = {"q": query}
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            response = await client.post(url, data=payload, headers=headers)
            response.raise_for_status()

            import re
            html = response.text

            results = []
            # DDG HTML version uses class="result__a" for links and class="result__snippet" for snippets
            result_blocks = re.findall(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )

            for href, title, snippet in result_blocks[:5]:
                # Clean HTML tags from title and snippet
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                if href.startswith('http') and 'duckduckgo' not in href:
                    results.append({
                        "title": clean_title,
                        "url": href,
                        "snippet": clean_snippet[:300]
                    })

            if results:
                print(f"[DDG API] Got {len(results)} results from HTML search")
            return results if results else None

    except Exception as e:
        print(f"[WARN] DDG API search failed: {e}")
        return None


async def _playwright_search(query: str, headless: bool = True, keep_open: bool = False) -> list[dict] | None:
    """
    Browser-based search with content extraction using Playwright.
    Returns extracted results from DuckDuckGo.
    """
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        page = await context.new_page()

        try:
            # Use DuckDuckGo HTML version which is more stable for scraping
            encoded_query = urllib.parse.quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

            print(f"[NAV] Browser navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)

            # Wait for results — DDG HTML uses .result class
            await page.wait_for_selector(".result", timeout=8000)

            if keep_open:
                try:
                    await page.click(".result__a", timeout=5000)
                    print("[CLICK] Clicked first result, keeping browser open")
                except Exception as click_err:
                    print(f"[WARN] Could not click result: {click_err}")

            # Extract results
            extracted = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.result');
                    const data = [];
                    items.forEach(item => {
                        const link = item.querySelector('.result__a');
                        const snippet = item.querySelector('.result__snippet');
                        if (link) {
                            data.push({
                                title: link.textContent.trim(),
                                url: link.href,
                                snippet: snippet ? snippet.textContent.trim().substring(0, 300) : ''
                            });
                        }
                    });
                    return data.slice(0, 5);
                }
            """)

            results = extracted
            print(f"[OK] Extracted {len(results)} results from browser")

        except PlaywrightTimeout:
            print("[TIMEOUT] Timeout waiting for results, trying fallback")
            try:
                # Try the JS version as fallback
                await page.goto(f"https://duckduckgo.com/?q={encoded_query}", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_selector("[data-testid='result']", timeout=8000)
                results = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('[data-testid="result"]')).slice(0, 5).map(r => ({
                        title: r.querySelector('a')?.textContent?.trim() || '',
                        url: r.querySelector('a')?.href || '',
                        snippet: r.textContent?.trim().substring(0, 300) || ''
                    })).filter(r => r.title)
                """)
            except Exception as fallback_err:
                print(f"[ERROR] Fallback extraction failed: {fallback_err}")

        except Exception as e:
            print(f"[ERROR] Browser search failed: {e}")

        finally:
            if keep_open:
                print(f"[WAIT] Keeping browser open for user (5 min)...")
                await asyncio.sleep(300)
            await context.close()
            await browser.close()

    return results


async def _open_visible_browser(query: str) -> str:
    """
    Opens a physical browser window that stays open for user interaction.
    Returns immediately to not block other operations.
    """
    import threading

    def run_browser():
        """Run browser in separate thread."""
        asyncio.run(_playwright_search(query, headless=False, keep_open=True))

    # Start browser in background thread
    thread = threading.Thread(target=run_browser, daemon=True)
    thread.start()

    return f"Opening browser for '{query}', sir. The tab will remain active."


async def browser_search(query: str, open_visible: bool = False) -> str:
    """
    Opens a visible DuckDuckGo browser window with search results.
    The user can browse and interact with the results directly.

    Args:
        query: Search query string
        open_visible: Ignored — always opens visible browser now.

    Returns:
        Confirmation message
    """
    print(f"[WEB] Search: '{query}' — opening visible browser")
    return await _open_visible_browser(query)


def browser_search_sync(query: str, open_visible: bool = False) -> str:
    """Synchronous wrapper for browser_search."""
    return asyncio.run(browser_search(query, open_visible))


async def open_url(url: str) -> str:
    """
    Opens a specific URL directly in a visible browser.
    No search, direct navigation.

    Args:
        url: Full URL to open (e.g., 'https://google.com', 'https://github.com')

    Returns:
        Confirmation message
    """
    # Add https:// if missing
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"

    print(f"[URL] Opening: {url}")

    import threading

    def run_browser():
        """Run browser in thread."""
        asyncio.run(_open_direct_url(url))

    thread = threading.Thread(target=run_browser, daemon=True)
    thread.start()

    return f"Opening {url} in browser, sir."


async def _open_direct_url(url: str):
    """Internal: Open direct URL and keep browser alive."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-gpu", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(url, timeout=30000)
            print(f"[OK] Loaded: {url}")
            # Keep open for 10 minutes
            await asyncio.sleep(600)
        except Exception as e:
            print(f"[ERROR] Failed to load {url}: {e}")
        finally:
            await context.close()
            await browser.close()
