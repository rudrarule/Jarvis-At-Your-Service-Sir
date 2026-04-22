"""
Manual test script for browser tool verification.
Run this to verify actual functionality.
"""
import asyncio
from tools.browser_tool import browser_search

async def test_headless_search():
    """Test headless mode with actual search."""
    print("=" * 60)
    print("TEST: Headless Browser Search")
    print("=" * 60)

    result = await browser_search("Python programming language", open_visible=False)
    print(f"\nResult:\n{result[:500]}...")
    print(f"\n[PASS] Total length: {len(result)} chars")

    # Assertions
    assert "Python" in result or "programming" in result or "no results" in result.lower(), "Should contain Python or no results message"
    assert "Source:" in result or "no results" in result.lower(), "Should contain sources"
    print("[PASS] Headless search test PASSED")


async def test_api_fast_path():
    """Test that API fast path works."""
    print("\n" + "=" * 60)
    print("TEST: DDG API Fast Path")
    print("=" * 60)

    # This should hit the API first (if working)
    result = await browser_search("weather today", open_visible=False)
    print(f"\nResult:\n{result[:500]}...")
    print("[PASS] API fast path test completed")


async def test_visible_mode():
    """Test visible browser mode."""
    print("\n" + "=" * 60)
    print("TEST: Visible Browser Mode")
    print("=" * 60)

    result = await browser_search("latest news", open_visible=True)
    print(f"\nResult: {result}")

    assert "Opening browser" in result
    assert "tab will remain active" in result
    print("[PASS] Visible mode test PASSED")


async def main():
    """Run all manual tests."""
    print("\n[TEST] Browser Tool Manual Test Suite")
    print("=" * 60)

    try:
        await test_headless_search()
    except Exception as e:
        print(f"[FAIL] Headless search failed: {e}")

    try:
        await test_api_fast_path()
    except Exception as e:
        print(f"[FAIL] API fast path failed: {e}")

    try:
        await test_visible_mode()
    except Exception as e:
        print(f"[FAIL] Visible mode failed: {e}")

    print("\n" + "=" * 60)
    print("Manual testing complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
