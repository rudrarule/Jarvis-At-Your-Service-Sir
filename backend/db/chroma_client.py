"""
chroma_client.py — Persistent ChromaDB Setup
Initializes a local ChromaDB client and the jarvis_memory collection.
"""
import os
import chromadb

# Store data in backend/chroma_data/ (persistent across restarts)
_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_data")

client = chromadb.PersistentClient(path=_DB_PATH)

collection = client.get_or_create_collection(
    name="jarvis_memory",
    metadata={"hnsw:space": "cosine"},
)

print(f"[ChromaDB] Ready - {collection.count()} memories loaded from {_DB_PATH}")
