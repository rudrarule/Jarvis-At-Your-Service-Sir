"""
weather_tool.py — Ultra-fast real-time weather using wttr.in
Returns concise string ideal for text-to-speech.
"""
import httpx

def get_weather(location: str) -> str:
    """
    Get the current weather for a specific location.
    Returns a clean, easily spoken string.
    """
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
            
            return f"Sir, the current weather for {result}."
        else:
            return "I'm having trouble accessing the weather service right now, sir."
            
    except Exception as e:
        print(f"[ERROR] Weather fetch failed: {e}")
        return "I apologize, sir, but I cannot reach the weather service at this moment."
