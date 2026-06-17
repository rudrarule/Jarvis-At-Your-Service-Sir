"""Offline unit tests for route-scoped MCP tool binding.

Proves that _scope_mcp_tools_by_route keeps native tools on every route and
drops MCP tools that don't belong to the route's allowed groups.

We exec the REAL source slice from master_graph.py (the route-scoping block)
so the test exercises the shipped logic without importing langgraph/bedrock,
which aren't available in every test environment.
"""
import os
import types
import pathlib

_SRC = pathlib.Path(__file__).with_name("workflows") / "master_graph.py"
_START = "# ── Route-scoped MCP tool binding"
_END = "# ── LLM Instance Cache"


def _load_real_logic():
    text = _SRC.read_text(encoding="utf-8")
    s = text.index(_START)
    e = text.index(_END, s)
    ns: dict = {"os": os}
    exec(text[s:e], ns)  # noqa: S102 — executing our own shipped source
    return ns


_NS = _load_real_logic()
_scope = _NS["_scope_mcp_tools_by_route"]
_GROUPS = _NS["_MCP_ROUTE_GROUPS"]


def _native(name):
    return types.SimpleNamespace(name=name, metadata={})


def _mcp(name, group):
    return types.SimpleNamespace(name=name, metadata={"mcp": True, "mcp_group": group})


def _tools():
    return [
        _native("browser_open_url"),
        _native("file_write"),
        _native("whatsapp_send_message"),
        _mcp("tavily_search", "web"),
        _mcp("fetch", "web"),
        _mcp("sequentialthinking", "web"),
        _mcp("read_file", "fs"),
        _mcp("write_file", "fs"),
    ]


def _names(tools):
    return {t.name for t in tools}


NATIVE = {"browser_open_url", "file_write", "whatsapp_send_message"}


def setup_function(_):
    os.environ["JARVIS_ROUTE_SCOPED_TOOLS"] = "true"


def test_native_tools_always_survive():
    for route in ("browser", "tool", "mission", "vision", "", "garbage"):
        out = _names(_scope(_tools(), route))
        assert NATIVE <= out, f"native tool dropped on route={route!r}"


def test_browser_keeps_web_and_fs():
    # browser route now allows both web research and filesystem MCP
    # (e.g. "search X and save it to a file")
    out = _names(_scope(_tools(), "browser"))
    assert {"tavily_search", "fetch", "sequentialthinking"} <= out
    assert {"read_file", "write_file"} <= out


def test_tool_route_keeps_fs_drops_web():
    out = _names(_scope(_tools(), "tool"))
    assert {"read_file", "write_file"} <= out
    assert "tavily_search" not in out and "fetch" not in out


def test_mission_keeps_everything():
    assert _names(_scope(_tools(), "mission")) == _names(_tools())


def test_vision_drops_all_mcp():
    assert _names(_scope(_tools(), "vision")) == NATIVE


def test_unknown_route_is_fail_open():
    for route in ("", "garbage", None):
        assert _names(_scope(_tools(), route)) == _names(_tools()), f"route={route!r}"


def test_flag_off_is_passthrough():
    os.environ["JARVIS_ROUTE_SCOPED_TOOLS"] = "false"
    assert _names(_scope(_tools(), "tool")) == _names(_tools())


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        setup_function(None)
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
