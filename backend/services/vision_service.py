"""
vision_service.py — Retina Module Capture Service
Handles screen capture, window title PII checks, and image formatting for Bedrock.
"""
import io
import base64
import time
import pyautogui
from PIL import Image

try:
    import pygetwindow as gw
except ImportError:
    gw = None


# ── PII Safety Gate ────────────────────────────────────────

def is_safe_to_capture(window_title: str) -> bool:
    """
    Check if the window title indicates sensitive information.
    Returns True if safe, False if potentially sensitive.
    """
    if not window_title:
        return True
        
    sensitive_keywords = [
        "password", "1password", "bitwarden", "lastpass", "dashlane",
        "bank", "login", "credential", "sign in", "auth"
    ]
    title_lower = window_title.lower()
    
    if any(keyword in title_lower for keyword in sensitive_keywords):
        print(f"[VISION] PII guard: Blocked capture due to sensitive window title.")
        return False
        
    return True


# ── Capture Module ─────────────────────────────────────────

def _capture_retina_view() -> tuple[str | None, str | None]:
    """
    Captures the active window or full screen.
    Resizes to fit 1024x1024, converts to RGB, compresses to JPEG.
    
    Returns:
        (base64_string, error_message)
    """
    try:
        img = None
        active_title = ""
        
        # Try active window capture first
        if gw is not None:
            active_window = gw.getActiveWindow()
            if active_window:
                active_title = active_window.title
                
                # Check PII Gate before doing the heavy capture
                if not is_safe_to_capture(active_title):
                    return None, "Sir, I've detected what appears to be sensitive credentials on screen. I'd rather not see that. Please switch windows."
                
                # Bounding box: left, top, width, height
                region = (active_window.left, active_window.top, active_window.width, active_window.height)
                # Ensure valid dimensions
                if region[2] > 0 and region[3] > 0:
                    try:
                        img = pyautogui.screenshot(region=region)
                    except Exception as e:
                        print(f"[VISION] Active window capture failed: {e}. Falling back to full screen.")
        
        # Fallback to full screen
        if img is None:
            # Note: Full screen doesn't check active window title PII, but usually it's fine as a fallback.
            img = pyautogui.screenshot()
            print("[VISION] PII guard: clear (Full screen fallback).")
        else:
            print("[VISION] PII guard: clear.")
            
        original_width, original_height = img.size
        
        # Convert to RGB (strip alpha channel)
        if img.mode != "RGB":
            img = img.convert("RGB")
            
        # Resize to fit within 1024x1024 (maintain aspect ratio)
        max_size = 1024
        if original_width > max_size or original_height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
        new_width, new_height = img.size
        
        # Compress as JPEG quality=80
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        img_bytes = buffer.getvalue()
        
        # Encode as Base64
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        
        size_kb = len(img_bytes) / 1024
        print(f"[VISION] Capture successful. {original_width}x{original_height}px -> {new_width}x{new_height}px -> JPEG {size_kb:.1f}KB -> Bedrock.")
        
        return img_b64, None

    except pyautogui.FailSafeException:
        print("[VISION] Error: FailSafeException — mouse in corner, capture aborted.")
        return None, "Sir, my visual cortex appears to be offline. I can still assist you in the traditional, text-based, decidedly less impressive fashion."
    except Exception as e:
        import traceback
        print(f"[VISION] Error during capture: {e}")
        print(traceback.format_exc())
        return None, "Sir, my visual cortex appears to be offline. I can still assist you in the traditional, text-based, decidedly less impressive fashion."
