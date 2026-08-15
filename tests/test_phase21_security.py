"""
Phase 21 Security Test Suite.

Verifies:
1. SSRF prevention in read_website (loopback, private IPv4/IPv6, schemes, DNS resolution, redirect checks).
2. Path traversal prevention in find_file and open_file (traversal sequences, UNC, drive letters, encoded traversal, safe directory bounds).
"""
import pytest
from unittest.mock import patch, MagicMock
from friday.tools.browser import read_website, _validate_url_security
from friday.tools.files import find_file, open_file


class TestSSRFHardening:
    @pytest.mark.parametrize("target", [
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8080",
        "http://[::1]",
        "http://10.0.0.1",
        "http://192.168.1.1",
        "http://172.16.0.1",
        "http://169.254.169.254",
        "file:///etc/passwd",
        "ftp://example.com/file.txt",
        "data:text/plain;base64,SGVsbG8=",
        "javascript:alert(1)",
        "http://something.local",
        "http://service.internal",
    ])
    def test_ssrf_blocked_targets(self, target):
        res = read_website(target, dry_run=True)
        assert res["success"] is False
        assert "Blocked" in res["message"] or "Security" in res["spoken_message"] or "forbidden" in res["message"].lower()

    def test_hostname_resolving_to_private_ip(self):
        # Mock getaddrinfo to return a private IP for a public-looking hostname
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("192.168.1.50", 80))]
            is_safe, reason = _validate_url_security("http://malicious-internal.com")
            assert is_safe is False
            assert "private" in reason.lower()

    def test_dns_resolution_failure(self):
        import socket
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.side_effect = socket.gaierror("Name or service not known")
            is_safe, reason = _validate_url_security("http://nonexistent-domain-xyz123.com")
            assert is_safe is False
            assert "failed" in reason.lower()

    def test_redirect_from_public_to_private_blocked(self):
        with patch("friday.tools.browser._validate_url_security") as mock_val, \
             patch("requests.Session") as mock_sess_cls:
            # First call for initial URL -> safe, second call for redirect location -> unsafe
            mock_val.side_effect = [(True, ""), (False, "Redirected to private IP 10.0.0.1")]
            
            mock_sess = MagicMock()
            mock_resp = MagicMock()
            mock_resp.is_redirect = True
            mock_resp.status_code = 302
            mock_resp.headers = {"Location": "http://10.0.0.1/admin"}
            mock_sess.get.return_value = mock_resp
            mock_sess_cls.return_value = mock_sess

            res = read_website("http://public-site.com", dry_run=False)
            assert res["success"] is False
            assert "Blocked" in res["message"] or "security" in res["message"].lower()


class TestPathTraversalHardening:
    @pytest.mark.parametrize("payload", [
        "../secret.txt",
        "..\\secret.txt",
        "../../../../etc/passwd",
        "..\\..\\..\\Windows\\System32\\config",
        "\\\\server\\share\\file.txt",
        "//server/share/file.txt",
        "C:\\Windows\\System32\\cmd.exe",
        "D:\\data.txt",
        "/etc/shadow",
        "mixed/../traversal",
        "%2e%2e%2fsecret.txt",
        "....//....//secret.txt",
    ])
    def test_find_file_traversal_blocked(self, payload):
        res = find_file(payload)
        assert res["success"] is False
        assert res["candidates"] == []
        assert "blocked" in res["message"].lower() or "traversal" in res["message"].lower()

    @pytest.mark.parametrize("payload", [
        "../secret.txt",
        "..\\secret.txt",
        "\\\\server\\share\\file.txt",
        "C:\\Windows\\System32\\cmd.exe",
        "%2e%2e%2fsecret.txt",
    ])
    def test_open_file_traversal_blocked(self, payload):
        res = open_file(payload, dry_run=True)
        assert res["success"] is False
        assert "blocked" in res["message"].lower() or "outside" in res["message"].lower()
