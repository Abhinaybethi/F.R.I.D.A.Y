"""
Shared logger setup used across all of Friday's modules.
Logs to both the console and a rotating-friendly log file.
"""
import logging
import os


def get_logger(name: str, log_file: str = "logs/friday.log", level: str = "INFO") -> logging.Logger:
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured, avoid duplicate handlers

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
