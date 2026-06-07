"""Process-wide Python startup tweaks for the backend.

On Windows, Playwright launches a driver subprocess. That requires the
Proactor event loop; Selector loops raise NotImplementedError from
asyncio.create_subprocess_exec().
"""

import asyncio
import sys


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
