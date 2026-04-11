"""
registry.py — Central Tool Registry for Native Function Calling
Maps tool names → executable functions + JSON schemas for LLM tool calling.
"""
from tools.music_tool import play_music
from tools.browser_tool import browser_search
from tools.weather_tool import get_weather


# ── Tool Schemas (OpenAI/Ollama format) ───────────────────
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "Call this tool if the user asks you to play a song. Use the query parameter to specify the exact requested song or artist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The song name, artist, or search query to play on YouTube",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": "CRITICAL: You MUST execute this tool if the user asks to 'look up', 'search', 'find', or 'browse' for ANY information on the internet. Use it to open a physical browser for answers, articles, shopping, or facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The specific search query"
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a specific location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city or location (e.g., 'Faridabad', 'New York')",
                    }
                },
                "required": ["location"],
            },
        },
    },
]

# ── Function Lookup ───────────────────────────────────────
TOOL_FUNCTIONS = {
    "play_music": play_music,
    "browser_search": browser_search,
    "get_weather": get_weather,
}


def execute_tool(tool_name: str, arguments: dict) -> str:
    """
    Look up and execute a tool by name.
    Returns a Jarvis-style confirmation string.
    """
    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return f"I'm sorry, sir. I don't recognize the tool '{tool_name}'."

    try:
        result = func(**arguments)

        # play_music returns (title, url)
        if tool_name == "play_music":
            title, url = result
            if url:
                return f"Certainly, sir. Playing {title} on YouTube now."
            else:
                return "I apologize, sir. I couldn't find that song on YouTube."
                
        # Browser and Weather returns are already perfectly formatted TTS strings
        if tool_name in ["browser_search", "get_weather"]:
            return result

        # Generic fallback for future tools
        return f"Tool '{tool_name}' executed successfully: {result}"

    except Exception as e:
        print(f"❌ Tool execution error ({tool_name}): {e}")
        return f"I encountered an error executing {tool_name}, sir."
