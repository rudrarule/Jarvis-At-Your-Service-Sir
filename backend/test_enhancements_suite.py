import os
import sqlite3
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END

@pytest.mark.asyncio
async def test_extract_token_usage():
    from workflows.master_graph import _extract_token_usage
    # 1. Test standard usage_metadata
    msg1 = AIMessage(content="hello", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    res1 = _extract_token_usage(msg1)
    assert res1 == {"input": 10, "output": 5, "total": 15}

    # 2. Test response_metadata usage
    msg2 = AIMessage(content="hello", response_metadata={"usage": {"prompt_tokens": 8, "completion_tokens": 4}})
    res2 = _extract_token_usage(msg2)
    assert res2 == {"input": 8, "output": 4, "total": 12}

    # 3. Test Bedrock metrics
    msg3 = AIMessage(content="hello", response_metadata={"amazon-bedrock-invocationMetrics": {"inputTokenCount": 20, "outputTokenCount": 10}})
    res3 = _extract_token_usage(msg3)
    assert res3 == {"input": 20, "output": 10, "total": 30}


def test_should_continue_token_budget():
    from workflows.master_graph import should_continue
    # Test that if total tokens is under budget, it behaves normally (no tool calls, so END)
    state_under = {
        "messages": [HumanMessage(content="test"), AIMessage(content="res")],
        "token_usage": {"total": 500},
        "token_budget": 1000,
        "iteration": 0
    }
    assert should_continue(state_under) == END
    
    # Test that if total tokens is over budget, it returns loop_halt
    state_over = {
        "messages": [HumanMessage(content="test"), AIMessage(content="res")],
        "token_usage": {"total": 1500},
        "token_budget": 1000,
        "iteration": 0
    }
    assert should_continue(state_over) == "loop_halt"


@pytest.mark.asyncio
async def test_sqlite_saver_persistence(tmp_path):
    from workflows.master_graph import build_master_graph
    # Test that SqliteSaver correctly persists state.
    # We set the database path to a temp location via JARVIS_GRAPH_DB.
    temp_db_path = str(tmp_path / "test_jarvis_graph.db")
    
    old_env = os.environ.get("JARVIS_GRAPH_DB")
    old_ckpt = os.environ.get("JARVIS_GRAPH_CHECKPOINTS")
    os.environ["JARVIS_GRAPH_DB"] = temp_db_path
    os.environ["JARVIS_GRAPH_CHECKPOINTS"] = "true"
    try:
        app = build_master_graph()
        
        # Verify db file is created
        assert os.path.exists(temp_db_path)
        
        # Setup tables manually
        app.checkpointer.setup()
        
        # Check tables exist
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        assert "checkpoints" in tables
        assert "writes" in tables
        conn.close()
    finally:
        if old_env is not None:
            os.environ["JARVIS_GRAPH_DB"] = old_env
        else:
            os.environ.pop("JARVIS_GRAPH_DB", None)
        if old_ckpt is not None:
            os.environ["JARVIS_GRAPH_CHECKPOINTS"] = old_ckpt
        else:
            os.environ.pop("JARVIS_GRAPH_CHECKPOINTS", None)


@pytest.mark.asyncio
async def test_dynamic_tool_binding():
    # We want to verify that in call_model, the LLM is bound only with the filtered tools.
    import workflows.master_graph
    workflows.master_graph._llm_cache.clear()  # Clear cache so mock is used

    app = workflows.master_graph.build_master_graph()
    
    # Let's inspect call_model behavior by calling it directly or inspecting how tools are bound.
    # We can mock the _get_llm call and inspect what tools were passed to bind_tools.
    mock_llm = MagicMock()
    
    # Mock return value of bound_llm.ainvoke to avoid actual Bedrock API call
    mock_response = AIMessage(content="mocked response", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    mock_bound_llm = MagicMock()
    mock_bound_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools.return_value = mock_bound_llm
    
    with patch.object(workflows.master_graph, "_get_llm", return_value=mock_llm):
        # 1. Test case: file_write_completed is True -> browser tools should be stripped
        state = {
            "messages": [HumanMessage(content="write a report")],
            "file_write_completed": True,
            "iteration": 0
        }
        
        # Master graph has a node named "agent" which runs call_model.
        agent_node = app.nodes["agent"]
        
        # Call the node function using bound.ainvoke
        config = {"configurable": {"thread_id": "test_thread"}}
        await agent_node.bound.ainvoke(state, config)
        
        # Verify bind_tools was called
        mock_llm.bind_tools.assert_called()
        bound_tools = mock_llm.bind_tools.call_args[0][0]
        # Assert none of the bound tools start with "browser_"
        for t in bound_tools:
            assert not t.name.startswith("browser_")
            
        # 2. Test case: last action was browser_observe -> file_search should be stripped
        mock_llm.reset_mock()
        state_observe = {
            "messages": [HumanMessage(content="observe page")],
            "tool_history": [{"phase": "result", "tool": "browser_observe", "success": True}],
            "iteration": 0
        }
        await agent_node.bound.ainvoke(state_observe, config)
        bound_tools_observe = mock_llm.bind_tools.call_args[0][0]
        tool_names = [t.name for t in bound_tools_observe]
        assert "file_search" not in tool_names
