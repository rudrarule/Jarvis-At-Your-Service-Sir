import asyncio
import sys
import os

# Add the backend directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tools.whatsapp_tool import whatsapp_briefing, whatsapp_unread, whatsapp_missed_calls

async def test_whatsapp_tools():
    print("--- Testing WhatsApp Briefing ---")
    briefing = await whatsapp_briefing()
    print(briefing)
    print("\n--- Testing WhatsApp Unread ---")
    unread = await whatsapp_unread()
    print(unread)
    print("\n--- Testing WhatsApp Missed Calls ---")
    missed = await whatsapp_missed_calls()
    print(missed)

if __name__ == "__main__":
    asyncio.run(test_whatsapp_tools())
