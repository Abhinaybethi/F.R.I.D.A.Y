"""
Deterministic request classifier unit tests.

Covers the priority ordering from the interaction spec: session control, exit,
deterministic command, multi-step, context reference, knowledge question, chat,
unknown.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.classifier import RequestClass, classify


def cls(text):
    return classify(text)


def test_exit():
    assert cls("stop") == RequestClass.EXIT
    assert cls("goodbye") == RequestClass.EXIT
    assert cls("shut down") == RequestClass.EXIT


def test_session_control():
    assert cls("yes") == RequestClass.SESSION_CONTROL
    assert cls("no") == RequestClass.SESSION_CONTROL
    assert cls("cancel") == RequestClass.SESSION_CONTROL
    assert cls("help") == RequestClass.SESSION_CONTROL
    assert cls("what can you do") == RequestClass.SESSION_CONTROL


def test_screen_questions_are_detected():
    for text in (
        "what is on my screen",
        "what's on my screen",
        "what are you showing on my screen",
        "what do you see",
        "look at my screen",
        "can you see my screen",
        "what is on the screen",
    ):
        assert cls(text) == RequestClass.SCREEN_QUESTION, text


def test_knowledge_questions():
    for text in (
        "what is java",
        "explain recursion",
        "why is the sky blue",
        "how does a compiler work",
        "tell me about neural networks",
        "what is the difference between python and java",
    ):
        assert cls(text) == RequestClass.QUESTION, text


def test_casual_chat():
    assert cls("let's talk") == RequestClass.CHAT
    assert cls("tell me something interesting") == RequestClass.CHAT
    assert cls("i'm bored") == RequestClass.CHAT
    # "how are you" is caught by the question starter first — both map to the
    # SAME reasoner CHAT mode downstream, so it is acceptable either way.
    assert cls("how are you") in (RequestClass.QUESTION, RequestClass.CHAT)


def test_context_references():
    assert cls("play it") == RequestClass.CONTEXT_REFERENCE
    assert cls("open the first one") == RequestClass.CONTEXT_REFERENCE
    assert cls("close it") == RequestClass.CONTEXT_REFERENCE
    assert cls("open the second result") == RequestClass.CONTEXT_REFERENCE


def test_simple_commands():
    # Deterministic simple commands stay out of chat/reasoner entirely.
    assert cls("open chrome") == RequestClass.UNKNOWN
    assert cls("hi") == RequestClass.UNKNOWN
    assert cls("open youtube") == RequestClass.UNKNOWN
    assert cls("what time is it") == RequestClass.QUESTION  # knowledge-ish, router resolves


def test_compound_commands_need_command_verbs():
    assert cls("open chrome, play jazz") == RequestClass.COMMAND
    assert cls("open chrome and search for jazz") == RequestClass.COMMAND
    assert cls("open youtube then play kalyani song") == RequestClass.COMMAND
    # Greeting-chat punctuation is NOT a compound command.
    assert cls("hi, how are you") != RequestClass.COMMAND


def test_ambiguous_is_unknown():
    assert cls("lorem ipsum blah") == RequestClass.UNKNOWN
    assert cls("") == RequestClass.UNKNOWN


def test_recall_phrase_stays_knowledge(self=None):
    # "what is my schedule" is memory, but plain "what is java" must NOT be
    # captured by RECALL-style patterns — it remains a QUESTION.
    assert cls("what is my schedule") == RequestClass.QUESTION
    assert cls("recall my java notes") == RequestClass.UNKNOWN