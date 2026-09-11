"""Scoped local evidence index and governed memory projection.

The index owns exact typed evidence and relationships. Cognee receives only a
bounded, provenance-bearing summary through ``MemoryManager``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from ingestion_pipelines.models import IngestedDocument
from api.storage import ObjectStore
from memory import AccessContext, KnowledgeUnit, MemoryManager, MemoryType, ScopeType, Source, SourceType
from pipelines.common.ntro_policy import require_classification, require_classification_access


class EvidenceNotFoundError(KeyError):
    """Raised when an evidence ID is absent or outside the access scope."""


class EvidenceIndex:
    """SQLite-backed first slice for evidence retrieval and idempotent writes."""

    def __init__(
        self,
        db_path: str | Path = "artifacts/.state/evidence_index.db",
        *,
        object_store: ObjectStore | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.object_store = object_store
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_blocks (
                    evidence_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    source_reference TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    content TEXT NOT NULL,
                    location_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    extractor_version TEXT NOT NULL,
                    model_version TEXT,
                    user_id TEXT,
                    case_id TEXT,
                    task_id TEXT,
                    classification_level TEXT NOT NULL,
                    object_id TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_scope
                    ON evidence_blocks(user_id, case_id, task_id, classification_level);
                CREATE INDEX IF NOT EXISTS idx_evidence_modality
                    ON evidence_blocks(modality, document_id);
                CREATE TABLE IF NOT EXISTS evidence_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    heading_path_json TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    parent_chunk_id TEXT
                );
                CREATE TABLE IF NOT EXISTS evidence_relationships (
                    relation_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    source_evidence_id TEXT NOT NULL,
                    target_evidence_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    provenance_json TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence_blocks)")}
            if "object_id" not in columns:
                connection.execute("ALTER TABLE evidence_blocks ADD COLUMN object_id TEXT")

    def index_document(
        self,
        document: IngestedDocument,
        *,
        classification_level: str = "RESTRICTED",
    ) -> dict[str, Any]:
        """Replace one document's derived index rows atomically."""

        classification = require_classification(classification_level)
        if not document.evidence_blocks:
            return {
                "document_id": document.id,
                "evidence_count": 0,
                "chunk_count": 0,
                "relationship_count": 0,
                "indexed": False,
            }
        source_reference = str(document.source_path)
        source_hash = document.evidence_blocks[0].source_hash
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM evidence_blocks WHERE document_id = ?", (document.id,))
            connection.execute("DELETE FROM evidence_chunks WHERE document_id = ?", (document.id,))
            connection.execute("DELETE FROM evidence_relationships WHERE document_id = ?", (document.id,))
            now = time.time()
            for block in document.evidence_blocks:
                object_id = None
                if self.object_store is not None and block.content:
                    stored = self.object_store.put_bytes(
                        block.content.encode("utf-8"),
                        name=f"{block.evidence_id}.txt",
                        kind="evidence",
                        media_type="text/plain",
                        classification_level=classification,
                        owner_id=document.user_id,
                        case_id=document.case_id,
                        task_id=document.task_id,
                        retention_class="evidence",
                        parent_object_ids=(),
                    )
                    object_id = stored.object_id
                connection.execute(
                    """
                    INSERT INTO evidence_blocks
                    (evidence_id, document_id, source_hash, source_reference, modality,
                     content, location_json, metadata_json, confidence, extractor_version,
                     model_version, user_id, case_id, task_id, classification_level, object_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        block.evidence_id,
                        document.id,
                        block.source_hash,
                        source_reference,
                        block.modality,
                        block.content or "",
                        json.dumps(block.location.model_dump(mode="json"), ensure_ascii=False),
                        json.dumps(block.metadata, ensure_ascii=False, default=str),
                        block.confidence,
                        block.extractor_version,
                        block.model_version,
                        document.user_id,
                        document.case_id,
                        document.task_id,
                        classification,
                        object_id,
                        now,
                    ),
                )
            for chunk in document.chunks:
                connection.execute(
                    """
                    INSERT INTO evidence_chunks
                    (chunk_id, document_id, content, evidence_ids_json, heading_path_json,
                     source_hash, chunk_index, parent_chunk_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        document.id,
                        chunk.content,
                        json.dumps(chunk.evidence_ids, ensure_ascii=False),
                        json.dumps(chunk.heading_path, ensure_ascii=False),
                        chunk.source_hash,
                        chunk.chunk_index,
                        chunk.parent_chunk_id,
                    ),
                )
            for relation in document.relationships:
                connection.execute(
                    """
                    INSERT INTO evidence_relationships
                    (relation_id, document_id, source_evidence_id, target_evidence_id,
                     relation_type, confidence, provenance_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relation.relation_id,
                        document.id,
                        relation.source_evidence_id,
                        relation.target_evidence_id,
                        relation.relation_type,
                        relation.confidence,
                        json.dumps(relation.provenance, ensure_ascii=False, default=str),
                    ),
                )
            connection.commit()
        return {
            "document_id": document.id,
            "source_hash": source_hash,
            "evidence_count": len(document.evidence_blocks),
            "chunk_count": len(document.chunks),
            "relationship_count": len(document.relationships),
            "indexed": True,
        }

    def _scope_rows(
        self,
        context: AccessContext,
        *,
        modality: Iterable[str] | None = None,
    ) -> list[sqlite3.Row]:
        if not context.user_id:
            raise PermissionError("evidence search requires a user scope")
        params: list[Any] = [context.user_id, context.case_id]
        query = """
            SELECT * FROM evidence_blocks
            WHERE user_id = ? AND (case_id = ? OR case_id IS NULL)
        """
        if context.task_id:
            query += " AND (task_id = ? OR task_id IS NULL)"
            params.extend([context.task_id])
        if modality:
            values = list(modality)
            query += f" AND modality IN ({','.join('?' for _ in values)})"
            params.extend(values)
        query += " ORDER BY updated_at DESC, evidence_id"
        with self._connect() as connection:
            return connection.execute(query, params).fetchall()

    @staticmethod
    def _matches_query(content: str, query: str) -> int:
        terms = [term.lower() for term in re.findall(r"[\w-]+", query) if len(term) > 1]
        lowered = content.lower()
        return sum(lowered.count(term) for term in terms)

    @staticmethod
    def _safe_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "evidence_id": str(row["evidence_id"]),
            "document_id": str(row["document_id"]),
            "source_reference": str(row["source_reference"]),
            "modality": str(row["modality"]),
            "content": str(row["content"]),
            "location": json.loads(str(row["location_json"])),
            "metadata": json.loads(str(row["metadata_json"])),
            "confidence": float(row["confidence"]),
            "extractor_version": str(row["extractor_version"]),
            "model_version": row["model_version"],
            "source_hash": str(row["source_hash"]),
            "object_id": row["object_id"],
        }

    def search(
        self,
        query: str,
        context: AccessContext,
        *,
        modalities: Iterable[str] | None = None,
        top_k: int = 10,
        classification_level: str = "RESTRICTED",
    ) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("query must be non-empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        access = require_classification(classification_level)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for row in self._scope_rows(context, modality=modalities):
            require_classification_access(access, str(row["classification_level"]))
            score = self._matches_query(str(row["content"]), query)
            if score:
                ranked.append((score, self._safe_row(row)))
        ranked.sort(key=lambda item: (-item[0], item[1]["evidence_id"]))
        return [dict(item, score=score) for score, item in ranked[:top_k]]

    def search_text(self, query: str, context: AccessContext, *, top_k: int = 10, classification_level: str = "RESTRICTED") -> list[dict[str, Any]]:
        return self.search(
            query,
            context,
            modalities=("text_document", "pdf_page", "pptx_slide"),
            top_k=top_k,
            classification_level=classification_level,
        )

    def search_visual(self, query: str, context: AccessContext, *, top_k: int = 10, classification_level: str = "RESTRICTED") -> list[dict[str, Any]]:
        return self.search(
            query,
            context,
            modalities=("image_ocr", "video_ocr", "video_scene"),
            top_k=top_k,
            classification_level=classification_level,
        )

    def search_table(self, query: str, context: AccessContext, *, top_k: int = 10, classification_level: str = "RESTRICTED") -> list[dict[str, Any]]:
        return self.search(
            query,
            context,
            modalities=("table", "pdf_table", "pptx_table"),
            top_k=top_k,
            classification_level=classification_level,
        )

    def search_video_segment(self, query: str, context: AccessContext, *, top_k: int = 10, classification_level: str = "RESTRICTED") -> list[dict[str, Any]]:
        return self.search(
            query,
            context,
            modalities=("audio_transcript", "video_ocr", "video_scene"),
            top_k=top_k,
            classification_level=classification_level,
        )

    def get_evidence(
        self,
        evidence_id: str,
        context: AccessContext,
        *,
        classification_level: str = "RESTRICTED",
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence_blocks WHERE evidence_id = ?", (str(evidence_id),)
            ).fetchone()
            if row is None:
                raise EvidenceNotFoundError(evidence_id)
        if context.user_id != row["user_id"] or context.case_id != row["case_id"]:
            raise EvidenceNotFoundError(evidence_id)
        if context.task_id and row["task_id"] not in {None, context.task_id}:
            raise EvidenceNotFoundError(evidence_id)
        require_classification_access(classification_level, str(row["classification_level"]))
        result = self._safe_row(row)
        with self._connect() as connection:
            result["relationships"] = [
                dict(item)
                for item in connection.execute(
                    """
                    SELECT relation_id, source_evidence_id, target_evidence_id,
                           relation_type, confidence
                    FROM evidence_relationships
                    WHERE source_evidence_id = ? OR target_evidence_id = ?
                    ORDER BY relation_id
                    """,
                    (str(evidence_id), str(evidence_id)),
                ).fetchall()
            ]
        return result

    def project_to_memory(
        self,
        document: IngestedDocument,
        memory_manager: MemoryManager,
        *,
        classification_level: str = "RESTRICTED",
        max_summary_chars: int = 6000,
    ) -> dict[str, Any]:
        """Project bounded summaries and references, never raw files, to Cognee."""

        classification = require_classification(classification_level)
        if not document.chunks:
            return {"projected": False, "reason": "no_evidence_chunks"}
        summary_lines = [
            f"Evidence summary for {document.source_path}",
            f"Document ID: {document.id}",
            f"Evidence IDs: {', '.join(block.evidence_id for block in document.evidence_blocks)}",
        ]
        remaining = max(512, int(max_summary_chars))
        for chunk in document.chunks:
            line = f"[{chunk.chunk_id}] {' '.join(chunk.heading_path)}\n{chunk.content.strip()}"
            if len(line) > remaining:
                line = line[:remaining].rstrip() + " …"
            summary_lines.append(line)
            remaining -= len(line) + 1
            if remaining <= 0:
                break
        summary = "\n\n".join(summary_lines)[:max_summary_chars]
        try:
            source_type = SourceType(document.doc_type)
        except ValueError:
            source_type = SourceType.OTHER
        context = AccessContext(
            user_id=document.user_id,
            case_id=document.case_id,
            task_id=document.task_id,
        )
        scope_type = (
            ScopeType.CASE
            if document.case_id
            else ScopeType.USER
            if document.user_id
            else ScopeType.SYSTEM
        )
        unit = KnowledgeUnit(
            unit_id=f"evidence-summary:{document.id}",
            content=summary,
            source=Source(document.id, source_type, str(document.source_path)),
            metadata={
                "projection": "evidence-summary",
                "classification_level": classification,
                "evidence_ids": [block.evidence_id for block in document.evidence_blocks],
                "chunk_ids": [chunk.chunk_id for chunk in document.chunks],
                "relationship_ids": [relation.relation_id for relation in document.relationships],
            },
            provenance={
                "source_hash": document.evidence_blocks[0].source_hash,
                "compiler": "evidence-index@1.0.0",
                "exact_evidence_store": "EvidenceIndex",
            },
        )
        receipt = memory_manager.remember(
            unit,
            context,
            scope_type=scope_type,
            memory_type=MemoryType.SUMMARY,
            run_in_background=False,
        )
        return {
            "projected": True,
            "memory_id": receipt.memory.id,
            "evidence_count": len(document.evidence_blocks),
            "chunk_count": len(document.chunks),
            "classification_level": classification,
        }


__all__ = ["EvidenceIndex", "EvidenceNotFoundError"]
