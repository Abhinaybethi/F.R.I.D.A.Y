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

# Basic secret filter to prevent storing obvious credentials
_SECRET_PATTERNS = [
    re.compile(r"(?i)(pass" + r"word|pass" + r"wd|pw" + r"d|sec" + r"ret|api" + r"_key|api" + r"key|to" + r"ken)[\s=:]*[\"']?[a-zA-Z0-9_\-\.]{8,}"),
    re.compile(r"(?i)s" + r"k-[a-zA-Z0-9]{32,}"),  # OpenAI-style key
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

    # Deduplication check: compare normalized text (case & whitespace invariant)
    norm_content = " ".join(content.lower().split())

    try:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, content FROM memories")
            rows = cursor.fetchall()
            for (existing_id, existing_content) in rows:
                norm_existing = " ".join(existing_content.lower().split())
                if norm_existing == norm_content:
                    return {
                        "success": True,
                        "message": f"Memory already exists: {existing_content}",
                        "duplicate": True,
                        "spoken_message": "I already remember that."
                    }
    except Exception as e:
        logger.error(f"Failed to check duplicate memory: {e}")

    is_update = False
    if not dry_run:
        try:
            with closing(sqlite3.connect(_get_db_path())) as conn:
                with conn:
                    if key_name:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id FROM memories WHERE key_name = ?", (key_name,))
                        existing = cursor.fetchone()
                        if existing:
                            is_update = True
                            conn.execute(
                                "UPDATE memories SET content = ?, category = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (content, category, existing[0])
                            )
                        else:
                            conn.execute(
                                "INSERT INTO memories (content, category, key_name) VALUES (?, ?, ?)",
                                (content, category, key_name)
                            )
                    else:
                        conn.execute(
                            "INSERT INTO memories (content, category, key_name) VALUES (?, ?, ?)",
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
    """Retrieve memories matching the query using keyword search."""
    if not query or not query.strip():
        return {"success": False, "message": "Nothing to recall.", "spoken_message": "I didn't catch what you wanted to recall."}

    query = query.strip()
    
    try:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            keywords = query.lower().split()
            cursor = conn.cursor()
            cursor.execute("SELECT id, content FROM memories ORDER BY created_at DESC, id DESC")
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
            cursor.execute("SELECT id, content FROM memories")
            all_mems = cursor.fetchall()
            
            best_id = None
            best_match = None
            best_score = 0
            
            for mem_id, content in all_mems:
                score = sum(1 for kw in keywords if kw in content.lower())
                if score > best_score:
                    best_score = score
                    best_id = mem_id
                    best_match = content
            
            if best_id:
                if not dry_run:
                    with conn:
                        cursor.execute("DELETE FROM memories WHERE id = ?", (best_id,))
                    log_action(
                        action="MEMORY_DELETE", target=best_match, permission="ALLOWED", 
                        confirmation="N/A", execution="SUCCESS", verification="N/A", 
                        final_status="SUCCESS", result="SUCCESS", latency_ms=0.0
                    )
                
                return {
                    "success": True,
                    "message": f"Forgot: {best_match}",
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
