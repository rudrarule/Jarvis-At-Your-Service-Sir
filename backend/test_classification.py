import asyncio
import httpx

async def test_classification():
    prompt = """You are a strict intent classifier. Given the user's message, reply with EXACTLY ONE of these labels:

MUSIC — user wants to play, listen to, or hear a song/artist/genre
SEARCH — user wants to search the internet, look up info, news, products, knowledge
OPEN_URL — user wants to open a specific website (google.com, youtube, github, etc.)
APP — user wants to open, close, or launch a desktop application (chrome, spotify, vscode, etc.)
FOLDER — user wants to open a folder (desktop, downloads, documents, etc.)
SYSTEM — user wants to lock, shutdown, restart the PC, or list running apps
FILE — user wants to read, write, create, or find a file on their computer
WEATHER — user wants to know the weather
WHATSAPP — user wants to check WhatsApp messages, missed calls, or send a message
CHAT — user just wants to have a conversation, ask a question, or chat

Rules:
- Output ONLY the single label word. No explanation, no punctuation.
- If unsure, default to CHAT.
- "who messaged me", "any new messages", "check whatsapp" -> WHATSAPP
"""
    msg = "who messaged me?"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "gemma3:latest",
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": msg},
                ],
                "stream": False,
            },
        )
        print(f"Classification for '{msg}': {response.json()['message']['content'].strip()}")

if __name__ == "__main__":
    asyncio.run(test_classification())
