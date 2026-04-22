import asyncio
import sys

# Ensure backend path is recognized
sys.path.append(r'c:\Users\Rudra\holo-core-nexus\backend')

from services.llm_service import generate_response
from services.session_service import get_session_history

async def test_memory():
    session_id = "test_memory_session_1"
    
    print("User: My name is Rudraksh")
    print("Jarvis is thinking...")
    r1 = await generate_response("My name is Rudraksh", session_id)
    print(f"Jarvis: {r1}\n")
    
    print("User: What is my name?")
    print("Jarvis is thinking...")
    r2 = await generate_response("What is my name?", session_id)
    print(f"Jarvis: {r2}\n")
    
    print("--- Session History Trace ---")
    for msg in get_session_history(session_id):
        print(f"[{msg['role'].upper()}]: {msg['content'][:100]}...")

if __name__ == '__main__':
    # Make sure Ollama is running if you want the fast local response!
    asyncio.run(test_memory())
