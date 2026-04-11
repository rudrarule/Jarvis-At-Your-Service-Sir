"""
browser_tool.py — Automated web crawling tool utilizing Playwright.
Spins up a physical Chromium instance to search Google and clicks the first result.
"""
import urllib.parse
import threading
from playwright.sync_api import sync_playwright

def run_browser(query: str):
    """
    Runs the playwright instance synchronously inside a dedicated thread.
    Keeps the browser open intentionally so the user can interact with it.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            
            # Go directly to DuckDuckGo search endpoint to bypass automated CAPTCHAs
            url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}"
            page.goto(url)
            
            try:
                # Wait for DuckDuckGo's first organic result link
                page.wait_for_selector("a[data-testid='result-title-a']", timeout=3000)
                # Click the first natural search result
                page.click("a[data-testid='result-title-a']")
            except Exception as wait_err:
                print(f"⚠️ Playwright couldn't find/click h3 tag: {wait_err}")
                
            # Keep the browser open for 30 minutes so user can read
            import time
            time.sleep(1800)
            
            context.close()
            browser.close()
    except Exception as e:
        print(f"❌ Browser tool failed: {e}")


def browser_search(query: str) -> str:
    """
    Opens a visible browser and searches for the query.
    Returns instantly to avoid blocking the TTS pipeline.
    """
    print(f"🌐 Firing visible browser automation for: '{query}'")
    
    # Run playwright in a separate daemon thread to return 0-latency feedback
    thread = threading.Thread(target=run_browser, args=(query,), daemon=True)
    thread.start()
    
    return f"Affirmative, sir. Searching the web for {query}."
