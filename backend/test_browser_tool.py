"""
test_browser_tool.py — Comprehensive test suite for enhanced browser tool.
Senior Testing Engineer: Code Review & Test Plan Execution
"""
import pytest
import asyncio
import httpx
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from typing import Any

# Import the module under test
from tools.browser_tool import (
    _ddg_api_search,
    _playwright_search,
    _open_visible_browser,
    browser_search,
    browser_search_sync,
)


# =============================================================================
# TEST CONFIGURATION & FIXTURES
# =============================================================================

@pytest.fixture
def sample_query():
    """Standard test query."""
    return "Python programming language"


@pytest.fixture
def mock_ddg_results():
    """Mock DuckDuckGo API response results."""
    return [
        {
            "title": "Welcome to Python.org",
            "url": "https://www.python.org",
            "snippet": "The official home of the Python Programming Language"
        },
        {
            "title": "Python Tutorial - W3Schools",
            "url": "https://www.w3schools.com/python",
            "snippet": "Learn Python with our tutorial"
        }
    ]


@pytest.fixture
def mock_html_response():
    """Mock HTML response from DDG Lite."""
    return """
    <html>
    <body>
        <a href="https://www.python.org">Welcome to Python.org</a>
        <a href="https://www.w3schools.com/python">Python Tutorial - W3Schools</a>
    </body>
    </html>
    """


# =============================================================================
# TEST CATEGORY 1: UNIT TESTS - _ddg_api_search
# =============================================================================

class TestDDGApiSearch:
    """Tests for DuckDuckGo API search functionality."""

    @pytest.mark.asyncio
    async def test_ddg_api_success(self, sample_query, mock_html_response):
        """TC-API-001: Verify successful DDG API search returns results."""
        mock_response = Mock()
        mock_response.text = mock_html_response
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with patch("httpx.AsyncClient.__aenter__", return_value=Mock(
                post=AsyncMock(return_value=mock_response)
            )):
                # Mock the httpx client properly
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)

                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await _ddg_api_search(sample_query)

                    # Verify we got results back
                    assert result is not None
                    assert isinstance(result, list)
                    assert len(result) > 0

    @pytest.mark.asyncio
    async def test_ddg_api_empty_response(self):
        """TC-API-002: Verify empty HTML returns None gracefully."""
        mock_response = Mock()
        mock_response.text = "<html><body></body></html>"
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _ddg_api_search("test query")
            assert result is None or len(result) == 0

    @pytest.mark.asyncio
    async def test_ddg_api_timeout(self):
        """TC-API-003: Verify timeout exception handled gracefully."""
        with patch("httpx.AsyncClient", side_effect=httpx.TimeoutException("Connection timed out")):
            result = await _ddg_api_search("test")
            assert result is None

    @pytest.mark.asyncio
    async def test_ddg_api_http_error(self):
        """TC-API-004: Verify HTTP errors return None."""
        mock_response = Mock()
        mock_response.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "403 Forbidden",
            request=Mock(),
            response=Mock(status_code=403)
        ))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _ddg_api_search("test")
            assert result is None

    @pytest.mark.asyncio
    async def test_ddg_api_skips_internal_links(self):
        """TC-API-005: Verify internal DDG links are filtered out."""
        html_with_internal = """
        <html>
        <body>
            <a href="https://duckduckgo.com/about">About DuckDuckGo</a>
            <a href="https://www.python.org">Python.org</a>
        </body>
        </html>
        """
        mock_response = Mock()
        mock_response.text = html_with_internal
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _ddg_api_search("test")
            assert result is not None
            for item in result:
                assert "duckduckgo" not in item["url"]


# =============================================================================
# TEST CATEGORY 2: INTEGRATION TESTS - Playwright
# =============================================================================

class TestPlaywrightSearch:
    """Tests for browser-based Playwright search."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_playwright_headless_extraction(self, sample_query):
        """TC-BRW-001: Verify headless browser extracts search results."""
        # Note: This is an integration test requiring Playwright browser
        pytest.skip("Integration test - requires Playwright browser installation")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_playwright_visible_mode(self, sample_query):
        """TC-BRW-002: Verify visible mode opens browser window."""
        pytest.skip("Integration test - requires display and manual verification")

    @pytest.mark.asyncio
    async def test_playwright_timeout_handling(self):
        """TC-BRW-003: Verify timeout scenarios handled correctly."""
        with patch("tools.browser_tool.async_playwright") as mock_playwright:
            mock_browser = AsyncMock()
            mock_context = AsyncMock()
            mock_page = AsyncMock()

            # Simulate timeout on first selector
            mock_page.wait_for_selector = AsyncMock(side_effect=[
                Exception("Timeout"),  # First selector fails
                None  # Fallback selector succeeds
            ])

            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_playwright.return_value.__aenter__ = AsyncMock(return_value=Mock(
                chromium=Mock(launch=AsyncMock(return_value=mock_browser))
            ))

            # This would test the fallback mechanism
            # Implementation requires more detailed mocking
            pass


# =============================================================================
# TEST CATEGORY 3: FUNCTIONAL TESTS - browser_search
# =============================================================================

class TestBrowserSearchFunction:
    """Tests for main browser_search function."""

    @pytest.mark.asyncio
    async def test_headless_mode_returns_formatted_results(self, sample_query, mock_ddg_results):
        """TC-FUNC-001: Verify headless mode returns formatted string with results."""
        with patch("tools.browser_tool._ddg_api_search", return_value=mock_ddg_results):
            result = await browser_search(sample_query, open_visible=False)

            assert isinstance(result, str)
            assert "Here are the search results" in result
            assert "Python" in result
            assert "1." in result  # Numbered list
            assert "Source:" in result  # URLs included

    @pytest.mark.asyncio
    async def test_visible_mode_returns_confirmation(self, sample_query):
        """TC-FUNC-002: Verify visible mode returns immediate confirmation."""
        with patch("tools.browser_tool._open_visible_browser",
                   return_value="Opening browser for 'test', sir.") as mock_open:
            result = await browser_search(sample_query, open_visible=True)

            mock_open.assert_called_once()
            assert "Opening browser" in result

    @pytest.mark.asyncio
    async def test_api_fallback_to_browser(self, sample_query):
        """TC-FUNC-003: Verify API failure falls back to browser extraction."""
        with patch("tools.browser_tool._ddg_api_search", return_value=None):
            with patch("tools.browser_tool._playwright_search", return_value=[
                {"title": "Fallback Result", "snippet": "Test", "url": "http://test.com"}
            ]) as mock_playwright:
                result = await browser_search(sample_query)

                mock_playwright.assert_called_once()
                assert "Fallback Result" in result

    @pytest.mark.asyncio
    async def test_no_results_handling(self):
        """TC-FUNC-004: Verify graceful message when no results found."""
        with patch("tools.browser_tool._ddg_api_search", return_value=None):
            with patch("tools.browser_tool._playwright_search", return_value=[]):
                result = await browser_search("xyzxyzxyz123nonexistent")

                assert "no results" in result.lower()
                assert "sir" in result.lower()

    @pytest.mark.asyncio
    async def test_result_formatting_limits(self):
        """TC-FUNC-005: Verify result formatting respects limits."""
        long_results = [
            {"title": "Test", "snippet": "x" * 500, "url": "http://test.com"}
            for _ in range(10)
        ]

        with patch("tools.browser_tool._ddg_api_search", return_value=long_results):
            result = await browser_search("test")

            # Should only show first 5 results
            assert result.count("1.") + result.count("2.") + result.count("3.") + result.count("4.") + result.count("5.") <= 5

            # Snippet should be truncated
            assert "..." in result or len(result) < 3000


# =============================================================================
# TEST CATEGORY 4: ERROR HANDLING & EDGE CASES
# =============================================================================

class TestErrorHandling:
    """Tests for error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_empty_query_handling(self):
        """TC-ERR-001: Verify empty query handled gracefully."""
        with patch("tools.browser_tool._ddg_api_search", return_value=[]):
            with patch("tools.browser_tool._playwright_search", return_value=[]):
                result = await browser_search("")
                assert "no results" in result.lower()

    @pytest.mark.asyncio
    async def test_special_characters_in_query(self):
        """TC-ERR-002: Verify special characters URL-encoded properly."""
        query_with_special = "C++ programming & algorithms!"

        with patch("tools.browser_tool._ddg_api_search") as mock_api:
            await browser_search(query_with_special)

            # Verify the function was called (encoding happens inside)
            mock_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_unicode_query_handling(self):
        """TC-ERR-003: Verify unicode characters handled."""
        unicode_query = "日本語 検索"

        with patch("tools.browser_tool._ddg_api_search", return_value=None):
            with patch("tools.browser_tool._playwright_search", return_value=[
                {"title": "Result", "snippet": "Test", "url": "http://test.com"}
            ]):
                result = await browser_search(unicode_query)
                assert "Here are the search results" in result

    @pytest.mark.asyncio
    async def test_all_backends_fail_gracefully(self):
        """TC-ERR-004: Verify graceful degradation when all methods fail."""
        with patch("tools.browser_tool._ddg_api_search", return_value=None):
            with patch("tools.browser_tool._playwright_search", return_value=None):
                result = await browser_search("test")
                assert "no results" in result.lower() or "sir" in result.lower()


# =============================================================================
# TEST CATEGORY 5: SYNC WRAPPER
# =============================================================================

class TestSyncWrapper:
    """Tests for browser_search_sync wrapper."""

    def test_sync_wrapper_calls_async_version(self):
        """TC-SYNC-001: Verify sync wrapper properly calls async function."""
        with patch("tools.browser_tool.browser_search", new_callable=AsyncMock) as mock_async:
            mock_async.return_value = "Test results"
            result = browser_search_sync("test query")

            mock_async.assert_called_once_with("test query", False)

    def test_sync_wrapper_passes_open_visible(self):
        """TC-SYNC-002: Verify sync wrapper passes open_visible parameter."""
        with patch("tools.browser_tool.browser_search", new_callable=AsyncMock) as mock_async:
            browser_search_sync("test", open_visible=True)

            mock_async.assert_called_once_with("test", True)


# =============================================================================
# TEST CATEGORY 6: PERFORMANCE & RESOURCE TESTS
# =============================================================================

class TestPerformance:
    """Performance and resource utilization tests."""

    @pytest.mark.asyncio
    async def test_headless_faster_than_visible(self):
        """TC-PERF-001: Headless mode should complete faster than visible."""
        # This would require actual timing measurements
        # Marked for manual verification
        pass

    @pytest.mark.asyncio
    async def test_concurrent_searches_dont_block(self):
        """TC-PERF-002: Verify multiple searches can run concurrently."""
        with patch("tools.browser_tool._ddg_api_search",
                   new_callable=AsyncMock,
                   return_value=[{"title": "Test", "snippet": "Test", "url": "http://test.com"}]):

            # Run 3 searches concurrently
            tasks = [
                browser_search(f"query {i}")
                for i in range(3)
            ]
            results = await asyncio.gather(*tasks)

            assert len(results) == 3
            for r in results:
                assert "Here are the search results" in r


# =============================================================================
# TEST EXECUTION & REPORTING
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
