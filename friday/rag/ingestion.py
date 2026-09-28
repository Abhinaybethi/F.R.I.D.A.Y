"""
Knowledge ingestion — builds the vector index from local markdown sources.

Scans configured source directories for *.md files, chunks them with the
section-aware chunker, and upserts into the persistent collection. Idempotent
(chunks are keyed by content hash, so re-runs add nothing).
"""
import os
import glob
from typing import List

from friday.rag.models import RAGChunk, RAGConfig
from friday.rag.chunker import chunk_document
from friday.rag.index import VectorIndex
from friday.rag.embedder import Embedder
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def discover_sources(config: RAGConfig) -> List[str]:
    files: List[str] = []
    seen = set()
    for directory in config.source_dirs:
        if not directory:
            continue
        if not os.path.isdir(directory):
            directory = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), directory)
        for pattern in ("**/*.md", "**/*.markdown", "*.md"):
            for f in glob.glob(os.path.join(directory, pattern), recursive=True):
                norm = os.path.normpath(f)
                if "_index" in norm or os.sep + ".git" + os.sep in norm:
                    continue
                if norm not in seen:
                    seen.add(norm)
                    files.append(norm)
    return sorted(files)


def chunk_files(files: List[str]) -> List[RAGChunk]:
    chunks: List[RAGChunk] = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError as e:
            logger.warning("[RAG] Cannot read %s: %s", f, e)
            continue
        if not text.strip():
            continue
        content_type = _content_type(f)
        document = os.path.basename(f)
        chunks.extend(chunk_document(text, source=f, document=document, content_type=content_type))
    return chunks


def _content_type(path: str) -> str:
    base = os.path.basename(path).lower()
    if base in ("readme.md",):
        return "readme"
    if ".md" in base or ".markdown" in base:
        return "markdown"
    return "text"


def ingest(config: RAGConfig, index: VectorIndex, embedder: Embedder) -> dict:
    """Full ingestion run. Returns {added, total_chunks, sources}."""
    files = discover_sources(config)
    chunks = chunk_files(files)
    added = index.add_chunks(chunks)
    total = index.count()
    logger.info(
        "[RAG] Ingestion complete: sources=%d chunks=%d added=%d total=%d",
        len(files), len(chunks), added, total,
    )
    return {"sources": len(files), "chunks": len(chunks), "added": added, "total": total}