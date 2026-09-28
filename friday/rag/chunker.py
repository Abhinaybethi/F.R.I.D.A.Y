"""
Semantic-ish chunker for knowledge documents.

Strategy (avoids arbitrary fixed-size windows):
  1. Markdown: split on headings (# / ## / ###); each section becomes a
     chunk when it fits the target size, otherwise it is split on sentence
     boundaries with a small overlap to preserve context.
  2. Plain text: paragraph split first, then sentence-level fallback.
  3. Every chunk carries provenance metadata (source, document, section,
     topic, content_type, timestamp).
"""
import os
import re
import hashlib
import datetime
from typing import List

from friday.rag.models import RAGChunk

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WS_RE = re.compile(r"\s+")

DEFAULT_TARGET = 600      # target char size per chunk
DEFAULT_MAX = 1200        # hard cap
DEFAULT_OVERLAP = 120     # overlap chars when splitting long sections
MIN_CHUNK = 24            # drop sub-sentence fragments

_STOP = set(("the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
             "with", "as", "is", "are", "was", "were", "it", "this", "that"))


def _slug(text: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", text.lower())
             if w not in _STOP and len(w) > 2]
    return " ".join(words[:6])


def _normalise_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _split_long(text: str, target: int, max_size: int, overlap: int) -> List[str]:
    """Split text into overlapping windows at sentence boundaries."""
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    chunks: List[str] = []
    cur = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(cur) + len(sent) + 1 <= target:
            cur = (cur + " " + sent).strip() if cur else sent
            continue
        if cur:
            chunks.append(cur)
        if len(sent) > max_size:
            # single sentence too big; hard split with overlap
            for i in range(0, len(sent), max_size - overlap):
                piece = sent[i:i + max_size].strip()
                if len(piece) >= MIN_CHUNK:
                    chunks.append(piece)
            cur = ""
        else:
            cur = sent
    if cur and len(cur) >= MIN_CHUNK:
        chunks.append(cur)
    return chunks


def _chunk_markdown(text: str, source: str, document: str, target: int,
                    max_size: int, overlap: int, timestamp: str,
                    content_type: str) -> List[RAGChunk]:
    # Locate heading spans.
    matches = list(_HEADING_RE.finditer(text))
    bounds = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        bounds.append((m.group(2).strip(), start, end, len(m.group(1))))

    if not bounds:
        # No headings: treat whole text as one flat section then split.
        return _make_chunks([("", text)], source, document, target, max_size,
                            overlap, timestamp, content_type)

    out = []
    for heading, start, end, level in bounds:
        body = text[start:end].strip()
        if not body:
            continue
        out.extend(_make_chunks([(heading, body)], source, document, target,
                                max_size, overlap, timestamp, content_type))
    return out


def _make_chunks(sections: List[tuple], source: str, document: str, target: int,
                 max_size: int, overlap: int, timestamp: str,
                 content_type: str) -> List[RAGChunk]:
    result = []
    parent = ""
    for heading, body in sections:
        heading_norm = _normalise_ws(heading).strip("#")
        if heading_norm and heading_norm.lower() not in (parent.lower(),):
            parent = heading_norm
        if len(body) <= max_size:
            if len(body) >= MIN_CHUNK:
                result.append(_to_chunk(body, parent, source, document,
                                        timestamp, content_type))
        else:
            for piece in _split_long(body, target, max_size, overlap):
                result.append(_to_chunk(piece, parent, source, document,
                                        timestamp, content_type))
    return result


def _to_chunk(text: str, heading: str, source: str, document: str,
              timestamp: str, content_type: str) -> RAGChunk:
    clean = _normalise_ws(text)
    chunk_id = f"{_hash(source)}-{_hash(clean)[:6]}"
    return RAGChunk(
        id=chunk_id,
        text=clean,
        source=source,
        document=document,
        section=heading,
        topic=_slug(f"{document} {heading}" if heading else document),
        project=os.path.basename(os.path.dirname(source)) if os.path.dirname(source) else "",
        content_type=content_type,
        timestamp=timestamp,
    )


def chunk_document(text: str, source: str = "", document: str = "",
                   content_type: str = "markdown",
                   target: int = DEFAULT_TARGET,
                   max_size: int = DEFAULT_MAX,
                   overlap: int = DEFAULT_OVERLAP) -> List[RAGChunk]:
    """Chunk a single document body into RAGChunks with provenance metadata."""
    if not text or not text.strip():
        return []
    text = text.strip()
    doc = document or os.path.basename(source) or "untitled"
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if content_type == "markdown" or (".md" in source or ".markdown" in source):
        return _chunk_markdown(text, source, doc, target, max_size, overlap, ts, "markdown")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    sections = [(p[:80], p) for p in paragraphs]
    return _make_chunks(sections, source, doc, target, max_size, overlap, ts, "text")