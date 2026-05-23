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
    goal = "Get the real-time weather forecast for Tokyo, Kyoto, and Osaka using the weather tool. Then, open google.com, search for 'top 3 cultural attractions in Kyoto 2026', open the first article to extract the names and descriptions of those attractions. Synthesize a 3-day travel itinerary combining the weather forecast and the attraction details, and save the final itinerary to 'kyoto_itinerary.txt'."
    print(f"Starting Goal: {goal}")
    response = await generate_response(goal, "interactive-test-session")
    print("\n--- FINAL JARVIS RESPONSE ---")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())

