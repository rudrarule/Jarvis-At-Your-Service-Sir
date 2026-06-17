"""Personal Memory MCP server for J.A.R.V.I.S.

Exposes the existing ChromaDB RAG memory_service as explicit agent tools so the
model can deliberately store and recall personal facts (not just rely on the
automatic context-injection path).

CRITICAL — clean stdio:
  FastMCP's stdio transport uses *stdout* for the JSON-RPC protocol. Both
  db.chroma_client and services.memory_service print diagnostics to stdout
  (e.g. "[ChromaDB] Ready...", "[MEM] ..."), which would corrupt the stream.
  So we redirect stdout -> stderr both at import time and around every
  service call. The protocol stream (FastMCP's own writes) is untouched.
"""
import sys
import os
import asyncio
import contextlib

# Ensure project root is in path (mirrors mcp_voice_server / mcp_monitoring_server).
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import the memory service with stdout muted -> stderr, since importing it
# triggers db.chroma_client's top-level "[ChromaDB] Ready" print.
with contextlib.redirect_stdout(sys.stderr):
    from services import memory_service

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("PersonalMemory")


@mcp.tool()
async def remember(text: str) -> str:
    """
    Persist a personal fact about the user to long-term memory (ChromaDB).
    Use this when the user shares something worth recalling later — their name,
    preferences, goals, projects, or anything they ask you to remember.
    Near-duplicates are skipped automatically.
    """
    try:
        with contextlib.redirect_stdout(sys.stderr):
            stored = await memory_service.store_memory(text, force=True)
        if stored:
            return f"Stored to long-term memory: {text[:80]}"
        return "Not stored — a near-identical memory already exists."
    except Exception as e:
        return f"Failed to store memory: {e}"


@mcp.tool()
async def recall(query: str, n: int = 5) -> str:
    """
    Search long-term memory for facts relevant to a query and return the top
    matches. Use before answering anything that may depend on what you know
    about the user. Returns an empty result if nothing relevant is stored.
    """
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = await memory_service.retrieve_memory(query, n_results=n)
        return result or "No relevant memories found."
    except Exception as e:
        return f"Failed to recall memories: {e}"


@mcp.tool()
async def list_memories() -> str:
    """
    List every stored long-term memory (text + timestamp). Useful for auditing
    or when the user asks what you remember about them.
    """
    try:
        with contextlib.redirect_stdout(sys.stderr):
            memories = memory_service.get_all_memories()
        if not memories:
            return "No memories stored yet."
        lines = ["=== STORED MEMORIES ==="]
        for m in memories:
            ts = (m.get("timestamp") or "")[:19]
            lines.append(f"[{ts}] {m.get('text', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list memories: {e}"


if __name__ == "__main__":
    mcp.run()
