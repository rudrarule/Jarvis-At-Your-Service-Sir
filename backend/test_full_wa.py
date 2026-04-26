import asyncio
import sys
import os

# Add the backend directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.llm_service import generate_response

async def test_full_wa():
    print("--- Sending message: 'any missed calls?' ---")
    reply = await generate_response("any missed calls?")
    print("\nJarvis Response:")
    print(reply)

if __name__ == "__main__":
    asyncio.run(test_full_wa())
