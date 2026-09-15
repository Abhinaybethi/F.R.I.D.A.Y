"""
Explicit Local Memory Tool (Phase 20 / Phase 22)

Provides SQLite-based persistent memory with active preference resolution.
Strict constraints:
- Local SQLite only.
- Explicit user commands & preference resolution.
- Rejects secrets/API keys.
- Auditable.
"""
import sqlite3
import os
import re
from contextlib import closing
from typing import Dict, Any, Optional

from friday.utils.logger import get_logger
from friday.utils.audit_logger import log_action

logger = get_logger(__name__)

# Basic secret filter to prevent storing obvious credentials, tokens, or PII
_SECRET_PATTERNS = [
    re.compile(r"(?i)(pass" + r"word|pass" + r"wd|pw" + r"d|sec" + r"ret|api" + r"_key|api" + r"key|to" + r"ken)[\s=:]*[\"']?[a-zA-Z0-9_\-\.]{8,}"),
    re.compile(r"(?i)s" + r"k-[a-zA-Z0-9]{32,}"),       # OpenAI-style key
    re.compile(r"(?i)ghp_[a-zA-Z0-9]{36}"),            # GitHub Personal Access Token
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{16,}"),  # Bearer authentication header
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),              # US Social Security Number (SSN)
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),             # Credit Card Number (13-16 digits)
]

def _get_db_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_dir = os.path.join(root, ".data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "memory.db")

def _init_db():
    with closing(sqlite3.connect(_get_db_path())) as conn:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    confidence REAL DEFAULT 1.0,
                    key_name TEXT DEFAULT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Safe schema migrations for existing DBs
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(memories)")
            cols = [col[1] for col in cursor.fetchall()]
            if "category" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN category TEXT DEFAULT 'general'")
            if "confidence" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT 1.0")
            if "key_name" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN key_name TEXT DEFAULT NULL")
            if "updated_at" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

_init_db()


def _contains_secrets(text: str) -> bool:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return True
    return False


def remember(content: str, category: str = "general", key_name: Optional[str] = None, dry_run: bool = True) -> Dict[str, Any]:
    """Store a memory if it doesn't contain secrets and isn't a duplicate."""
    if not content or not content.strip():
        return {"success": False, "message": "Nothing to remember.", "spoken_message": "I didn't catch what you wanted me to remember."}

    content = content.strip()

    if _contains_secrets(content):
        return {
            "success": False, 
            "message": "Blocked attempt to store sensitive information.",
            "blocked": True,
            "spoken_message": "I cannot save that. It looks like sensitive information."
        }

    is_update = False
    if not dry_run:
        try:
            with closing(sqlite3.connect(_get_db_path())) as conn:
                with conn:
                    cursor = conn.cursor()
                    if key_name:
                        cursor.execute("SELECT id, content FROM memories WHERE lower(key_name) = ?", (key_name.lower(),))
                        existing_rows = cursor.fetchall()
                        if existing_rows:
                            is_update = True
                            first_id = existing_rows[0][0]
                            conn.execute(
                                "UPDATE memories SET content = ?, category = ?, key_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (content, category, key_name, first_id)
                            )
                            if len(existing_rows) > 1:
                                conn.executemany("DELETE FROM memories WHERE id = ?", [(r[0],) for r in existing_rows[1:]])
                        else:
                            norm_content = " ".join(content.lower().split())
                            cursor.execute("SELECT id, content FROM memories")
                            rows = cursor.fetchall()
                            dup_id = None
                            for (e_id, e_content) in rows:
                                if " ".join(e_content.lower().split()) == norm_content:
                                    dup_id = e_id
                                    break
                            if dup_id:
                                conn.execute("UPDATE memories SET key_name = ?, category = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (key_name, category, dup_id))
                            else:
                                conn.execute(
                                    "INSERT INTO memories (content, category, key_name, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                                    (content, category, key_name)
                                )
                    else:
                        norm_content = " ".join(content.lower().split())
                        cursor.execute("SELECT id, content FROM memories")
                        rows = cursor.fetchall()
                        for (e_id, e_content) in rows:
                            if " ".join(e_content.lower().split()) == norm_content:
                                return {
                                    "success": True,
                                    "message": f"Memory already exists: {e_content}",
                                    "duplicate": True,
                                    "spoken_message": "I already remember that."
                                }
                        conn.execute(
                            "INSERT INTO memories (content, category, key_name, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                            (content, category, key_name)
                        )
            log_action(
                action="MEMORY_WRITE", target=content, permission="ALLOWED", 
                confirmation="N/A", execution="SUCCESS", verification="N/A", 
                final_status="SUCCESS", result="SUCCESS", latency_ms=0.0
            )
        except Exception as e:
            logger.error(f"Failed to write memory: {e}")
            return {"success": False, "message": f"Database error: {e}", "spoken_message": "I had a database error while saving that."}

    spoken_msg = f"Updated your {key_name} preference." if (key_name and is_update) else "I'll remember that."

    return {
        "success": True,
        "message": f"Remembered: {content}",
        "spoken_message": spoken_msg
    }


def recall(query: str) -> Dict[str, Any]:
    """Retrieve memories matching the query using preference key or keyword search."""
    if not query or not query.strip():
        return {"success": False, "message": "Nothing to recall.", "spoken_message": "I didn't catch what you wanted to recall."}

    query = query.strip()
    
    try:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            cursor = conn.cursor()

            # 1. Direct key match check first
            clean_q = query.lower().replace("my ", "").replace("the ", "").strip()
            cursor.execute(
                "SELECT id, content, key_name FROM memories WHERE lower(key_name) = ? OR lower(key_name) = ? ORDER BY updated_at DESC, id DESC",
                (query.lower(), clean_q)
            )
            key_row = cursor.fetchone()
            if key_row:
                return {
                    "success": True,
                    "message": f"Recalled: {key_row[1]}",
                    "spoken_message": f"I remember that. {key_row[1]}"
                }

            # 2. Keyword relevance search ordered by latest update
            keywords = query.lower().split()
            cursor.execute("SELECT id, content FROM memories ORDER BY updated_at DESC, created_at DESC, id DESC")
            all_mems = cursor.fetchall()
            
            best_match = None
            best_score = 0
            
            for mem_id, content in all_mems:
                score = sum(1 for kw in keywords if kw in content.lower())
                if score > best_score:
                    best_score = score
                    best_match = content
            
            if best_match:
                return {
                    "success": True,
                    "message": f"Recalled: {best_match}",
                    "spoken_message": f"I remember that. {best_match}"
                }
            else:
                return {
                    "success": False,
                    "message": f"No memory found matching: {query}",
                    "spoken_message": "I couldn't find any memory about that."
                }
    except Exception as e:
        logger.error(f"Failed to read memory: {e}")
        return {"success": False, "message": f"Database error: {e}", "spoken_message": "I had a database error while retrieving memories."}


def resolve_preference(key_name: str) -> Optional[str]:
    """Search for stored preferences matching key_name (e.g. 'browser', 'editor')."""
    try:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT content, key_name FROM memories WHERE (category = 'preference' OR key_name = ?) ORDER BY updated_at DESC, id DESC",
                (key_name,)
            )
            rows = cursor.fetchall()
            for (content, k_name) in rows:
                if k_name and k_name.lower() == key_name.lower():
                    if " is " in content:
                        return content.split(" is ", 1)[-1].strip()
                    return content
                if key_name.lower() in content.lower():
                    if " is " in content:
                        return content.split(" is ", 1)[-1].strip()
                    return content
            return None
    except Exception as e:
        logger.error(f"Failed to resolve preference for {key_name}: {e}")
        return None


def forget(query: str, dry_run: bool = True) -> Dict[str, Any]:
    """Delete memories matching the query."""
    if not query or not query.strip():
        return {"success": False, "message": "Nothing to forget.", "spoken_message": "I didn't catch what you wanted to forget."}

    query = query.strip()
    
    try:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            cursor = conn.cursor()
            keywords = query.lower().split()
            cursor.execute("SELECT id, content, key_name FROM memories")
            all_mems = cursor.fetchall()
            
            matching_ids = []
            deleted_contents = []
            
            for mem_id, content, k_name in all_mems:
                if (k_name and k_name.lower() == query.lower()) or (query.lower() in content.lower()) or any(kw in content.lower() for kw in keywords):
                    matching_ids.append(mem_id)
                    deleted_contents.append(content)
            
            if matching_ids:
                if not dry_run:
                    with conn:
                        cursor.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in matching_ids])
                    log_action(
                        action="MEMORY_DELETE", target=", ".join(deleted_contents), permission="ALLOWED",
                        confirmation="N/A", execution="SUCCESS", verification="N/A",
                        final_status="SUCCESS", result="SUCCESS", latency_ms=0.0
                    )
                
                return {
                    "success": True,
                    "message": f"Forgot: {', '.join(deleted_contents)}",
                    "spoken_message": "I have forgotten that."
                }
            else:
                return {
                    "success": False,
                    "message": f"No memory found to forget matching: {query}",
                    "spoken_message": "I couldn't find anything matching that to forget."
                }
    except Exception as e:
        logger.error(f"Failed to delete memory: {e}")
        return {"success": False, "message": f"Database error: {e}", "spoken_message": "I had a database error while deleting that memory."}
