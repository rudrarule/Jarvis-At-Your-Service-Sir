"""Convenience wrapper: run `python test_tts.py` from backend/."""
from jarvis.test_tts import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
