import sys
import types

import pytest


_FAKEABLE_MODULES = [
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
    "httpx",
]


@pytest.fixture(autouse=True)
def cleanup_injected_module_fakes():
    """Keep monkeypatched sys.modules fakes from leaking across tests."""
    yield
    for module_name in _FAKEABLE_MODULES:
        module = sys.modules.get(module_name)
        if isinstance(module, types.SimpleNamespace):
            del sys.modules[module_name]
