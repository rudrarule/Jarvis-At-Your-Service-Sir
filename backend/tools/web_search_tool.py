"""
web_search_tool.py — Rapid internet search using DuckDuckGo
Returns top 3 results concisely formatted for text-to-speech.
"""
from duckduckgo_search import DDGS


def web_search(query: str) -> str:
    """
    Search the internet for real-time information.
    Fetches the top 3 results and returns them as a concise string for Jarvis to read.
    """
    print(f"🌐 Running web search for: '{query}'")
    try:
        results = DDGS().text(query, max_results=3)
        
        if not results:
            return "I'm sorry, sir. I couldn't find any relevant results on the web for that query."

        # Format cleanly so Jarvis can speak it without reading raw JSON
        response_lines = ["Here is what I found on the web, sir:"]
        
        for idx, res in enumerate(results, start=1):
            title = res.get("title", "No Title")
            body = res.get("body", "")
            
            # Keep snippets short for TTS
            if len(body) > 150:
                body = body[:147] + "..."
                
            response_lines.append(f"{idx}. {title} — {body}")
            
        return "\n".join(response_lines)

    except Exception as e:
        print(f"[ERROR] Web search failed: {e}")
        return "I apologize, sir. I am currently unable to reach the external internet. Please try again later."
