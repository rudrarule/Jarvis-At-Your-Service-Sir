import asyncio
import sys
import os
from unittest.mock import patch

# Add parent dir to path so we can import services
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.services.llm_service import generate_response
from backend.services import llm_service
from backend.services.session_service import get_session_history

# A mock for the text pipeline to simulate the standard response
async def mock_route_hybrid_llm(*args, **kwargs):
    return "This is the standard text response."

# A mock for Bedrock
async def mock_call_maverick_vision(image_b64, user_message):
    return "I can see your screen, sir. It appears you have VS Code open."

async def run_qa_tests():
    print("==================================================")
    print("  J.A.R.V.I.S. Retina Module - QA Testing Suite  ")
    print("==================================================")
    
    session_id = "qa_test_session"
    
    # Patch the text router to avoid hitting Ollama/Bedrock for the text fallback
    with patch("backend.services.llm_service._route_hybrid_llm", new=mock_route_hybrid_llm):
        
        # Patch the vision model to avoid AWS calls
        with patch("backend.services.llm_service._call_maverick_vision", new=mock_call_maverick_vision):
            
            # --- Test 1: Positive Path ---
            print("\n[Test Case 1] Positive Path: Vision Triggered")
            # Reset debounce
            llm_service._LAST_VISION_TRIGGER = 0.0
            
            res1 = await generate_response("Jarvis, what's on my screen?", session_id)
            print(f"User: Jarvis, what's on my screen?")
            print(f"Jarvis: {res1}")
            if "I can see your screen" in res1:
                print("[PASS] Bedrock vision mock triggered.")
            else:
                print("[FAIL] Vision not triggered.")
                
            
            # --- Test 2: Rate Limiter (Debounce) ---
            print("\n[Test Case 2] Rate Limiter: 15s Debounce Guard")
            res2 = await generate_response("Jarvis, look at this.", session_id)
            print(f"User: Jarvis, look at this.")
            print(f"Jarvis: {res2}")
            if "Patience is a virtue" in res2:
                print("[PASS] Debounce guard activated successfully.")
            else:
                print("[FAIL] Debounce guard failed.")
                
            
            # --- Test 3: Intent Scope Filter (URLs) ---
            print("\n[Test Case 3] Intent Scope Filter: Ignore URLs")
            # Reset debounce to avoid false positive on debounce
            llm_service._LAST_VISION_TRIGGER = 0.0
            
            res3 = await generate_response("Jarvis, can you see https://github.com?", session_id)
            print(f"User: Jarvis, can you see https://github.com?")
            print(f"Jarvis: {res3}")
            if "standard text response" in res3 and "I can see your screen" not in res3:
                print("[PASS] URL rejected, fell back to text pipeline.")
            else:
                print("[FAIL] URL improperly triggered vision.")

            
            # --- Test 4: Intent Scope Filter (Code Blocks) ---
            print("\n[Test Case 4] Intent Scope Filter: Ignore Code Blocks")
            llm_service._LAST_VISION_TRIGGER = 0.0
            
            res4 = await generate_response("Look at this code ```print('hello')```", session_id)
            print(f"User: Look at this code ```print('hello')```")
            print(f"Jarvis: {res4}")
            if "standard text response" in res4:
                print("[PASS] Code block rejected, fell back to text pipeline.")
            else:
                print("[FAIL] Code block improperly triggered vision.")


        # --- Test 5: Capture Failure / PII Gate ---
        print("\n[Test Case 5] PII Safety Gate Rejection")
        llm_service._LAST_VISION_TRIGGER = 0.0
        
        # We patch the capture function to simulate the PII gate firing
        def mock_capture_pii():
            return None, "Sir, I've detected what appears to be sensitive credentials on screen. I'd rather not see that. Please switch windows."
            
        with patch("services.vision_service._capture_retina_view", new=mock_capture_pii):
            res5 = await generate_response("Jarvis, check my screen", session_id)
            print(f"User: Jarvis, check my screen")
            print(f"Jarvis: {res5}")
            if "sensitive credentials" in res5:
                print("[PASS] PII gate successfully aborted pipeline and returned warning.")
            else:
                print("[FAIL] PII gate was bypassed.")


        # --- Test 6: API Failure (Graceful Degradation) ---
        print("\n[Test Case 6] API Failure (Graceful Degradation)")
        llm_service._LAST_VISION_TRIGGER = 0.0
        
        async def mock_call_maverick_fail(image_b64, user_message):
            # Returns None to simulate ClientError / UnidentifiedImageError
            return None
            
        with patch("backend.services.llm_service._call_maverick_vision", new=mock_call_maverick_fail):
            # We also need a real capture or a mock capture that succeeds
            def mock_capture_success():
                return "base64_fake_data", None
                
            with patch("services.vision_service._capture_retina_view", new=mock_capture_success):
                res6 = await generate_response("Jarvis, what's on my screen?", session_id)
                print(f"User: Jarvis, what's on my screen?")
                print(f"Jarvis: {res6}")
                if "visual cortex appears to be offline" in res6 and "standard text response" in res6:
                    print("[PASS] Graceful degradation activated. Prepended warning to text response.")
                else:
                    print("[FAIL] Did not gracefully degrade to text pipeline.")

    print("\n==================================================")
    print("  QA Testing Complete  ")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_qa_tests())
