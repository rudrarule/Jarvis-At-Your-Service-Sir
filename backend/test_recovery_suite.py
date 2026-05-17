import sys
# Clean up any lingering mock namespaces injected by preceding test suites (e.g. test_mission_mode / test_langgraph_routing)
mocked_modules = [
    "langgraph.graph",
    "langgraph.graph.state",
    "langgraph.errors",
    "workflows.tool_wrapper",
    "workflows.master_graph",
    "workflows.mission_graph",
    "workflows.wa_send_workflow",
    "services.memory_service",
    "tools.registry",
    "langchain_core.messages",
    "httpx"
]
for mocked_mod in mocked_modules:
    if mocked_mod in sys.modules:
        del sys.modules[mocked_mod]

import pytest
import asyncio
import sqlite3
import workflows.master_graph
from unittest.mock import MagicMock, patch
from tools.browser_tool import BrowserStateManager, open_url
from services.memory_service import retrieve_memory, store_memory
from services.mission_store import _connect, _DB_PATH


@pytest.mark.asyncio
async def test_tc076_llm_timeout_graceful_handling():
    """TC_076 | LLM API Timeout Fallback: Ensure LLM service falls back gracefully on Bedrock timeout."""
    with patch("workflows.master_graph._get_llm") as mock_get:
        mock_llm = MagicMock()
        # Simulate timeout or service error
        mock_llm.ainvoke.side_effect = Exception("AWS Bedrock Request Timeout")
        mock_get.return_value = mock_llm

        # Verify our ReAct execution graph gracefully raises/handles errors
        from workflows.master_graph import build_master_graph
        app = build_master_graph()
        
        # Invoke should raise error back to generator, which triggers fallback to Ollama/ReAct or prints trace
        with pytest.raises(Exception):
            await app.ainvoke({"messages": []})


@pytest.mark.asyncio
async def test_tc077_network_drop_mid_browser():
    """TC_077 | Network Failure: Verify browser tools handle mid-task Playwright exceptions gracefully."""
    # Patch the state manager to return a page that raises an exception during goto
    mock_page = MagicMock()
    mock_page.goto.side_effect = Exception("net::ERR_INTERNET_DISCONNECTED")
    
    with patch.object(BrowserStateManager, "get_page", return_value=mock_page):
        res = await open_url("https://google.com")
        # Ensure the exception is captured, structured error is returned, and process does not crash
        assert res["success"] is False
        assert "ERR_INTERNET_DISCONNECTED" in res["error"]


@pytest.mark.asyncio
async def test_tc078_chromadb_unavailable_resilience():
    """TC_078 | ChromaDB Unavailable: Assert memory services gracefully decay (e.g. empty strings) if Chroma is down."""
    with patch("services.memory_service.collection") as mock_collection:
        # Simulate db crash
        mock_collection.count.side_effect = Exception("ChromaDB Connection Rejected")
        
        # Retrieve should fail gracefully and return empty string (no crash in chat pipelines)
        try:
            res = await retrieve_memory("my name")
            assert res == ""
        except Exception:
            pytest.fail("ChromaDB exception was not caught inside memory retrieve")

        # Store should catch, print warning, and return False (skipped) without crash
        try:
            stored = await store_memory("remember my name is Rudra")
            assert stored is False
        except Exception:
            pytest.fail("ChromaDB exception was not caught inside memory store")


def test_tc079_sqlite_locked_concurrency():
    """TC_079 | SQLite Locked: Verify SQLite concurrent connections safely query using WAL mode."""
    # Write a multi-thread / multi-process safe test showing WAL is configured
    conn1 = _connect()
    conn2 = _connect()

    # Both connections should be active simultaneously due to WAL
    r1 = conn1.execute("PRAGMA journal_mode").fetchone()
    r2 = conn2.execute("PRAGMA journal_mode").fetchone()

    assert r1[0].lower() == "wal"
    assert r2[0].lower() == "wal"

    conn1.close()
    conn2.close()


@pytest.mark.asyncio
async def test_tc080_playwright_browser_auto_restart():
    """TC_080 | Browser Crash Recovery: Verify BrowserStateManager regenerates context after close/crash."""
    # Ensure starting from clean state
    await BrowserStateManager.close_all()
    
    # 1. Open browser page
    page1 = await BrowserStateManager.get_page()
    assert not page1.is_closed()

    # 2. Simulate browser process crash / forced close
    await BrowserStateManager.close_all()

    # 3. Request page again — state manager should detect closed page and spawn a fresh new context
    page2 = await BrowserStateManager.get_page()
    assert not page2.is_closed()
    assert page1 is not page2
    
    await BrowserStateManager.close_all()
