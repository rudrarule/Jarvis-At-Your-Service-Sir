import asyncio
from services.llm_service import generate_response

async def run_tests():
    questions = [
        "jarvis what's the news about Iran?",
        "Play perfect by ed sheeran",
        "how do airplanes fly?",
        "can you play some focus music to help me study?",
        "open spotify and open browser and search for latest news about AI"
    ]
    
    with open("test_op.txt", "w", encoding="utf-8") as f:
        for q in questions:
            f.write(f"\n======================================\n")
            f.write(f"USER: {q}\n")
            f.write(f"--------------------------------------\n")
            reply = await generate_response(q)
            f.write("RAW LLM OUTPUT:\n" + reply + "\n")

if __name__ == "__main__":
    asyncio.run(run_tests())
