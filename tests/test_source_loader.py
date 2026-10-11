"""Тесты загрузки и извлечения источников без обращения к сети."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from source_loader import (
    MAX_RESPONSE_BYTES,
    SourceLoadError,
    extract_from_html,
    fetch_public_url,
    read_uploaded_text,
    resolve_public_addresses,
    source_from_manual_text,
    validate_url_destination,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_empty_manual_text():
    with pytest.raises(SourceLoadError):
        source_from_manual_text("")


def test_empty_html_extraction():
    result = extract_from_html("")
    assert result.main_text == ""
    assert any("Пустой" in w for w in result.warnings)


def test_html_extraction_local_fixture():
    html = (FIXTURES / "sample_article.html").read_text(encoding="utf-8")
    result = extract_from_html(html, base_url="https://example.com/articles/pilot-report")
    assert result.title == "Пилотный отчёт о выборке"
    assert result.author == "А. Исследователь"
    assert result.publication_date == "2024-05-10"
    assert result.publisher == "Учебный журнал данных"
    assert "120 человек" in result.main_text
    assert result.canonical_url == "https://example.com/articles/pilot-report"


def test_relative_reference_link_resolution():
    html = (FIXTURES / "sample_article.html").read_text(encoding="utf-8")
    result = extract_from_html(html, base_url="https://example.com/articles/pilot-report")
    assert "https://example.com/data/raw.csv" in result.reference_links
    assert "https://example.org/methods" in result.reference_links
    assert all(not link.endswith("#top") for link in result.reference_links)


def test_missing_metadata_not_invented():
    html = "<html><body><p>Только текст без метаданных.</p></body></html>"
    result = extract_from_html(html)
    assert result.author == ""
    assert result.publication_date == ""
    assert result.display(result.author) == "Не найдено"


def test_invalid_url_schemes():
    for url in ("ftp://example.com/a", "file:///etc/passwd", "javascript:alert(1)"):
        with pytest.raises(SourceLoadError):
            validate_url_destination(url)


def test_reject_credentials_in_url():
    with pytest.raises(SourceLoadError):
        validate_url_destination("https://user:pass@example.com/page")


def test_block_localhost_and_loopback():
    with pytest.raises(SourceLoadError):
        validate_url_destination("http://localhost/secret")
    with pytest.raises(SourceLoadError):
        resolve_public_addresses("127.0.0.1", 80)
    with pytest.raises(SourceLoadError):
        resolve_public_addresses("::1", 80)


def test_block_private_and_metadata_addresses():
    for host in ("10.0.0.5", "192.168.1.10", "172.16.0.2", "169.254.169.254"):
        with pytest.raises(SourceLoadError):
            resolve_public_addresses(host, 80)


def test_redirect_destination_validation():
    """Каждый редирект проходит валидацию; локальный Location отклоняется."""

    def fake_fetch(url: str, ip: str):
        if "start.example" in url:
            return 302, {"location": "http://127.0.0.1/admin"}, b"", url
        return 200, {"content-type": "text/html"}, b"<html><body><p>ok</p></body></html>", url

    with patch("source_loader.validate_url_destination") as mock_validate, patch(
        "source_loader._fetch_once", side_effect=fake_fetch
    ):
        mock_validate.side_effect = [
            ("https://start.example/page", ["203.0.113.10"]),
            SourceLoadError("Запрещены частные, локальные и служебные адреса."),
        ]
        with pytest.raises(SourceLoadError, match="частн|локальн|служебн"):
            fetch_public_url("https://start.example/page")


def test_response_size_limit_in_fetch():
    oversized = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + (
        b"x" * (MAX_RESPONSE_BYTES + 10)
    )

    class FakeSock:
        def __init__(self):
            self._data = oversized
            self._pos = 0

        def settimeout(self, *_args):
            return None

        def sendall(self, *_args):
            return None

        def recv(self, size):
            if self._pos >= len(self._data):
                return b""
            chunk = self._data[self._pos : self._pos + size]
            self._pos += size
            return chunk

        def close(self):
            return None

    with patch("source_loader.validate_url_destination") as mock_validate, patch(
        "source_loader.socket.create_connection", return_value=FakeSock()
    ):
        # HTTP, чтобы не требовался TLS-handshake в юнит-тесте.
        mock_validate.return_value = ("http://example.com/big", ["203.0.113.10"])
        with pytest.raises(SourceLoadError, match="2 МБ"):
            fetch_public_url("http://example.com/big")


def test_timeout_surfaces_as_source_load_error():
    with patch("source_loader.validate_url_destination") as mock_validate, patch(
        "source_loader._fetch_once", side_effect=TimeoutError("timed out")
    ):
        mock_validate.return_value = ("https://example.com/slow", ["203.0.113.10"])
        with pytest.raises(SourceLoadError, match="соединение"):
            fetch_public_url("https://example.com/slow")


def test_uploaded_file_size_and_encoding():
    with pytest.raises(SourceLoadError):
        read_uploaded_text(b"a" * (1 * 1024 * 1024 + 1))
    with pytest.raises(SourceLoadError):
        read_uploaded_text("текст".encode("cp1251"))
    assert "привет" in read_uploaded_text("привет".encode("utf-8"))
