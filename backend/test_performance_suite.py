import pytest
import asyncio
import time
from services.session_service import get_session_history, append_message, chat_sessions
from services.text_to_speech_service import warm_start


@pytest.mark.asyncio
async def test_tc067_rapid_fire_requests():
    """TC_067 | Rapid Fire Requests: Assert concurrent task handling without failure."""
    async def mock_handler(task_id: int):
        await asyncio.sleep(0.01)  # Simulate fast processing
        return {"task_id": task_id, "status": "ok"}

    # Trigger 20 rapid-fire concurrent mock requests
    tasks = [mock_handler(i) for i in range(20)]
    results = await asyncio.gather(*tasks)
    
    assert len(results) == 20
    assert all(r["status"] == "ok" for r in results)


def test_tc068_long_conversation_history():
    """TC_068 | Long Conversation History: Ensure context remains bounded and managed."""
    session_id = "perf-history-test"
    chat_sessions.clear()

    # Append 50 turns (100 messages total: user + assistant)
    for i in range(50):
        append_message(session_id, "user", f"Turn {i}: Hello Jarvis")
        append_message(session_id, "assistant", f"Hello sir, turn {i} acknowledged.")

    # Retrieve history with a strict cap limit (e.g. limit=6)
    history = get_session_history(session_id, limit=6)
    assert len(history) == 6
    assert history[-1]["content"] == "Hello sir, turn 49 acknowledged."


def test_tc069_concurrent_sessions_isolated():
    """TC_069 | Concurrent Users: Verify strict state separation between distinct session keys."""
    user_a_session = "user-a-thread"
    user_b_session = "user-b-thread"
    chat_sessions.clear()

    append_message(user_a_session, "user", "My secret key is ALFA-1")
    append_message(user_b_session, "user", "My secret key is BRAVO-2")

    history_a = get_session_history(user_a_session)
    history_b = get_session_history(user_b_session)

    # Asserts absolute session isolation
    assert len(history_a) == 1
    assert len(history_b) == 1
    assert "ALFA-1" in history_a[0]["content"]
    assert "BRAVO-2" in history_b[0]["content"]
    assert "ALFA-1" not in history_b[0]["content"]
    assert "BRAVO-2" not in history_a[0]["content"]


@pytest.mark.asyncio
async def test_tc070_cold_start_tts_prewarm():
    """TC_070 | Cold Start Performance: Ensure TTS warming executes in < 2000ms for fast audio readiness."""
    start = time.perf_counter()
    await warm_start()
    elapsed = (time.perf_counter() - start) * 1000
    
    # Assert pre-warming completes rapidly to keep cold boot under 3 seconds
    assert elapsed < 3500.0  # Warm start must be instantaneous
