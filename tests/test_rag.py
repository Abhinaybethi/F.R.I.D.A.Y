"""
Unit tests for the RAG pipeline (query analysis, chunking, BM25,
run components, service orchestration, config validation).

All tests are offline; they never hit the network or an LLM server.
Index-heavy tests use a temporary persist directory and a minimal corpus.
"""
import sys
import os
import tempfile
import json
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pytest

from friday.rag.query_analyzer import analyze_query
from friday.rag.chunker import chunk_document
from friday.rag.lexical import BM25, tokenize
from friday.rag.models import RAGConfig, RAGChunk
from friday.rag.service import RAGService
from friday.rag.ingestion import chunk_files, discover_sources
from friday.rag.prompt_builder import build_rag_prompt_block, no_context_block


# ----------------------------------------------------------------------
# Query analysis / routing
# ----------------------------------------------------------------------

def test_command_queries_skip_rag():
    for q in ("open chrome", "play jazz", "set volume to 30", "what time is it",
              "tell me a joke", "find my resume file"):
        a = analyze_query(q, [])
        assert a.needs_rag is False, q


def test_factual_and_project_questions_need_rag():
    for q in ("how does text to speech work in friday?",
              "summarize the clean install instructions.",
              "did i implement physical voice certification?",
              "what does the forensic baseline document cover?"):
        a = analyze_query(q, [])
        assert a.needs_rag is True, q
        assert a.query_type in ("factual", "project", "technical")


def test_hey_does_not_fire_inside_they():
    # Regression: substring "hey" must not match inside "they".
    a = analyze_query("Which phases have product audit reports and what did they cover?")
    assert a.needs_rag is True
    assert a.query_type == "factual"


def test_memory_questions_route_to_memory_type():
    a = analyze_query("Do you remember my favorite programming language?")
    assert a.query_type == "memory"
    assert a.needs_rag is True


def test_followup_pronoun_resolution_uses_history():
    hist = [{"transcript": "How does speech to text work?", "response": "faster-whisper is used."}]
    a = analyze_query("Which model does it use?", history=hist)
    assert "it" in a.original
    assert a.semantic_query != a.original  # expanded with prior context
    assert "speech to text" in a.semantic_query


# ----------------------------------------------------------------------
# Chunking
# ----------------------------------------------------------------------

def test_markdown_chunker_produces_section_chunks():
    md = "# Overview\nSome intro text.\n\n## Auth\n\nFriday authenticates with tokens.\n\n## TTS\n\nPiper synthesizes speech."
    chunks = chunk_document(md, source="docs/TEST.md", document="TEST.md")
    assert len(chunks) >= 2
    sections = {c.section for c in chunks}
    assert "Auth" in sections
    assert all(c.document == "TEST.md" for c in chunks)
    assert all(c.source == "docs/TEST.md" for c in chunks)


def test_chunker_splits_long_sections_at_sentences():
    body = " ".join("Sentence number %d about the assistant pipeline." % i for i in range(60))
    chunks = chunk_document(body, source="docs/TEST.md", document="TEST.md",
                            target=300, max_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(0 < len(c.text) <= 500 for c in chunks)


def test_chunker_rejects_empty_input():
    assert chunk_document("", source="x.md") == []
    assert chunk_document("   \n  ", source="x.md") == []


# ----------------------------------------------------------------------
# BM25
# ----------------------------------------------------------------------

def test_bm25_ranks_term_matches_first():
    docs = [
        "Friday uses faster-whisper for speech to text conversion.",
        "The corpus is indexed as markdown chunks.",
        "pip install faster-whisper then configure the model.",
    ]
    bm = BM25(docs)
    scores = bm.score_docs("faster-whisper speech")
    top = max(scores, key=scores.get)
    assert top == 0 or top == 2  # docs 0 and 2 both mention faster-whisper


def test_bm25_out_of_range_doc_safe():
    bm = BM25(["one", "two three"])
    out = bm.score_docs("two", doc_ids=[0, 5])
    assert 5 not in out


# ----------------------------------------------------------------------
# RAG service end-to-end (offline, tiny corpus)
# ----------------------------------------------------------------------

def _tiny_service(tmp_path, content, threshold=0.25):
    cfg = RAGConfig(
        enabled=True, collection="friday_knowledge",
        persist_dir=str(tmp_path / "index"),
        similarity_threshold=threshold, relevance_min_score=0.10,
        retrieval_k=15, final_k=5, auto_ingest=False,
        context_compression=True, max_context_tokens=2000,
    )
    svc = RAGService(cfg)
    chunks = chunk_document(content, source="docs/TINY.md", document="TINY.md")
    svc.index.add_chunks(chunks)
    return svc


def test_rag_returns_grounded_context(tmp_path):
    content = ("# Voice\n\nFriday performs speech to text with faster-whisper "
               "running locally on CPU with int8 precision.\n\n"
               "# TTS\n\nPiper synthesizes offline speech from text.")
    svc = _tiny_service(tmp_path, content)
    r = svc.build_result("how does speech to text work in friday?")
    assert r.used is True
    assert r.final_context
    assert "faster-whisper" in r.context_block
    block = svc.build_prompt_block(r)
    assert "RETRIEVED CONTEXT" in block or "knowledge base" in block
    assert "Source:" in block or "INSTRUCTIONS" in block


def test_rag_gate_rejects_irrelevant_query(tmp_path):
    content = "# Voice\n\nPiper synthesizes offline speech from text."
    svc = _tiny_service(tmp_path, content)
    r = svc.build_result("what is the best recipe for chocolate cake?")
    assert r.no_context is True or r.used is False
    assert r.final_context == []


def test_rag_command_does_not_retrieve(tmp_path):
    content = "# Voice\n\nPiper synthesizes offline speech from text."
    svc = _tiny_service(tmp_path, content)
    r = svc.build_result("open chrome", history=[])
    assert r.used is False
    assert r.reason == "rag_not_needed"


def test_rag_disabled_service_returns_empty():
    cfg = RAGConfig(enabled=False)
    svc = RAGService(cfg)
    assert svc.build_result("how does tts work?").context_block == ""


# ----------------------------------------------------------------------
# Ingestion
# ----------------------------------------------------------------------

def test_discover_and_chunk_documents(tmp_path):
    (tmp_path / "a.md").write_text("# A\n\nSome longer a content here to exceed the minimum chunk size.", encoding="utf-8")
    (tmp_path / "b.markdown").write_text("# B\n\nSome longer b content here to exceed the minimum chunk size.", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("plain text file", encoding="utf-8")
    src = str(tmp_path)
    cfg = RAGConfig(source_dirs=[src])
    files = discover_sources(cfg)
    assert len(files) == 2  # only markdown
    chunks = chunk_files(files)
    docs = {c.document for c in chunks}
    assert "a.md" in docs and "b.markdown" in docs


# ----------------------------------------------------------------------
# Prompt building
# ----------------------------------------------------------------------

def test_prompt_block_returns_empty_when_no_content():
    class _Res:
        final_context = []
    assert build_rag_prompt_block(_Res()) == ""


def test_no_context_block_contains_message():
    out = no_context_block("I have nothing relevant.")
    assert "I have nothing relevant." in out


# ----------------------------------------------------------------------
# Config validation
# ----------------------------------------------------------------------

def test_rag_config_validation_clamps_values():
    from friday.utils.config_validator import validate_config
    raw = {"rag": {"retrieval_k": 9999, "final_k": -1, "similarity_threshold": 99,
                   "source_dirs": "bad"}}
    valid, sanitized, msgs = validate_config(raw)
    assert valid is True
    assert sanitized["rag"]["retrieval_k"] == 50
    assert sanitized["rag"]["final_k"] == 1
    assert sanitized["rag"]["similarity_threshold"] == 1.0
    assert sanitized["rag"]["source_dirs"] == ["docs", "."]
    assert any("rag" in m for m in msgs)


def test_rag_config_validation_defaults_when_missing():
    from friday.utils.config_validator import validate_config
    valid, sanitized, _ = validate_config({})
    assert sanitized["rag"]["enabled"] is True
    assert sanitized["rag"]["similarity_threshold"] == 0.30
    assert sanitized["rag"]["retrieval_k"] == 15


def test_rag_config_roundtrips_enabled_block():
    from friday.utils.config_validator import validate_config
    raw = {"rag": {"enabled": True, "hybrid": True, "context_compression": True,
                   "similarity_threshold": 0.42}}
    valid, sanitized, _ = validate_config(raw)
    assert sanitized["rag"]["similarity_threshold"] == 0.42