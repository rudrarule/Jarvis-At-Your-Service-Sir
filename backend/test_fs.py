"""Test the full routing pipeline for file system tool calls."""
import asyncio
import json
import httpx
import os
import sys

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8')

# Add parent to path
from tools.registry import TOOL_SCHEMAS, execute_tool

OLLAMA_URL = "http://localhost:11434"
OLLAMA_ROUTER_MODEL = "qwen2.5:7b"

SYSTEM_PROMPT = """You are J.A.R.V.I.S. Use tools when the user requests file operations.
If the user wants to create/write a file, use write_file.
If the user wants to read a file, use read_file.
If the user wants to list files, use list_directory."""


async def test_tool_routing(user_message: str):
    """Simulate what the LLM service does when routing tool calls."""
    print(f"\n{'='*60}")
    print(f"USER: {user_message}")
    print(f"{'='*60}")
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_ROUTER_MODEL,
                    "messages": messages,
                    "tools": TOOL_SCHEMAS,
                    "stream": False,
                },
            )
            response.raise_for_status()
            msg = response.json()["message"]
            
            print(f"\nRouter response role: {msg.get('role')}")
            print(f"Router response content: {msg.get('content', '(none)')}")
            print(f"Tool calls: {json.dumps(msg.get('tool_calls', []), indent=2)}")
            
            if msg.get("tool_calls"):
                tool_call = msg["tool_calls"][0]
                tool_name = tool_call["function"]["name"]
                arguments = tool_call["function"]["arguments"]
                print(f"\n🔧 Executing: {tool_name}({arguments})")
                result = execute_tool(tool_name, arguments)
                print(f"📋 Result: {result}")
            else:
                print("\n⚠️ NO TOOL CALL DETECTED — This is the bug!")
                
        except Exception as e:
            print(f"\n❌ Error: {e}")


async def main():
    # Test various "create file" prompts
    test_messages = [
        "create a file called notes.txt with the content Hello World",
        "write a file named todo.txt containing Buy groceries",
        "make a new file test.md with some sample text",
        "create notes.txt",
        "save this to a file: my shopping list",
    ]
    
    for msg in test_messages:
        await test_tool_routing(msg)
        print()


asyncio.run(main())
