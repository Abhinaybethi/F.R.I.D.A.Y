"""News feature tests: routing, fetching, and article follow-ups.

All network access is mocked so the suite stays offline.
"""
import datetime

import pytest

from friday.intent.models import Action
from friday.intent.router import route
from friday import news
from friday import news_skill


# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,target", [
    ("tell me latest news in india", "india"),
    ("what is the news today", ""),
    ("latest news", ""),
    ("what is happening in india", "india"),
    ("news in hindi", "hindi"),
    ("give me the news", ""),
    ("show me the news", ""),
    ("breaking news", ""),
    ("news briefing", ""),
])
def test_news_intents_route_to_news_summary(text, target):
    intent = route(text)
    assert intent.action == Action.NEWS_SUMMARY
    assert intent.target == target


def test_non_news_queries_do_not_route_to_news():
    assert route("open chrome").action != Action.NEWS_SUMMARY
    assert route("what time is it").action != Action.NEWS_SUMMARY


# ---------------------------------------------------------------------------
# Feed item cleanup
# ---------------------------------------------------------------------------

def test_make_item_strips_publisher_suffix():
    entry = {
        "title": "Big story today - The Hindu",
        "link": "https://example.com/a",
        "source": {"title": "The Hindu"},
        "published_parsed": (2026, 11, 4, 10, 0, 0, 0, 0, 0),
    }
    item = news._make_item(entry)
    assert item["title"] == "Big story today"
    assert item["source"] == "The Hindu"
    assert item["published"].startswith("2026-11-04")


def test_resolve_article_url_leaves_direct_links_alone():
    url = "https://www.thehindu.com/news/article1.ece"
    assert news.resolve_article_url(url) == url


# ---------------------------------------------------------------------------
# Fetch failures are reported on every call (cached failures keep the error)
# ---------------------------------------------------------------------------

def test_failed_fetch_is_reported_again_from_cache(monkeypatch):
    news._last_fetch.clear()
    monkeypatch.setattr(news, "_fetch_source", lambda *a, **k: ([], "network down"))

    first, first_err = news.get_headlines()
    second, second_err = news.get_headlines()

    assert first == [] and first_err == "network down"
    assert second == [] and second_err == "network down"


def test_fallback_source_used_when_primary_fails(monkeypatch):
    news._last_fetch.clear()

    def fake_fetch(url, timeout=15.0):
        if "google" in url:
            return [], "primary down"
        return [{"title": "Hindu story", "link": "https://thehindu.com/x",
                 "source": "The Hindu", "published": ""}], None

    monkeypatch.setattr(news, "_fetch_source", fake_fetch)
    items, err = news.get_headlines()

    assert err is None
    assert items and items[0]["title"] == "Hindu story"


def test_cache_respects_limit(monkeypatch):
    news._last_fetch.clear()

    def fake_fetch(url, timeout=15.0):
        return [{"title": f"story {i}", "link": "", "source": "News",
                 "published": ""} for i in range(8)], None

    monkeypatch.setattr(news, "_fetch_source", fake_fetch)
    items, err = news.get_headlines(limit=3)

    assert err is None
    assert len(items) == 3


# ---------------------------------------------------------------------------
# Prompt grounding
# ---------------------------------------------------------------------------

def test_prompt_contains_today_and_grounding_rules():
    prompt = news_skill._build_news_prompt(
        [{"title": "Headline one", "source": "BBC"}], "India"
    )
    today = datetime.datetime.now().strftime("%B %d, %Y")
    assert today in prompt
    assert "Headline one" in prompt
    assert "Use ONLY the headlines" in prompt


# ---------------------------------------------------------------------------
# Follow-up "number N"
# ---------------------------------------------------------------------------

def test_deep_dive_without_headlines_asks_for_news_first():
    news_skill.clear_last_headlines()
    assert "ask for news first" in news_skill.deep_dive(None, "1")


def test_deep_dive_by_number_uses_article_text(monkeypatch):
    news_skill.clear_last_headlines()
    news_skill._last_headlines = [
        {"title": "First story", "link": "https://example.com/1", "source": "BBC", "published": ""},
    ]
    long_text = "This is the article body. " * 40
    monkeypatch.setattr(news_skill, "get_article_text", lambda url: (long_text, None))

    reply = news_skill.deep_dive(None, "1")

    assert reply.startswith("This is the article body.")
    news_skill.clear_last_headlines()


def test_deep_dive_extraction_failure_falls_back_to_headline(monkeypatch):
    news_skill.clear_last_headlines()
    news_skill._last_headlines = [
        {"title": "First story", "link": "https://example.com/1", "source": "BBC", "published": ""},
    ]
    monkeypatch.setattr(news_skill, "get_article_text",
                        lambda url: (None, "paywall"))

    reply = news_skill.deep_dive(None, "1")

    assert "paywall" in reply
    assert "First story" in reply
    news_skill.clear_last_headlines()


def test_summarize_headlines_reports_fetch_error(monkeypatch):
    monkeypatch.setattr(news_skill, "get_headlines",
                        lambda limit=8, hindi=False: ([], "network down"))

    spoken, headlines = news_skill.summarize_headlines(None)

    assert "network down" in spoken
    assert headlines is None
