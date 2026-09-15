"""Pytest shared fixtures.

Prevents any test from accidentally spawning a real llama.cpp server process
or performing real subprocess launches. Individual tests opt into real
execution explicitly via mocks / environment overrides.
"""
import os

os.environ.setdefault("FRIDAY_SKIP_LLAMACPP_STARTUP", "1")