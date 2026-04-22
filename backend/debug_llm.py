import asyncio
import httpx
import time

async def main():
    print('[DEBUG] Testing llama3.1 local inference speed...')
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            print('[DEBUG] Sending request to Ollama...')
            resp = await client.post('http://localhost:11434/api/chat', json={
                'model': 'llama3.1:latest',
                'messages': [{'role': 'user', 'content': 'open spotify and open browser'}],
                'tools': [
                    {'type': 'function', 'function': {'name': 'open_app', 'description': 'open application', 'parameters': {'type': 'object', 'properties': {'app_name': {'type': 'string'}}, 'required': ['app_name']}}},
                    {'type': 'function', 'function': {'name': 'browser_search', 'description': 'search browser', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'open_visible': {'type': 'boolean'}}, 'required': ['query', 'open_visible']}}}
                ],
                'stream': False
            })
            resp.raise_for_status()
            elapsed = time.time() - start_time
            print(f'\n[SUCCESS] Response received in {elapsed:.2f} seconds!')
            data = resp.json()
            if 'tool_calls' in data['message']:
                num_calls = len(data["message"]["tool_calls"])
                print(f'[TOOL CALLS EXTRACTED]: {num_calls}')
                for t in data['message']['tool_calls']:
                    name = t["function"]["name"]
                    args = t["function"]["arguments"]
                    print(f' -> {name}: {args}')
            else:
                print('[RESPONSE]:', data['message']['content'])
    except Exception as e:
        print(f'\n[ERROR] {e}')
        
asyncio.run(main())
