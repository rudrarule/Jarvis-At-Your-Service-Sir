"""
weather_tool.py — Ultra-fast real-time weather using wttr.in
Returns concise string ideal for text-to-speech.
"""
import httpx
import re

def get_weather(location: str) -> str:
    """
    Get the current weather for a specific location.
    Returns a clean, easily spoken string.
    """
    # Sanitize: strip trailing punctuation that might have slipped through regex
    location = re.sub(r"[?!.]+$", "", location.strip())
    
    # If user says "right now", "current", "today", or empty string, use local weather (wttr.in/)
    vague_terms = ["right now", "current", "today", "now", "here", "outside"]
    loc_clean = location.lower().strip()
    
    if any(term == loc_clean for term in vague_terms) or not loc_clean:
        location = ""
        print("[WEATHER] Fetching local weather (IP-based)")
    else:
        print(f"[WEATHER] Fetching weather for: '{location}'")

    try:
        # format=3 returns: "Location: Condition, +22°C"
        url = f"https://wttr.in/{location}?format=3"
        response = httpx.get(url, timeout=5.0)
        
        if response.status_code == 200:
            result = response.text.strip()
            # Ensure it's not returning an error page
            if "Unknown location" in result or result == "":
                return f"I apologize, sir, but I could not find weather data for {location}."
            
            # Clean up result for voice/console: strip emojis to avoid Unicode errors on Windows
            result_safe = re.sub(r'[^\x00-\x7F]+', '', result).strip()
            
            return f"Sir, the current weather for {result_safe}."
        else:
            return "I'm having trouble accessing the weather service right now, sir."
            
    except Exception as e:
        # Safe printing for Windows console
        try:
            print(f"[ERROR] Weather fetch failed: {e}")
        except UnicodeEncodeError:
            print("[ERROR] Weather fetch failed (Unicode error)")
        return "I apologize, sir, but I cannot reach the weather service at this moment."
