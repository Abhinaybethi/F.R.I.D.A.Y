"""Persistent conversation, episodic, semantic and task memory.

Public surface:
    * :class:`MemoryConfig` — typed config from ``config.yaml.memory``
    * :class:`MemoryService` — facade used by the conversation loop and API

The legacy free-text ``memories`` table (voice ``remember``/``recall`` /
``forget``) is intentionally untouched and lives beside these additive tables.
"""
from friday.memory.config import MemoryConfig
from friday.memory.service import MemoryService

__all__ = ["MemoryConfig", "MemoryService"]
