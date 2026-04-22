import asyncio
from services.llm_service import generate_response

async def main():
    print("Sending query to J.A.R.V.I.S...")
    try:
        reply = await generate_response("hey jarvis open spotify and search for loose my mind song", "test_session_xyz")
        print(f"\nFinal Reply: {reply}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
