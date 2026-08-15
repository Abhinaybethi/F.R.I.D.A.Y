import pytest
from unittest.mock import patch, MagicMock
from friday.tools.browser import read_website

def test_read_website_success():
    with patch('requests.get') as mock_get, \
         patch('socket.getaddrinfo', return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"<html><head><title>Test</title></head><body><h1>Hello World</h1><script>alert(1);</script><p>Some text.</p></body></html>"]
        mock_get.return_value = mock_response
        
        result = read_website("test", dry_run=False)
        assert result["success"] is True
        assert "Hello World Some text." in result["spoken_message"]
        assert "<script>" not in result["spoken_message"]

def test_read_website_dry_run():
    result = read_website("google", dry_run=True)
    assert result["success"] is True
    assert "[DRY RUN]" in result["message"]

def test_read_website_size_limit():
    with patch('requests.get') as mock_get, \
         patch('socket.getaddrinfo', return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        mock_response = MagicMock()
        # 3 MB of data
        mock_response.iter_content.return_value = [b"a" * (1024 * 1024)] * 3
        mock_get.return_value = mock_response
        
        result = read_website("test", dry_run=False)
        assert result["success"] is True
        # Since it truncates, it shouldn't crash
        # It's 'a' separated by spaces, limited to 2000 chars
        assert len(result["spoken_message"]) <= 2100 # "Here is the page content: " + 2000 chars + "..."
