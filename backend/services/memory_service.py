"""
memory_service.py — RAG Memory System using ChromaDB
Stores important user messages as vector embeddings and retrieves
relevant memories for context injection into LLM prompts.
"""
import re
import uuid
from datetime import datetime, timezone

from db.chroma_client import collection, client
from services.embedding_service import generate_embedding

# ── Importance Filter ─────────────────────────────────────
_IMPORTANT_PATTERNS = [
    r"my name is",
    r"call me",
    r"i(?:'| a)m \w+",
    r"i (?:really )?like",
    r"i love",
    r"i prefer",
    r"i hate",
    r"i live in",
    r"i(?:'| a)m from",
    r"i work (?:at|for|in)",
    r"my favorite",
    r"my goal is",
    r"remember (?:this|that)",
    r"my age is",
    r"i(?:'| a)m \d{1,3} years old",
]

MAX_MEMORIES = 500
DUPLICATE_THRESHOLD = 0.92  # cosine similarity above this = duplicate
MIN_RETRIEVAL_SIMILARITY = 0.62
MAX_MEMORY_CONTEXT_CHARS = 900


def _memory_category(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ("my name is", "call me", "i am ", "i'm ")):
        return "profile"
    if any(marker in lowered for marker in ("i prefer", "i like", "i love", "i hate", "favorite")):
        return "preference"
    if any(marker in lowered for marker in ("i work", "my goal", "project", "workspace")):
        return "work"
    return "fact"


def is_important_message(message: str) -> bool:
    """Check if a message contains personal/memorable information."""
    text = message.strip().lower()
    return any(re.search(p, text) for p in _IMPORTANT_PATTERNS)


async def store_memory(text: str) -> bool:
    """
    Store a message in ChromaDB if it's important and not a duplicate.
    Returns True if stored, False if skipped.
    """
    if not is_important_message(text):
        return False

    try:
        # Generate embedding
        embedding = await generate_embedding(text)

        # Check for near-duplicates
        if collection.count() > 0:
            results = collection.query(
                query_embeddings=[embedding],
                n_results=1,
            )
            if results["distances"] and results["distances"][0]:
                # ChromaDB cosine distance: 0 = identical, 2 = opposite
                # similarity = 1 - (distance / 2)
                distance = results["distances"][0][0]
                similarity = 1 - (distance / 2)
                if similarity >= DUPLICATE_THRESHOLD:
                    print(f"[MEM] Skipped duplicate (similarity={similarity:.2f}): {text[:50]}...")
                    return False

        # Enforce max entries — evict oldest if at capacity
        if collection.count() >= MAX_MEMORIES:
            _evict_oldest()

        # Store in ChromaDB
        doc_id = str(uuid.uuid4())
        collection.add(
            ids=[doc_id],
            documents=[text],
            embeddings=[embedding],
            metadatas=[{
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "chat",
                "category": _memory_category(text),
            }],
        )
        print(f"[MEM] Memory stored: {text[:60]}...")
        return True
    except Exception as e:
        print(f"[MEM WARNING] Failed to store memory: {e}")
        return False


async def retrieve_memory(query: str, n_results: int = 5) -> str:
    """
    Retrieve the most relevant memories for a given query.
    Returns a formatted string of relevant memories, or empty string.
    """
    try:
        if collection.count() == 0:
            return ""

        query_embedding = await generate_embedding(query)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, collection.count()),
        )

        if not results["documents"] or not results["documents"][0]:
            return ""

        memories = []
        documents = results["documents"][0]
        distances = (results.get("distances") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]

        for idx, memory in enumerate(documents):
            distance = distances[idx] if idx < len(distances) else 2.0
            similarity = 1 - (distance / 2)
            if similarity < MIN_RETRIEVAL_SIMILARITY:
                continue
            metadata = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
            memories.append({
                "text": memory,
                "similarity": similarity,
                "category": metadata.get("category", "fact"),
                "timestamp": metadata.get("timestamp", ""),
            })

        if not memories:
            return ""

        memories.sort(key=lambda item: (item["similarity"], item["timestamp"]), reverse=True)
        lines = []
        char_count = 0
        for item in memories[:3]:
            line = f"- ({item['category']}) {item['text']}"
            if char_count + len(line) > MAX_MEMORY_CONTEXT_CHARS:
                break
            lines.append(line)
            char_count += len(line)
        return "\n".join(lines)
    except Exception as e:
        print(f"[MEM WARNING] Failed to retrieve memories: {e}")
        return ""


def get_all_memories() -> list[dict]:
    """Return all stored memories (for /memory API endpoint)."""
    try:
        if collection.count() == 0:
            return []

        all_data = collection.get(include=["documents", "metadatas"])
        memories = []
        for doc, meta in zip(all_data["documents"], all_data["metadatas"]):
            memories.append({
                "text": doc,
                "timestamp": meta.get("timestamp", ""),
            })
        return memories
    except Exception as e:
        print(f"[MEM WARNING] Failed to get all memories: {e}")
        return []


def clear_all_memories() -> None:
    """Delete all memories by recreating the collection."""
    try:
        global collection
        client.delete_collection("jarvis_memory")
        collection = client.get_or_create_collection(
            name="jarvis_memory",
            metadata={"hnsw:space": "cosine"},
        )
        # Update the module-level reference in db.chroma_client too
        import db.chroma_client as _db
        _db.collection = collection
        print("[MEM] All memories wiped from ChromaDB.")
    except Exception as e:
        print(f"[MEM WARNING] Failed to clear memories: {e}")


def _evict_oldest() -> None:
    """Remove the oldest memory entry to make room."""
    try:
        all_data = collection.get(include=["metadatas"])
        if not all_data["ids"]:
            return

        # Find the entry with the oldest timestamp
        oldest_idx = 0
        oldest_ts = all_data["metadatas"][0].get("timestamp", "")
        for i, meta in enumerate(all_data["metadatas"]):
            ts = meta.get("timestamp", "")
            if ts < oldest_ts:
                oldest_ts = ts
                oldest_idx = i

        collection.delete(ids=[all_data["ids"][oldest_idx]])
        print(f"[MEM] Evicted oldest memory to stay under {MAX_MEMORIES} limit.")
    except Exception as e:
        print(f"[MEM WARNING] Failed to evict oldest memory: {e}")
