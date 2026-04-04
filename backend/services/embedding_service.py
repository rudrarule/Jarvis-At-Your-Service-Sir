"""
embedding_service.py — Ollama Embedding Generator
Generates text embeddings using Ollama's nomic-embed-text model (100% local).
"""
import httpx

OLLAMA_URL = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"


async def generate_embedding(text: str) -> list[float]:
    """
    Convert text into a vector embedding using Ollama's nomic-embed-text.
    Returns a list of floats (768-dimensional vector).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={
                "model": EMBEDDING_MODEL,
                "prompt": text,
            },
        )
        response.raise_for_status()
        return response.json()["embedding"]
