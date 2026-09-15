"""
YouTube playback truthfulness unit tests.

Verifies play_youtube NEVER claims a video is playing unless a real watch link
was resolved and opened; otherwise it truthfully opens the search results page.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest import mock

from friday.tools.browser import play_youtube, _resolve_youtube_watch

_HTML_WITH_VIDEO = (
    '"videoId":"aBcD12eFgHi"'
    ',"title":{"runs":[{"text":"Despacito"}]'
)


class _Resp:
    status = 200

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload.encode()


class _E:
    def __call__(self, *a, **k):
        raise OSError("network down")


def _patch(urlopen_side_effect=lambda *a, **k: _Resp(_HTML_WITH_VIDEO)):
    return mock.patch(
        "friday.tools.browser.urllib.request.urlopen",
        side_effect=urlopen_side_effect,
    )


def test_dry_run_never_claims_playback():
    result = play_youtube("kalyani song", dry_run=True)
    assert result["success"]
    assert "youtube.com/results" in result["url"]
    assert "playing" not in result["spoken_message"].lower()
    assert "dry_run" in result


def test_unresolvable_opens_search_truthfully():
    with _patch(_E()), mock.patch("friday.tools.browser.webbrowser.open") as mock_open:
        result = play_youtube("despacito", dry_run=False)
    mock_open.assert_called_once()
    assert result["success"]
    assert result["watch_resolved"] is False
    assert "youtube.com/results" in result["url"]
    assert "couldn't verify" in result["spoken_message"].lower()
    assert "playing" not in result["spoken_message"].lower()


def test_resolvable_opens_watch_link_without_claiming_autoplay_done():
    with _patch(), mock.patch("friday.tools.browser.webbrowser.open") as mock_open:
        result = play_youtube("despacito", dry_run=False)
    mock_open.assert_called_once_with("https://www.youtube.com/watch?v=aBcD12eFgHi")
    assert result["success"]
    assert result["watch_resolved"] is True
    assert result["watch_url"] == "https://www.youtube.com/watch?v=aBcD12eFgHi"
    # Truthful: says it found/opened the video, never claims audio verified.
    assert "Found the video" in result["spoken_message"]
    assert "playing" not in result["spoken_message"].lower()


def test_resolver_extracts_watch_url_and_title():
    with _patch():
        url, title = _resolve_youtube_watch("despacito")
    assert url == "https://www.youtube.com/watch?v=aBcD12eFgHi"
    assert title == "Despacito"


def test_resolver_returns_empty_on_failure():
    with _patch(_E()):
        url, title = _resolve_youtube_watch("despacito")
    assert url == ""
    assert title == ""


def test_empty_query_fails():
    assert play_youtube("", dry_run=True)["success"] is False