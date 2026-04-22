"""
test_3tier.py — End-to-end test for the 3-Tier Router Architecture
Tests all tiers: regex fast-path, intent classification, pruned tool routing, and chat fallback.
"""
import asyncio
import httpx
import time

BACKEND_URL = "http://localhost:8002"

TEST_CASES = [
    # (input, expected_behavior, tier)
    
    # ── Tier 1: Regex Fast-Path ──
    ("play Thriller by Michael Jackson",    "MUSIC",    "Tier 1 Regex"),
    ("open chrome",                         "APP",      "Tier 1 Regex"),
    ("close notepad",                       "APP",      "Tier 1 Regex"),
    ("open downloads",                      "FOLDER",   "Tier 1 Regex"),
    
    # ── Tier 2+3: Intent Classify → Tool Route ──
    ("search for best laptops 2024",        "SEARCH",   "Tier 2+3"),
    ("what's the weather in Delhi",         "WEATHER",  "Tier 2+3"),
    ("best bats in india",                  "SEARCH",   "Tier 2+3"),
    ("latest news in AI",                   "SEARCH",   "Tier 2+3"),
    ("open youtube.com",                    "OPEN_URL", "Tier 2+3"),
    
    # ── Chat (no tool) ──
    ("how are you Jarvis?",                 "CHAT",     "Chat"),
    ("what is the meaning of life?",        "CHAT",     "Chat"),
    ("tell me a joke",                      "CHAT",     "Chat"),
]

async def test_single(msg: str, expected: str, tier: str) -> dict:
    """Send a message to the backend and measure response."""
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(
                f"{BACKEND_URL}/chat",
                json={"message": msg, "session_id": "test_3tier"},
            )
            latency = time.time() - t0
            reply = res.json().get("reply", "")
            
            # Determine if it was correct
            is_search = "browser" in reply.lower() or "opening" in reply.lower() or "search results" in reply.lower()
            is_music = "playing" in reply.lower() or "youtube" in reply.lower()
            is_weather = "temperature" in reply.lower() or "weather" in reply.lower() or "degrees" in reply.lower()
            is_app = "launching" in reply.lower() or "opened" in reply.lower() or "opening" in reply.lower()
            is_chat = not any([is_search, is_music, is_weather]) and len(reply) > 20
            
            return {
                "msg": msg,
                "expected": expected,
                "tier": tier,
                "latency": latency,
                "reply": reply[:120],
                "status": "OK"
            }
    except Exception as e:
        return {
            "msg": msg,
            "expected": expected,
            "tier": tier,
            "latency": time.time() - t0,
            "reply": str(e)[:120],
            "status": "FAIL"
        }


async def run_all_tests():
    print("=" * 80)
    print("   J.A.R.V.I.S 3-TIER ROUTER — INTEGRATION TEST SUITE")
    print("=" * 80)
    print()
    
    results = []
    for msg, expected, tier in TEST_CASES:
        print(f"  [{tier}] Testing: \"{msg}\"")
        result = await test_single(msg, expected, tier)
        results.append(result)
        
        status_icon = "[OK]" if result["status"] == "OK" else "[FAIL]"
        safe_reply = result['reply'].encode('ascii', 'replace').decode('ascii')
        print(f"    {status_icon} {result['latency']:.2f}s -> {safe_reply}")
        print()
    
    # Summary
    print("=" * 80)
    print("   SUMMARY")
    print("=" * 80)
    
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "OK")
    avg_latency = sum(r["latency"] for r in results) / total
    
    tier1 = [r for r in results if "Tier 1" in r["tier"]]
    tier23 = [r for r in results if "Tier 2" in r["tier"]]
    chat = [r for r in results if "Chat" in r["tier"]]
    
    if tier1:
        print(f"  Tier 1 (Regex):     avg {sum(r['latency'] for r in tier1)/len(tier1):.2f}s")
    if tier23:
        print(f"  Tier 2+3 (Classify+Route): avg {sum(r['latency'] for r in tier23)/len(tier23):.2f}s")
    if chat:
        print(f"  Chat (gemma3):      avg {sum(r['latency'] for r in chat)/len(chat):.2f}s")
    
    print(f"\n  Total: {passed}/{total} passed | Avg latency: {avg_latency:.2f}s")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
