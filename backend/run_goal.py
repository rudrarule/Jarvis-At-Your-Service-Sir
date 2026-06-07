import asyncio
import sys
import os

# Reconfigure stdout/stderr to handle UTF-8 symbols (like ₹)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from services.llm_service import generate_response

async def main():
    goal = "find the flights prices from delhi to goa for me on 29th june"
    print(f"Starting Goal: {goal}")
    response = await generate_response(goal, "interactive-test-session")
    print("\n--- FINAL JARVIS RESPONSE ---")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())

