import asyncio
import os
import sys

# Ensure backend directory is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.mcp_client import load_mcp_tools, mcp_enabled

async def main():
    print("=== MCP SERVER INTEGRATION TEST ===")
    try:
        import dotenv
        dotenv.load_dotenv()
    except ImportError:
        pass
        
    os.environ["JARVIS_MCP"] = "true"
    os.environ["JARVIS_MUTE"] = "true"
    
    # We must have TAVILY_API_KEY to test it, let's use a dummy key if not set to avoid skipping,
    # but since the server is configured, load_mcp_tools will spin up whatever is enabled.
    if not os.getenv("TAVILY_API_KEY"):
        os.environ["TAVILY_API_KEY"] = "tvly-test-key"

    print("Loading MCP tools...")
    sys.stdout.flush()
    tools = await load_mcp_tools()
    
    if not tools:
        print("[-] No MCP tools loaded. Ensure servers are configured and runnable.")
        sys.stdout.flush()
        os._exit(1)
        
    print(f"[+] Loaded {len(tools)} tools:")
    for t in tools:
        print(f"  - {t.name}: {t.description[:60]}...")
    sys.stdout.flush()

    print("\n=== STARTING FUNCTIONAL TESTS ===")
    sys.stdout.flush()

    test_cases = [
        ("get_system_metrics", {}),
        ("list_recent_missions", {"limit": 3}),
        ("list_available_voices", {}),
        ("speak_text", {"text": "Testing voice channel. Systems online, sir.", "interrupt": True}),
        ("sequentialthinking", {
            "thought": "Testing MCP thought integration.",
            "thoughtNumber": 1,
            "totalThoughts": 1,
            "nextThoughtNeeded": False
        }),
        ("tavily_search", {"query": "current weather in New York"}),
        ("fetch", {"url": "https://example.com"})
    ]

    # Map name to tool
    tool_map = {t.name: t for t in tools}
    
    for name, args in test_cases:
        if name in tool_map:
            print(f"\n[+] Testing tool: {name}({args})...")
            sys.stdout.flush()
            try:
                tool = tool_map[name]
                result = await tool.ainvoke(args)
                print(f"[SUCCESS] Result:\n{result}")
            except Exception as e:
                print(f"[-] Error executing {name}: {e}")
            sys.stdout.flush()
        else:
            print(f"\n[-] Tool '{name}' not found or not registered.")
            sys.stdout.flush()

    print("\n=== MCP SERVER TESTS COMPLETED ===")
    sys.stdout.flush()
    
    # Force process exit to close any remaining stdio subprocesses/threads
    os._exit(0)

if __name__ == "__main__":
    asyncio.run(main())
