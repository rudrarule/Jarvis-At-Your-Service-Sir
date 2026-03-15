"""
services.py — LLM Logic & Tool Dispatcher
Handles communication with language models and routes tool calls.
"""


async def handle_chat(message: str) -> str:
    """
    Process a user message and return a response.
    Currently uses a placeholder — swap in OpenAI / Gemini when API keys are set.
    """
    # TODO: Replace with real LLM call (OpenAI, Gemini, etc.)
    # from openai import AsyncOpenAI
    # client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # ...

    return f"I received your message: \"{message}\"At your service sir"


async def dispatch_tool(tool_name: str, params: dict) -> dict:
    """Route a tool call to the appropriate handler."""
    from tools import system_tools, web_tools

    registry = {
        **system_tools.TOOLS,
        **web_tools.TOOLS,
    }

    handler = registry.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}

    return await handler(**params)
