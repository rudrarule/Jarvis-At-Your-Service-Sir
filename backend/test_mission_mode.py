import asyncio
import importlib
import sys
import types


class _FakeTool:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    async def ainvoke(self, args):
        self.calls.append((self.name, args))
        return {"success": True, "tool": self.name, "args": args}


class _CompiledGraph:
    def __init__(self, nodes):
        self.nodes = nodes

    async def ainvoke(self, state, _config=None):
        for name in ("planner", "safety_gate", "executor", "verifier"):
            result = self.nodes[name](state)
            if asyncio.iscoroutine(result):
                result = await result
            state.update(result)
        return state


class _StateGraph:
    def __init__(self, _state_type):
        self.nodes = {}

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_edge(self, *_args):
        return None

    def compile(self):
        return _CompiledGraph(self.nodes)


def _install_graph_fakes(tool_calls):
    # Ensure we don't have a SimpleNamespace mock from other tests lingering in sys.modules
    if "workflows.mission_graph" in sys.modules:
        del sys.modules["workflows.mission_graph"]
    
    sys.modules["langgraph.graph"] = types.SimpleNamespace(
        StateGraph=_StateGraph,
        START="__start__",
        END="__end__",
    )
    sys.modules["workflows.tool_wrapper"] = types.SimpleNamespace(
        ALL_TOOLS=[
            _FakeTool("browser_open_url", tool_calls),
            _FakeTool("browser_observe", tool_calls),
            _FakeTool("weather_check", tool_calls),
            _FakeTool("file_write", tool_calls),
            _FakeTool("whatsapp_send_message", tool_calls),
        ]
    )


def test_mission_graph_research_save_executes_safe_steps():
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))

    state = asyncio.run(mission_graph.mission_graph_app.ainvoke({
        "user_goal": "research LangGraph agents and save to langgraph_notes.md",
        "session_id": "mission-test",
    }))

    called_tools = [name for name, _args in tool_calls]
    assert called_tools == ["browser_open_url", "browser_observe", "file_write"]
    assert state["verified"] is True
    assert "Mission completed" in state["final_answer"]
    assert tool_calls[-1][1]["path"] == "langgraph_notes.md"
    assert "Mission goal" in tool_calls[-1][1]["content"]


def test_llm_planner_output_is_validated_and_used():
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))

    mission_graph.llm_plan_mission = lambda _goal: asyncio.sleep(0, result=[
        {
            "type": "browser",
            "tool": "browser_open_url",
            "args": {"url": "https://example.com/search?q=ai"},
            "instruction": "Open planned search.",
            "risk": "low",
        },
        {
            "type": "whatsapp",
            "tool": "whatsapp_send_message",
            "args": {"contact": "Rahul", "message": "ignored"},
            "instruction": "Send planned summary.",
            "risk": "high",
        },
    ])

    state = asyncio.run(mission_graph.mission_graph_app.ainvoke({
        "user_goal": "research AI and message Rahul",
        "session_id": "mission-test",
    }))

    assert [name for name, _args in tool_calls] == ["browser_open_url"]
    assert tool_calls[0][1]["url"] == "https://example.com/search?q=ai"
    assert state["pending_confirmation"][0]["tool"] == "whatsapp_send_message"
    assert state["pending_confirmation"][0]["requires_confirmation"] is True


def test_invalid_llm_planner_output_falls_back_to_heuristic():
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))
    mission_graph.llm_plan_mission = lambda _goal: asyncio.sleep(0, result=[])

    state = asyncio.run(mission_graph.mission_graph_app.ainvoke({
        "user_goal": "research LangGraph agents and save to fallback_notes.md",
        "session_id": "mission-test",
    }))

    called_tools = [name for name, _args in tool_calls]
    assert called_tools == ["browser_open_url", "browser_observe", "file_write"]
    assert state["verified"] is True
    assert tool_calls[-1][1]["path"] == "fallback_notes.md"


def test_validator_rejects_unsafe_tools_and_bad_args():
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))

    plan = mission_graph._validate_llm_plan({
        "steps": [
            {"tool": "system_control", "args": {"command": "shutdown"}},
            {"tool": "browser_open_url", "args": {"url": "javascript:alert(1)"}},
            {"tool": "file_write", "args": {"path": "notes.exe"}},
            {"tool": "whatsapp_send_message", "args": {"contact": "Rahul"}},
        ]
    })

    assert [step["tool"] for step in plan] == ["whatsapp_send_message"]
    assert plan[0]["requires_confirmation"] is True


def test_mission_graph_pauses_before_whatsapp_send():
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))

    state = asyncio.run(mission_graph.mission_graph_app.ainvoke({
        "user_goal": "find latest AI news and message Rahul the summary",
        "session_id": "mission-test",
    }))

    called_tools = [name for name, _args in tool_calls]
    assert called_tools == ["browser_open_url", "browser_observe"]
    assert state["verified"] is False
    assert "paused before risky action" in state["final_answer"]
    assert state["pending_confirmation"][0]["tool"] == "whatsapp_send_message"


def test_mission_confirmation_executes_paused_step_only():
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))

    state = asyncio.run(mission_graph.mission_graph_app.ainvoke({
        "user_goal": "find latest AI news and message Rahul the summary",
        "session_id": "mission-test",
    }))
    mission_graph.store_active_mission("mission-test", state)

    tool_calls.clear()
    reply = asyncio.run(mission_graph.handle_mission_confirmation("mission-test", "yes"))

    called_tools = [name for name, _args in tool_calls]
    assert called_tools == ["whatsapp_send_message"]
    assert tool_calls[0][1]["contact"] == "Rahul"
    assert "Mission goal" in tool_calls[0][1]["message"]
    assert "Mission completed" in reply
    assert mission_graph.get_active_mission("mission-test") is None


def test_generate_response_routes_mission_before_tier3():
    class _MissionApp:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, state, config):
            self.calls.append((state, config))
            return {"final_answer": "mission routed"}

    app = _MissionApp()
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
        mission_graph_app=app,
        clear_mission=lambda *_args, **_kwargs: None,
        get_active_mission=lambda *_args, **_kwargs: None,
        handle_mission_confirmation=lambda *_args, **_kwargs: asyncio.sleep(0, result=""),
        store_active_mission=lambda *_args, **_kwargs: None,
    )

    llm_service = importlib.reload(importlib.import_module("services.llm_service"))
    llm_service._tier1_regex = lambda *_args, **_kwargs: asyncio.sleep(0, result=None)
    llm_service._classify_vision_intent = lambda *_args, **_kwargs: False
    llm_service.is_complex_query = lambda *_args, **_kwargs: True

    session_module = importlib.import_module("services.session_service")
    session_module.chat_sessions.clear()

    result = asyncio.run(llm_service.generate_response(
        "research LangGraph agents and save to notes.md",
        "mission-route-test",
    ))

    assert result == "mission routed"
    assert len(app.calls) == 1
    assert app.calls[0][0]["user_goal"] == "research LangGraph agents and save to notes.md"


def test_generate_response_resumes_active_mission_confirmation():
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
        get_active_mission=lambda *_args, **_kwargs: {
            "created_at": __import__("datetime").datetime.now(),
            "pending_confirmation": [{"tool": "whatsapp_send_message"}],
        },
        handle_mission_confirmation=lambda *_args, **_kwargs: asyncio.sleep(0, result="resumed mission"),
        store_active_mission=lambda *_args, **_kwargs: None,
    )

    llm_service = importlib.reload(importlib.import_module("services.llm_service"))
    session_module = importlib.import_module("services.session_service")
    session_module.chat_sessions.clear()

    result = asyncio.run(llm_service.generate_response("yes", "mission-route-test"))

    assert result == "resumed mission"
    
    # Cleanup mock to avoid breaking subsequent tests
    if "workflows.mission_graph" in sys.modules:
        del sys.modules["workflows.mission_graph"]

def test_heuristic_plan_includes_weather():
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))

    state = asyncio.run(mission_graph.mission_graph_app.ainvoke({
        "user_goal": "check weather in London and save to weather.txt",
        "session_id": "mission-test",
    }))

    called_tools = [name for name, _args in tool_calls]
    assert "weather_check" in called_tools
    assert "file_write" in called_tools
    assert tool_calls[0][1]["location"] == "London"
    assert tool_calls[1][1]["path"] == "weather.txt"


def test_execute_plan_handles_tool_errors():
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))

    # Force a failure for browser_open_url
    async def failing_tool(_args):
        raise Exception("Network timeout")

    # Monkey patch the reloaded module's tools
    mission_graph.ALL_TOOLS[0].ainvoke = failing_tool

    state = asyncio.run(mission_graph.mission_graph_app.ainvoke({
        "user_goal": "research AI and save",
        "session_id": "mission-test",
    }))

    assert state["verified"] is False
    assert "Network timeout" in state["final_answer"]
    assert any(res["status"] == "failed" for res in state["step_results"])


def test_mission_graph_complex_query():
    """Test a query that combines multiple research and notification steps."""
    tool_calls = []
    _install_graph_fakes(tool_calls)
    mission_graph = importlib.reload(importlib.import_module("workflows.mission_graph"))

    # Complex goal: research, weather, and save
    goal = "research the latest LangGraph features, check weather in SF, and save everything to research_bundle.md"
    
    state = asyncio.run(mission_graph.mission_graph_app.ainvoke({
        "user_goal": goal,
        "session_id": "complex-test",
    }))

    called_tools = [name for name, _args in tool_calls]
    # Expected: browser_open -> browser_observe -> weather_check -> file_write
    assert called_tools == ["browser_open_url", "browser_observe", "weather_check", "file_write"]
    
    assert state["verified"] is True
    assert "Mission completed" in state["final_answer"]
    
    # Verify file content summary was prepared
    last_call_args = tool_calls[-1][1]
    assert last_call_args["path"] == "research_bundle.md"
    assert "Mission goal: " in last_call_args["content"]
    assert "'tool': 'weather_check'" in last_call_args["content"]


def test_extract_file_path_logic():
    from workflows.mission_graph import _extract_file_path
    assert _extract_file_path("save to notes.txt") == "notes.txt"
    assert _extract_file_path("save in data/results.json") == "data/results.json"
    assert _extract_file_path("save as summary.md") == "summary.md"
    assert _extract_file_path("just research and save") == "mission_notes.md"
