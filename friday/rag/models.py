"""
RAG data models for F.R.I.D.A.Y.

Small, typed structures shared across the retrieval pipeline so components
swap cleanly without importing each other's internals.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RAGChunk:
    """A single indexed knowledge chunk with provenance metadata."""
    id: str                       # stable chunk_id
    text: str                     # chunk body
    source: str = ""              # filename / path
    document: str = ""            # friendly document name
    section: str = ""             # nearest heading
    topic: str = ""               # derived keywords / heading slug
    project: str = ""             # owning project (when known)
    content_type: str = "markdown"
    timestamp: str = ""
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class RAGConfig:
    """Runtime knobs for the retrieval pipeline (mirrors config.yaml `rag:`).

    Values are validated/clamped by the config layer before construction.
    """
    enabled: bool = True
    collection: str = "friday_knowledge"
    persist_dir: str = ""                    # "" -> project .data/rag
    retrieval_k: int = 15                    # candidates pulled before rerank
    final_k: int = 5                         # context after rerank
    similarity_threshold: float = 0.30       # vector relevance floor (all-MiniLM calibrated)
    rerank: bool = True
    hybrid: bool = True
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    merge_final_k: int = 3
    context_compression: bool = True
    max_context_tokens: int = 3000           # approx token budget for LLM block
    relevance_min_score: float = 0.30        # compressed rerank floor
    no_context_message: str = (
        "I don't have enough relevant information in my knowledge base "
        "to answer that confidently."
    )
    auto_ingest: bool = True                 # build index from docs/ README on first use
    source_dirs: List[str] = field(default_factory=lambda: ["docs", "."])
    include_md: bool = True                  # index *.md in source_dirs


@dataclass
class RetrievedChunk:
    """A ranked, scored candidate with provenance ready for the LLM."""
    chunk: RAGChunk
    vector_score: float = 0.0
    lexical_score: float = 0.0
    rerank_score: float = 0.0


@dataclass
class RAGQuery:
    """Output of query analysis — retrieval-friendly representation."""
    original: str            # raw user transcript
    semantic_query: str      # expanded / pronoun-resolved retrieval query
    keywords: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    query_type: str = "factual"   # factual|project|technical|memory|conversational|command
    needs_rag: bool = True
    filters: Dict[str, str] = field(default_factory=dict)  # e.g. {"project": "..."}
    conversation_context: str = ""   # compact prior-turn summary for follow-ups


@dataclass
class RAGResult:
    """Final output of the RAG pipeline — what actually reaches the LLM."""
    query: RAGQuery
    context_block: str             # compact, source-tagged text for the prompt
    chunks: List[RetrievedChunk] = field(default_factory=list)
    final_context: List[RetrievedChunk] = field(default_factory=list)
    used: bool = False             # True when a relevance gate passed
    no_context: bool = False       # True when the gate rejected all candidates
    reason: str = ""
    stats: Dict[str, float] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)  # unique file/section labels