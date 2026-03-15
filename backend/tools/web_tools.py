"""
web_tools.py — Web-based tool handlers.
Search, weather, and other internet-facing utilities.
"""


async def web_search(query: str) -> dict:
    """Perform a web search and return results."""
    # TODO: implement
    return {"status": "not_implemented", "tool": "web_search"}


async def get_weather(location: str) -> dict:
    """Get current weather for a location."""
    # TODO: implement
    return {"status": "not_implemented", "tool": "get_weather"}


# Registry mapping tool names → handlers
TOOLS: dict = {
    "web_search": web_search,
    "get_weather": get_weather,
}
