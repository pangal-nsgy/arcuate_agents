"""Google Docs/Drive ingestion — pull documents into the knowledge base."""

from __future__ import annotations

import logging
from typing import Any

from chief_of_staff.communication._google_auth import get_docs_service, get_drive_service
from chief_of_staff.config import settings
from chief_of_staff.knowledge.store import ingest

logger = logging.getLogger(__name__)


def fetch_and_ingest_docs(folder_id: str | None = None, max_results: int = 50) -> int:
    """Fetch Google Docs and ingest into the knowledge base.

    Args:
        folder_id: Optional Drive folder ID to scope the search.
        max_results: Maximum number of docs to fetch.

    Returns:
        Number of documents ingested.
    """
    drive = get_drive_service()
    docs = get_docs_service()

    files = _list_docs_from_drive(
        drive=drive,
        folder_id=folder_id,
        max_results=max_results,
    )
    count = 0

    for file in files:
        try:
            doc = docs.documents().get(documentId=file["id"]).execute()
            content = _extract_doc_text(doc)

            ingest(
                source="gdocs",
                source_id=file["id"],
                title=file["name"],
                content=content,
                metadata={
                    "doc_id": file["id"],
                    "modified": file.get("modifiedTime", ""),
                    "owners": [o.get("displayName", "") for o in file.get("owners", [])],
                },
            )
            count += 1

        except Exception as e:
            logger.error(f"Failed to ingest doc {file['id']} ({file['name']}): {e}")

    logger.info(f"Ingested {count}/{len(files)} Google Docs")
    return count


def _iter_doc_files(
    drive: Any,
    *,
    query: str,
    max_results: int,
    corpora: str,
    drive_id: str | None = None,
) -> list[dict[str, Any]]:
    """List Google Docs files with pagination and all-drives support."""
    out: list[dict[str, Any]] = []
    page_token: str | None = None

    while len(out) < max_results:
        page_size = min(100, max_results - len(out))
        kwargs: dict[str, Any] = {
            "q": query,
            "pageSize": page_size,
            "fields": "nextPageToken, files(id, name, modifiedTime, owners, driveId)",
            "spaces": "drive",
            "corpora": corpora,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        if drive_id:
            kwargs["driveId"] = drive_id

        resp = drive.files().list(**kwargs).execute()
        out.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return out


def _list_accessible_shared_drive_ids(drive: Any, limit: int = 200) -> list[str]:
    """List shared drive IDs visible to the authenticated Google account."""
    drive_ids: list[str] = []
    page_token: str | None = None

    while len(drive_ids) < limit:
        page_size = min(100, limit - len(drive_ids))
        kwargs: dict[str, Any] = {
            "pageSize": page_size,
            "fields": "nextPageToken, drives(id, name)",
        }
        if page_token:
            kwargs["pageToken"] = page_token

        resp = drive.drives().list(**kwargs).execute()
        for row in resp.get("drives", []):
            drive_id = row.get("id")
            if drive_id:
                drive_ids.append(drive_id)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return drive_ids


def _list_docs_from_drive(drive: Any, folder_id: str | None, max_results: int) -> list[dict[str, Any]]:
    """Get documents from My Drive, shared-with-me, and optional Shared Drives."""
    query_parts = [
        "mimeType='application/vnd.google-apps.document'",
        "trashed=false",
    ]
    if folder_id:
        query_parts.append(f"'{folder_id}' in parents")
    base_query = " and ".join(query_parts)

    files: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _merge(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            file_id = row.get("id")
            if not file_id or file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            files.append(row)

    # 1) Primary pass: include all accessible drives.
    _merge(_iter_doc_files(drive, query=base_query, max_results=max_results, corpora="allDrives"))

    # 2) Shared-with-me pass (helps capture docs not surfaced in user corpus).
    if not folder_id and len(files) < max_results:
        shared_query = f"{base_query} and sharedWithMe=true"
        _merge(
            _iter_doc_files(
                drive,
                query=shared_query,
                max_results=max_results - len(files),
                corpora="allDrives",
            )
        )

    # 3) Optional explicit shared drives/workspaces.
    raw_drive_ids = settings.google_shared_drive_ids.strip()
    configured_drive_ids = [d.strip() for d in raw_drive_ids.split(",") if d.strip()]
    discovered_drive_ids: list[str] = []
    try:
        discovered_drive_ids = _list_accessible_shared_drive_ids(drive)
    except Exception as e:
        logger.warning(f"Could not auto-discover shared drives: {e}")

    drive_ids = sorted(set(configured_drive_ids + discovered_drive_ids))
    if drive_ids:
        logger.info(f"Google Docs ingestion scanning {len(drive_ids)} shared drive(s)")

    for drive_id in drive_ids:
        if len(files) >= max_results:
            break
        _merge(
            _iter_doc_files(
                drive,
                query=base_query,
                max_results=max_results - len(files),
                corpora="drive",
                drive_id=drive_id,
            )
        )

    return files[:max_results]


def _extract_doc_text(doc: dict[str, Any]) -> str:
    """Extract plain text from a Google Docs API document response."""
    text_parts: list[str] = []

    body = doc.get("body", {})
    for element in body.get("content", []):
        paragraph = element.get("paragraph", {})
        for elem in paragraph.get("elements", []):
            text_run = elem.get("textRun", {})
            content = text_run.get("content", "")
            if content:
                text_parts.append(content)

    return "".join(text_parts)
