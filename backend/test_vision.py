import sys
import os

# Add parent dir to path so we can import services
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.services.vision_service import _capture_retina_view, is_safe_to_capture
from backend.services.llm_service import _classify_vision_intent

def test_intent():
    print("--- Testing Intent Detection ---")
    assert _classify_vision_intent("Jarvis, what's on my screen?", []) == True
    assert _classify_vision_intent("Look at this code ```python print('hi') ```", []) == False
    assert _classify_vision_intent("Can you see https://google.com?", []) == False
    assert _classify_vision_intent("Check my screen", []) == True
    assert _classify_vision_intent("What's the weather?", []) == False
    print("Intent tests passed!")

def test_capture():
    print("--- Testing Capture Module ---")
    # Test PII gate
    assert is_safe_to_capture("My Bank Account - Chrome") == False
    assert is_safe_to_capture("1Password - Vault") == False
    assert is_safe_to_capture("Visual Studio Code") == True

    # Test capture
    print("Capturing...")
    img_b64, err = _capture_retina_view()
    if err:
        print(f"Capture returned error: {err}")
    else:
        print(f"Capture successful. Base64 length: {len(img_b64)}")
        # Check if it starts with valid base64 chars
        assert len(img_b64) > 100
        print("Capture test passed!")

if __name__ == "__main__":
    test_intent()
    test_capture()
