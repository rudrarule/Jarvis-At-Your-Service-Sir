"""
system_tools.py — System-level tool handlers.
Open apps, browser, volume control, etc.
"""


async def open_application(name: str) -> dict:
    """Open a desktop application by name."""
    # TODO: implement
    return {"status": "not_implemented", "tool": "open_application"}


async def set_volume(level: int) -> dict:
    """Set system volume (0–100)."""
    # TODO: implement
    return {"status": "not_implemented", "tool": "set_volume"}


# Registry mapping tool names → handlers
TOOLS: dict = {
    "open_application": open_application,
    "set_volume": set_volume,
}
