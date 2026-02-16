"""ChromaDB vector store for semantic search across all ingested content."""

from __future__ import annotations

import json
from typing import Any

import chromadb

from chief_of_staff.config import settings
from chief_of_staff.knowledge.embeddings import chunk_text, content_hash

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None

COLLECTION_NAME = "chief_of_staff_knowledge"


def _sanitize_metadata_value(value: Any) -> Any:
    """Chroma metadata values must be scalar. Serialize complex values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {k: _sanitize_metadata_value(v) for k, v in metadata.items()}


def get_collection() -> chromadb.Collection:
    """Get or create the ChromaDB collection."""
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def add_document(
    doc_id: str,
    text: str,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Chunk and add a document to the vector store. Returns number of chunks added."""
    collection = get_collection()
    chunks = chunk_text(text)
    base_meta = {"source": source, "doc_id": doc_id}
    if metadata:
        base_meta.update(metadata)
    base_meta = _sanitize_metadata(base_meta)

    ids = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}_chunk_{i}"
        ids.append(chunk_id)
        documents.append(chunk)
        metadatas.append({**base_meta, "chunk_index": i, "total_chunks": len(chunks)})

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    return len(ids)


def search(
    query: str,
    n_results: int = 10,
    source_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic search across all knowledge. Returns list of {text, metadata, distance}."""
    collection = get_collection()

    where = {"source": source_filter} if source_filter else None

    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=where,
    )

    items = []
    if results["documents"] and results["documents"][0]:
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            items.append({"text": doc, "metadata": meta, "distance": dist})

    return items


def delete_document(doc_id: str) -> None:
    """Remove all chunks for a document."""
    collection = get_collection()
    # Get all chunk IDs for this document
    results = collection.get(where={"doc_id": doc_id})
    if results["ids"]:
        collection.delete(ids=results["ids"])
