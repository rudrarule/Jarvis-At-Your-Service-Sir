import asyncio
import time
from services.llm_service import generate_response

async def main():
    print("==================================================")
    print("  JARVIS 4GB VRAM Efficiency Stack Latency Test")
    print("  Models: llama3.2:1b (Tier 1/2) | qwen3.5:4b (Tier 3)")
    print("==================================================\n")

    test_prompts = [
        ("open chrome", "Tier 1: Regex Fast-Path"),
        ("what is the capital of France?", "Tier 2: Chat Fallback"),
        ("who messaged me?", "Tier 3: Tool Routing (WhatsApp)"),
    ]

    for prompt, expected_tier in test_prompts:
        print(f"Testing Prompt : '{prompt}'")
        print(f"Expected Path  : {expected_tier}")
        
        start_time = time.time()
        reply = await generate_response(prompt)
        end_time = time.time()
        
        latency_ms = (end_time - start_time) * 1000
        
        # Safe print for unicode characters that might choke cp1252
        safe_reply = reply.encode('ascii', 'ignore').decode('ascii')
        print(f"Latency        : {latency_ms:.0f} ms")
        print(f"Response       : {safe_reply[:100]}...\n")
        print("-" * 50 + "\n")

if __name__ == "__main__":
    # Ensure memory service tables are initialized if needed, 
    # generate_response handles it automatically via imports.
    asyncio.run(main())
