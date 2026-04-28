import httpx
import asyncio
import sys

OLLAMA_URL = "http://localhost:11434"
MODELS = ["llama3.2:1b", "qwen3.5:4b"]

async def pull_model(model_name: str):
    print(f"Pulling {model_name}... This may take a few minutes depending on your internet connection.")
    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            # We use stream=True to potentially track progress if we wanted, 
            # but for simplicity we'll just wait for the download to finish.
            response = await client.post(
                f"{OLLAMA_URL}/api/pull",
                json={"name": model_name, "stream": False}
            )
            if response.status_code == 200:
                print(f"[SUCCESS] Successfully pulled {model_name}.")
            else:
                print(f"[FAILED] Failed to pull {model_name}: {response.text}")
    except httpx.ConnectError:
        print("[ERROR] Could not connect to Ollama. Please ensure Ollama is running on localhost:11434")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Error pulling {model_name}: {e}")

async def main():
    print("Initializing JARVIS 4GB VRAM Efficiency Stack...")
    for model in MODELS:
        await pull_model(model)
    print("Setup complete.")

if __name__ == "__main__":
    asyncio.run(main())
