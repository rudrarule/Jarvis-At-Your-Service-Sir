import webbrowser
import urllib.request
import urllib.parse
import re

def play_music(query: str) -> tuple[str, str]:
    """
    Searches YouTube for the query and opens the first result in the default browser.
    Returns (video_title, video_url).
    """
    try:
        query_string = urllib.parse.urlencode({"search_query": query})
        url = "https://www.youtube.com/results?" + query_string
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html_content = urllib.request.urlopen(req)
        html_text = html_content.read().decode('utf-8')
        
        # Extract video IDs
        search_results = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html_text)
        
        if search_results:
            video_id = search_results[0]
            link = f"https://www.youtube.com/watch?v={video_id}"
            
            # Simple title reconstruction since extracting HTML title involves parsing complex JS
            title = query.title() 
            
            autoplay_link = f"{link}&autoplay=1"
            print(f"🎵 Opening YouTube: {title} ({autoplay_link})")
            
            webbrowser.open(autoplay_link)
            return title, link
            
        return "Unknown", ""
    except Exception as e:
        print(f"Error in play_music tool: {e}")
        return "Unknown", ""
