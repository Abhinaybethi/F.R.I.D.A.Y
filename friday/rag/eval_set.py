"""
Offline evaluation set for the RAG pipeline.

Each item carries a question (optionally with conversation history), a
`type` (direct / project / multi-hop / follow-up / negative), and the
expected source document(s) a correct retrieval should surface.

Grounded retrieval quality (hit@k, MRR, gate precision) is fully measurable
offline — no LLM required.  Answer-quality measurement is additive and runs
only when Bonsai / Ollama is actually reachable (see scripts/rag_eval.py).
"""
from typing import List, Dict, Optional


def build_eval_set() -> List[Dict]:
    return [
        # --- direct (single-document factual retrieval) ---
        {"type": "direct", "question": "How does wake word detection work in Friday?",
         "expected": ["PHASE_28_PRODUCT_AUDIT.md"]},
        {"type": "direct", "question": "What is the active conversation session timeout?",
         "expected": ["PHASE_NEXT_WORKFLOW_AUDIT.md", "V1_1_BACKLOG.md"]},
        {"type": "direct", "question": "How does text to speech work in Friday?",
         "expected": ["PHASE_24_5_PHYSICAL_VOICE_CERTIFICATION.md", "PHASE_30_5_FORENSIC_BASELINE.md", "PHASE_26_PRODUCT_AUDIT.md"]},
        {"type": "direct", "question": "Does the assistant require a wake word to respond?",
         "expected": ["PHASE_28_PRODUCT_AUDIT.md"]},
        {"type": "direct", "question": "What security controls does the project document?",
         "expected": ["SECURITY.md"]},
        {"type": "direct", "question": "How is real tool execution gated in the project?",
         "expected": ["SECURITY.md", "ARCHITECTURE.md"]},
        {"type": "direct", "question": "What is in the V1.1 backlog?",
         "expected": ["V1_1_BACKLOG.md"]},
        {"type": "direct", "question": "What does the forensic baseline document cover?",
         "expected": ["PHASE_30_5_FORENSIC_BASELINE.md"]},
        {"type": "direct", "question": "Summarize the clean install instructions.",
         "expected": ["CLEAN_INSTALL.md"]},
        {"type": "direct", "question": "What went wrong after the V1.1 release?",
         "expected": ["POST_RELEASE_FAILURE_MODEL.md", "CI_FAILURE_ANALYSIS.md"]},

        # --- project (project-specific context, `did I / my project`) ---
        {"type": "project", "question": "Did I implement physical voice certification?",
         "expected": ["PHASE_24_5_PHYSICAL_VOICE_CERTIFICATION.md"]},
        {"type": "project", "question": "Is there a real world test plan in my project?",
         "expected": ["PHASE_29_5_REAL_WORLD_TEST_PLAN.md", "PHASE_NEXT_REAL_WORLD_TEST_PLAN.md"]},
        {"type": "project", "question": "My stress test report - where is it?",
         "expected": ["PHASE_25_STRESS_TEST_REPORT.md"]},
        {"type": "project", "question": "What does the phase 28 action audit say?",
         "expected": ["PHASE_28_5_ACTION_AUDIT.md"]},

        # --- multi-hop (evidence is spread over several documents) ---
        {"type": "multi-hop", "question": "Which phases have product audit reports and what did they cover?",
         "expected": [f"PHASE_{p}_PRODUCT_AUDIT.md" for p in (20, 21, 22, 23, 26, 27, 28)]},
        {"type": "multi-hop", "question": "How does the voice pipeline connect to the reasoning layer?",
         "expected": ["ARCHITECTURE.md"]},
        {"type": "multi-hop", "question": "What does the reliability scorecard say about the stress test results?",
         "expected": ["PHASE_25_RELIABILITY_SCORECARD.md", "PHASE_25_STRESS_TEST_REPORT.md"]},

        # --- follow-up (pronoun resolution using history) ---
        {"type": "follow-up", "history": [
            {"transcript": "Search the docs for the daily use matrix.", "response": "Found it."}],
         "question": "What recommendations does it make?",
         "expected": ["PHASE_24_DAILY_USE_MATRIX.md"]},
        {"type": "follow-up", "history": [
            {"transcript": "How does speech to text work?", "response": "faster-whisper is used."}],
         "question": "Which model does it use?",
         "expected": ["PHASE_24_5_PHYSICAL_VOICE_CERTIFICATION.md", "PHASE_30_5_FORENSIC_BASELINE.md"]},
        {"type": "follow-up", "history": [
            {"transcript": "Show me the phase 28 action audit.", "response": "Here you go."}],
         "question": "What was the overall score?",
         "expected": ["PHASE_28_5_ACTION_SCORECARD.md", "PHASE_28_5_ACTION_AUDIT.md"]},

        # --- negative (must be gated OUT → no-context path) ---
        {"type": "negative", "question": "What is the recipe for chocolate cake?"},
        {"type": "negative", "question": "Who won the 2022 world cup?"},
        {"type": "negative", "question": "Recommend a book about personal finance."},
    ]


def expected_docs(item: Dict) -> List[str]:
    return list(item.get("expected", []))


def is_negative(item: Dict) -> bool:
    return item.get("type") == "negative"


def is_followup(item: Dict) -> bool:
    return item.get("type") == "follow-up"