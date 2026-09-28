"""
Shared logger setup used across all of Friday's modules.
Logs to both the console and a bounded rotating log file.

Windows rotation fix (WinError 32)
----------------------------------
Earlier versions created a *separate* ``RotatingFileHandler`` for every
distinct logger name, all pointing at the same ``logs/friday.log``.  Windows
cannot ``os.rename()`` a file while another open handle still references it,
so the first handler that hit ``maxBytes`` failed inside
``rotate() -> os.rename()`` with::

    PermissionError: [WinError 32] friday.log -> friday.log.1

This module now:
  * shares ONE file handler per canonical log path (single file handle, single
    rotation lock, no duplicate handlers);
  * degrades gracefully when rotation must be deferred (file temporarily held
    by another process) instead of spewing ``--- Logging error ---``
    tracebacks, logging a rate-limited single-line notice instead;
  * keeps the exact same log format and per-record request/session IDs.
"""
import contextvars
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

request_id_var = contextvars.ContextVar("request_id", default="-")


class RequestIDFilter(logging.Filter):
    """Attach the current per-request/session ID to every log record."""

    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


_FORMAT_STRING = "%(asctime)s | %(name)s | %(levelname)s | [%(request_id)s] | %(message)s"

# One stateless formatter + one filter shared by every handler.
_SHARED_FORMATTER = logging.Formatter(_FORMAT_STRING)
_SHARED_REQUEST_FILTER = RequestIDFilter()

# Shared handlers: canonical(abs path) -> file handler. All loggers targeting
# the same file attach the SAME handler object, so there is exactly one open
# file handle per log path and one rotation lock.
_FILE_HANDLER_REGISTRY: dict[str, "WindowsSafeRotatingFileHandler"] = {}
_REGISTRY_LOCK = threading.Lock()

# Single shared console handler (writes to stderr). No duplicate stream
# handlers per logger, no per-logger file handles fighting over one file.
_CONSOLE_HANDLER: "logging.StreamHandler" = None


class WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """
    ``RotatingFileHandler`` that never lets a Windows file-in-use error bring
    down logging.

    On any ``OSError`` during rollover the handler keeps the current stream
    open (reopening it on the base file if the failed rollover closed it) so
    logging continues uninterrupted, and prints ONE rate-limited, single-line
    notice instead of the default multi-line ``--- Logging error ---``
    traceback.  The next size-triggered rollover retries naturally.
    """

    _NOTICE_INTERVAL_SECONDS = 60.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_rotation_error_at = 0.0
        self._rotation_errors = 0

    def doRollover(self):
        try:
            super().doRollover()
        except OSError as exc:
            # Windows: another handle still references the log file. Keep
            # writing to the current file; retry on the next rollover window.
            self._rotation_errors += 1
            if self.stream is None:
                try:
                    self.stream = self._open()
                except OSError:
                    self.stream = None
            now = time.monotonic()
            if now - self._last_rotation_error_at >= self._NOTICE_INTERVAL_SECONDS:
                self._last_rotation_error_at = now
                try:
                    sys.stderr.write(
                        "[LOG] Rotation deferred (%s): %s\n"
                        % (type(exc).__name__, exc)
                    )
                except Exception:
                    pass


def _canonical_key(log_file: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(log_file)))


def _get_shared_file_handler(log_file: str) -> WindowsSafeRotatingFileHandler:
    log_dir = os.path.dirname(log_file)
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            pass
    key = _canonical_key(log_file)
    with _REGISTRY_LOCK:
        handler = _FILE_HANDLER_REGISTRY.get(key)
        if handler is None:
            handler = WindowsSafeRotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(_SHARED_FORMATTER)
            handler.addFilter(_SHARED_REQUEST_FILTER)
            _FILE_HANDLER_REGISTRY[key] = handler
        return handler


def _get_shared_console_handler() -> logging.StreamHandler:
    global _CONSOLE_HANDLER
    with _REGISTRY_LOCK:
        if _CONSOLE_HANDLER is None:
            handler = logging.StreamHandler()
            handler.setFormatter(_SHARED_FORMATTER)
            handler.addFilter(_SHARED_REQUEST_FILTER)
            _CONSOLE_HANDLER = handler
        return _CONSOLE_HANDLER


def close_logging() -> None:
    """
    Close every shared file handler. Call once during shutdown (idempotent) so
    log files are flushed and released cleanly on Windows.
    """
    with _REGISTRY_LOCK:
        for key, handler in list(_FILE_HANDLER_REGISTRY.items()):
            try:
                handler.close()
            except Exception:
                pass
            _FILE_HANDLER_REGISTRY.pop(key, None)


def get_logger(name: str, log_file: str = "logs/friday.log", level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured, avoid duplicate handlers

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False  # prevent duplicate logs via parent logger propagation

    file_handler = _get_shared_file_handler(log_file)
    console_handler = _get_shared_console_handler()

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger