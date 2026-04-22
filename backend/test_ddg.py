import asyncio
import httpx
import re

async def test():
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.post(
            'https://html.duckduckgo.com/html/',
            data={'q': 'latest movies 2024'},
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        html = resp.text
        
        # Try to find result links
        blocks = re.findall(
            r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        print(f"Found {len(blocks)} result links")
        for href, title in blocks[:3]:
            clean = re.sub(r'<[^>]+>', '', title).strip()
            print(f"  -> {clean}")
            print(f"     {href[:100]}")
        
        if not blocks:
            # Debug: dump a portion of the HTML to see the structure
            print("\n--- HTML SAMPLE (first 3000 chars) ---")
            print(html[:3000])

asyncio.run(test())
