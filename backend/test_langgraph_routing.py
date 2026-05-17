import asyncio
import importlib
import sys
import types


class _Message:
    def __init__(self, content):
        self.content = content


class _FakeGraph:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, state, config):
        self.calls.append((state, config))
        return {"messages": [_Message("graph ok")]}


def _install_import_fakes(fake_graph):
    sys.modules.setdefault("httpx", types.SimpleNamespace())
    sys.modules["services.memory_service"] = types.SimpleNamespace(
        store_memory=lambda *_args, **_kwargs: asyncio.sleep(0, result=False),
        retrieve_memory=lambda *_args, **_kwargs: asyncio.sleep(0, result=""),
    )
    sys.modules["tools.registry"] = types.SimpleNamespace(
        TOOL_SCHEMAS=[],
        TOOL_GROUPS={},
        get_schemas_for_intent=lambda *_args, **_kwargs: [],
        execute_tool=lambda *_args, **_kwargs: asyncio.sleep(0, result=""),
    )
    sys.modules["workflows.wa_send_workflow"] = types.SimpleNamespace(
        get_active_workflow=lambda *_args, **_kwargs: None,
    )
    sys.modules["workflows.mission_graph"] = types.SimpleNamespace(
        clear_mission=lambda *_args, **_kwargs: None,
        get_active_mission=lambda *_args, **_kwargs: None,
        handle_mission_confirmation=lambda *_args, **_kwargs: asyncio.sleep(0, result=""),
        store_active_mission=lambda *_args, **_kwargs: None,
    )
    sys.modules["workflows.master_graph"] = types.SimpleNamespace(
        master_graph_app=fake_graph,
    )
    sys.modules["langchain_core.messages"] = types.SimpleNamespace(
        SystemMessage=_Message,
        HumanMessage=_Message,
        AIMessage=_Message,
    )
    sys.modules["langgraph.errors"] = types.SimpleNamespace(
        GraphRecursionError=RuntimeError,
    )


def test_complex_query_routes_to_langgraph_without_missing_history():
    fake_graph = _FakeGraph()
    _install_import_fakes(fake_graph)
    llm_service = importlib.reload(importlib.import_module("services.llm_service"))

    llm_service._tier1_regex = lambda *_args, **_kwargs: asyncio.sleep(0, result=None)
    llm_service._classify_vision_intent = lambda *_args, **_kwargs: False
    llm_service.is_complex_query = lambda *_args, **_kwargs: True

    session_module = importlib.import_module("services.session_service")
    session_module.chat_sessions.clear()

    queries = [
        "weather in Delhi",
        "stock price for NVIDIA",
        "open duckduckgo",
    ]

    for query in queries:
        result = asyncio.run(llm_service.generate_response(query, "test-session"))
        assert result == "graph ok"

    assert len(fake_graph.calls) == len(queries)
    for query, (state, config) in zip(queries, fake_graph.calls):
        assert state["messages"][-1].content == query
        assert config["configurable"]["thread_id"].startswith("test-session:")
