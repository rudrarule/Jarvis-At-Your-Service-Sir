import asyncio
import os
from unittest.mock import patch
from tools.registry import execute_tool

async def run_tests():
    print("--- Senior Test Engineer: Tool Suite Execution ---")
    results = {}

    # 1. Weather Tool
    try:
        reply = await execute_tool("get_weather", {"location": "New York"})
        results["get_weather"] = "PASS" if "weather in New York" in reply or "degrees" in reply.lower() else f"WARN: {reply[:50]}"
    except Exception as e:
        results["get_weather"] = f"FAIL: {e}"

    # 2. File System Tools
    test_file_path = "test_qa_file.txt"
    try:
        # Write
        reply_w = await execute_tool("write_file", {"path": test_file_path, "content": "QA Test Content"})
        if "successfully written" not in reply_w:
            results["write_file"] = "FAIL"
        else:
            # Read
            reply_r = await execute_tool("read_file", {"path": test_file_path})
            if "QA Test Content" in reply_r:
                results["write_file"] = "PASS"
                results["read_file"] = "PASS"
            else:
                results["read_file"] = "FAIL"
            
            # Append
            await execute_tool("append_file", {"path": test_file_path, "content": "\nAppended!"})
            reply_r2 = await execute_tool("read_file", {"path": test_file_path})
            if "Appended!" in reply_r2:
                results["append_file"] = "PASS"
            else:
                results["append_file"] = "FAIL"
    except Exception as e:
        results["file_system"] = f"FAIL: {e}"
    finally:
        if os.path.exists(test_file_path):
            os.remove(test_file_path)

    # 3. List Directory & Search
    try:
        reply_list = await execute_tool("list_directory", {"path": "."})
        results["list_directory"] = "PASS" if "main.py" in reply_list else "WARN"

        reply_search = await execute_tool("search_files", {"query": "main"})
        results["search_files"] = "PASS" if "main.py" in reply_search else "WARN"
    except Exception as e:
        results["list_directory_search"] = f"FAIL: {e}"

    # 4. Mocked External Actions (Browser/Music)
    try:
        with patch('webbrowser.open') as mock_open:
            reply_music = await execute_tool("play_music", {"query": "test song"})
            results["play_music"] = "PASS" if mock_open.called else "FAIL"
    except Exception as e:
        results["play_music"] = f"FAIL: {e}"

    # 5. Browser Search (Headless)
    try:
        reply_browser = await execute_tool("browser_search", {"query": "python", "open_visible": False})
        results["browser_search"] = "PASS" if reply_browser and len(reply_browser) > 50 else f"WARN: {reply_browser[:50]}"
    except Exception as e:
        results["browser_search"] = f"FAIL: {e}"

    print("\n--- Test Report ---")
    for k, v in results.items():
        print(f"[{v.split(':')[0]}] {k} -> {v}")

asyncio.run(run_tests())
