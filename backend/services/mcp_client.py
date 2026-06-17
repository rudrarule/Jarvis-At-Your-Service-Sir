"""MCP (Model Context Protocol) integration for J.A.R.V.I.S.

Loads tools from external MCP servers and exposes them as LangChain tools that
plug straight into the master_graph ReAct agent's ALL_TOOLS list.

Design:
  * Flag-gated by JARVIS_MCP (default OFF) — nothing changes until you enable it.
  * FAIL-OPEN — any error returns no tools and logs; startup never breaks.
  * Curated by default (Tavily web search + Fetch) to avoid flooding the model
    with tools (Nova's tool-calling degrades with too many). Filesystem is opt-in
    via JARVIS_MCP_FS=true because it adds ~10 tools.
  * Must be loaded on the app's running event loop (FastAPI lifespan), NOT at
    import time — MCP stdio sessions are bound to the loop that created them.
"""
from __future__ import annotations

import os
import sys

# Kept module-global so the MCP client (and its stdio sessions) stay alive for
# the lifetime of the process — otherwise tool calls would fail mid-session.
_client = None


def mcp_enabled() -> bool:
    return os.getenv("JARVIS_MCP", "false").strip().lower() in {"1", "true", "yes", "on"}


# Filesystem MCP tool names (server-filesystem). Used to bucket tools so the
# route-scoper can keep file MCP tools off web-research turns and vice-versa.
_FS_TOOLNAMES = {
    "read_file", "read_text_file", "read_media_file", "write_file", "edit_file",
    "create_directory", "list_directory", "list_directory_with_sizes",
    "directory_tree", "move_file", "search_files", "get_file_info",
    "list_allowed_directories",
}

_VOICE_TOOLNAMES = {
    "speak_text", "stop_speaking", "set_voice_parameters", "list_available_voices",
}

_MONITORING_TOOLNAMES = {
    "get_system_metrics", "list_recent_missions", "get_mission_details", "check_backend_logs",
}

_MEMORY_TOOLNAMES = {
    "remember", "recall", "list_memories",
}

# Official Google MCP tools (remote HTTP servers). Bucketed into the 'google'
# route group so they ride along on tool/mission turns but stay off pure
# web-research / browser turns.
_GOOGLE_TOOLNAMES = {
    # Gmail
    "search_threads", "get_thread", "create_draft", "list_drafts", "list_labels",
    # Calendar
    "create_event", "delete_event", "find_free_time", "get_event",
    "list_calendars", "list_events", "respond_to_event", "update_event",
    # Drive
    "create_file", "download_file_content", "get_file_metadata",
    "get_file_permissions", "list_recent_files", "read_file_content",
    # NOTE: Drive's "search_files" collides with the filesystem MCP's
    # "search_files". _mcp_group() keeps the filesystem mapping first, so when
    # both servers are enabled the name resolves to 'fs'. Harmless in practice:
    # 'fs' and 'google' are allowed on the same routes (tool/mission).
    "search_files",
}


def google_enabled() -> bool:
    return os.getenv("JARVIS_MCP_GOOGLE", "false").strip().lower() in {"1", "true", "yes", "on"}


def _mcp_group(tool_name: str) -> str:
    """Bucket an MCP tool into a coarse route group.
    'fs'         -> filesystem operations (local file actions).
    'voice'      -> always-on voice settings and controls.
    'monitoring' -> system monitoring and logging metrics.
    'memory'     -> long-term personal memory (store/recall facts).
    'google'     -> Gmail / Calendar / Drive (remote Google MCP servers).
    'web'        -> web search / fetch / reasoning (research & lookups). Default.
    """
    if tool_name in _FS_TOOLNAMES:
        return "fs"
    if tool_name in _VOICE_TOOLNAMES:
        return "voice"
    if tool_name in _MONITORING_TOOLNAMES:
        return "monitoring"
    if tool_name in _MEMORY_TOOLNAMES:
        return "memory"
    if tool_name in _GOOGLE_TOOLNAMES:
        return "google"
    return "web"


def _server_config() -> dict:
    """Curated MCP servers. Add more here as needed; keep the count small so the
    agent's active tool list stays reliable."""
    servers: dict = {}

    # Web search — fixes weak DuckDuckGo search / SEO confabulation. Free Tavily key.
    if os.getenv("TAVILY_API_KEY"):
        servers["search"] = {
            "command": "npx",
            "args": ["-y", "tavily-mcp"],
            "transport": "stdio",
            "env": {"TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", "")},
        }

    # Fetch — turn a URL into clean markdown (read-only research without a browser).
    servers["fetch"] = {
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "transport": "stdio",
    }

    # Sequential Thinking — structured reasoning scratchpad for complex problems.
    servers["thinking"] = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "transport": "stdio",
    }

    # Always-On Voice — wraps Edge-TTS and voice settings local controls.
    python_exe = sys.executable or "python"
    servers["voice"] = {
        "command": python_exe,
        "args": [os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_voice_server.py"))],
        "transport": "stdio",
        "env": {
            "JARVIS_MUTE": os.getenv("JARVIS_MUTE", "false"),
            "PATH": os.getenv("PATH", ""),
        }
    }

    # Real-Time Monitoring — retrieves psutil system metrics and sqlite mission logs.
    servers["monitoring"] = {
        "command": python_exe,
        "args": [os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_monitoring_server.py"))],
        "transport": "stdio",
        "env": {
            "JARVIS_MUTE": os.getenv("JARVIS_MUTE", "false"),
            "PATH": os.getenv("PATH", ""),
        }
    }

    # Personal Memory — wraps the ChromaDB RAG memory_service so the agent can
    # deliberately store/recall personal facts (remember / recall / list_memories).
    servers["memory"] = {
        "command": python_exe,
        "args": [os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_memory_server.py"))],
        "transport": "stdio",
        "env": {
            "PATH": os.getenv("PATH", ""),
        }
    }

    # Google (Gmail / Calendar / Drive) — opt-in remote HTTP MCP servers.
    # Unlike the local stdio servers above, these are authenticated with a
    # Google OAuth2 bearer token in the request headers. Fail-open: if the token
    # can't be obtained, we just skip these servers (no startup break).
    if google_enabled():
        try:
            from services.google_auth import get_access_token

            token = get_access_token()
            if token:
                google_headers = {"Authorization": f"Bearer {token}"}
                servers["gmail"] = {
                    "transport": "streamable_http",
                    "url": "https://gmailmcp.googleapis.com/mcp/v1",
                    "headers": google_headers,
                }
                servers["gcal"] = {
                    "transport": "streamable_http",
                    "url": "https://calendarmcp.googleapis.com/mcp/v1",
                    "headers": google_headers,
                }
                servers["gdrive"] = {
                    "transport": "streamable_http",
                    "url": "https://drivemcp.googleapis.com/mcp/v1",
                    "headers": google_headers,
                }
            else:
                print("[MCP] Google enabled but no OAuth token available; skipping Gmail/Calendar/Drive.")
        except Exception as exc:
            print(f"[MCP] Google MCP setup failed, skipping (fail-open): {exc}")

    # Filesystem — opt-in (adds many tools). Scope it to a safe root.
    if os.getenv("JARVIS_MCP_FS", "false").strip().lower() in {"1", "true", "yes", "on"}:
        servers["fs"] = {
            "command": "npx",
            "args": [
                "-y", "@modelcontextprotocol/server-filesystem",
                os.getenv("JARVIS_MCP_FS_ROOT", os.path.expanduser("~")),
            ],
            "transport": "stdio",
        }

    return servers


async def load_mcp_tools() -> list:
    """Load tools from the configured MCP servers. Returns [] if disabled or on error."""
    global _client
    if not mcp_enabled():
        return []

    servers = _server_config()
    if not servers:
        print("[MCP] Enabled but no servers configured.")
        return []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        _client = MultiServerMCPClient(servers)
        tools = await _client.get_tools()
        # Tag so other code (e.g. route-scoping) can recognize MCP-sourced tools
        # and bucket them by route group (web vs fs).
        for t in tools:
            try:
                t.metadata = {
                    **(getattr(t, "metadata", None) or {}),
                    "mcp": True,
                    "mcp_group": _mcp_group(getattr(t, "name", "")),
                }
            except Exception:
                pass
        print(f"[MCP] Loaded {len(tools)} tools from {list(servers)}: {[t.name for t in tools]}")
        return tools
    except Exception as exc:
        print(f"[MCP] Load failed, continuing without MCP tools (fail-open): {exc}")
        return []
