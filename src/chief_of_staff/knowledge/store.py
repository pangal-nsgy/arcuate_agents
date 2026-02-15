"""Unified knowledge store interface — combines vector search with structured metadata."""

from __future__ import annotations

import json
import logging
from typing import Any

from chief_of_staff.knowledge import database as db
from chief_of_staff.knowledge import vectordb
from chief_of_staff.knowledge.embeddings import content_hash

logger = logging.getLogger(__name__)


def ingest(
    source: str,
    source_id: str,
    title: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Ingest a document into both the vector store and structured database.

    Returns the document ID.
    """
    doc_id = content_hash(f"{source}:{source_id}")

    # Store in vector DB for semantic search
    vectordb.add_document(
        doc_id=doc_id,
        text=content,
        source=source,
        metadata={"title": title, **(metadata or {})},
    )

    # Store metadata in SQLite
    db.upsert_document(
        doc_id=doc_id,
        source=source,
        source_id=source_id,
        title=title,
        content_preview=content[:500],
        metadata=json.dumps(metadata or {}),
    )

    return doc_id


def search(
    query: str,
    n_results: int = 10,
    source_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Search the knowledge base. Combines semantic search with metadata."""
    return vectordb.search(query=query, n_results=n_results, source_filter=source_filter)


def get_context_for_query(query: str, max_tokens: int = 8000) -> str:
    """Retrieve relevant context for a query, formatted for the LLM.

    Returns a string of concatenated relevant documents, trimmed to max_tokens.
    Returns empty string if ChromaDB is unavailable (graceful degradation).
    """
    try:
        results = search(query, n_results=15)
    except Exception as e:
        logger.warning(f"ChromaDB search failed, continuing without context: {e}")
        return ""

    context_parts = []
    total_chars = 0
    char_limit = max_tokens * 4  # rough token-to-char ratio

    for r in results:
        source = r["metadata"].get("source", "unknown")
        title = r["metadata"].get("title", "untitled")
        header = f"[Source: {source} | {title}]"
        entry = f"{header}\n{r['text']}\n"

        if total_chars + len(entry) > char_limit:
            break

        context_parts.append(entry)
        total_chars += len(entry)

    return "\n---\n".join(context_parts)
