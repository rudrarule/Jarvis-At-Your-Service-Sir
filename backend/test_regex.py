import httpx
import time

msg = "jarvis, play thriller by michael jackson"

print('\n⚡ EXECUTING SINGULAR MUSIC BENCHMARK...\n')
print(f'➜ Sending: "{msg}"')
t0 = time.time()
try:
    r = httpx.post(
        'http://localhost:8000/chat', 
        json={'message': msg, 'session_id': 'singular_qa'}, 
        timeout=10
    )
    latency = time.time() - t0
    reply = r.json().get('reply', '')
    
    print(f'   [MEASURED LATENCY]: {latency:.3f} seconds')
    print(f'   [ROUTER FALLBACK]:  "{reply}"\n')
except Exception as e:
    print(f'   [ERROR] Validation Failed: {e}\n')

print('✅ BENCHMARK COMPLETE.\n')
