import httpx
import time

test_cases = [
    {'name': 'Browser Automation (Playwright)', 'msg': 'look up the latest PS5 games', 'expected': 'browser_search'},
    {'name': 'Music Player (Native OS)', 'msg': 'play blinding lights by ed sheeran', 'expected': 'play_music'},
    {'name': 'Weather API (wttr.in)', 'msg': 'weather in tokyo', 'expected': 'get_weather'},
    {'name': 'Gemma 3 Conversation (No Tools)', 'msg': 'Are you an AI or a human?', 'expected': 'conversational'}
]

print('\n🧪 INITIALIZING SENIOR QA ROUTER SUITE...\n')

for i, test in enumerate(test_cases):
    print(f'➜ Test {i+1}: {test["name"]}')
    print(f'   Prompt: "{test["msg"]}"')
    t0 = time.time()
    try:
        r = httpx.post(
            'http://localhost:8000/chat', 
            json={'message': test['msg'], 'session_id': f'qa_suite_{i}'}, 
            timeout=120
        )
        latency = time.time() - t0
        reply = r.json().get('reply', '')
        
        print(f'   Latency: {latency:.2f} seconds')
        print(f'   Output:  {reply}')
        
        # Heuristic validation
        if test['expected'] == 'browser_search' and 'Searching the web' in reply:
            print('   [PASS] 🟢 Playwright Thread Successfully Triggered\n')
        elif test['expected'] == 'play_music' and 'Playing' in reply and 'YouTube' in reply:
            print('   [PASS] 🟢 Native YouTube Command Successfully Executed\n')
        elif test['expected'] == 'get_weather' and 'Weather in ' in reply:
            print('   [PASS] 🟢 Weather API Successfully Hooked\n')
        elif test['expected'] == 'conversational' and len(reply) > 5 and 'Playing' not in reply and 'Searching' not in reply and 'Weather in ' not in reply:
            print('   [PASS] 🟢 Gemma 3 Convo Engine Bypassed Tools Flawlessly\n')
        else:
            print('   [FAIL] 🔴 Unexpected response format!\n')
            
    except Exception as e:
        print(f'   [ERROR] Connection Failed: {e}\n')

print('✅ QA SUITE COMPLETE.\n')
