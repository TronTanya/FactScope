"""Тесты отчётов и экранирования."""

from __future__ import annotations

from reporting import export_evidence_csv, generate_html_report, is_safe_http_url, link_html


def _case():
    return {
        "id": 1,
        "claim": "<script>alert(1)</script> Утверждение",
        "context": "Контекст & проверка",
        "conclusion": "Недостаточно данных",
        "conclusion_explanation": "Мало данных",
        "is_demo": True,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-02T00:00:00+00:00",
        "source": {
            "title": "Источник <b>x</b>",
            "author": "",
            "publication_date": "",
            "canonical_url": "https://example.com/ok",
            "publisher": "Demo",
            "url": "javascript:alert(1)",
            "text": "Текст с <img src=x onerror=alert(1)>",
            "reference_links": ["https://example.com/a", "javascript:evil"],
            "retrieval_time": "2024-01-01T12:00:00+00:00",
            "input_method": "manual",
            "checklist": {
                "author_identified": "Нет",
                "publication_date_identified": "Нет",
                "reference_links_present": "Да",
                "original_document_linked": "Неизвестно",
                "publisher_identifiable": "Да",
                "independent_corroboration": "Неизвестно",
            },
            "indicators": [
                {
                    "fragment": "срочно распространите",
                    "category": "Призыв",
                    "explanation": "тест <tag>",
                }
            ],
        },
        "evidence": [
            {
                "source_title": "A",
                "reference": "https://example.com/evidence",
                "excerpt": "фрагмент <script>",
                "relationship": "Поддерживает",
                "explanation": "пояснение",
                "source_family": "family",
            },
            {
                "source_title": "B",
                "reference": "javascript:alert(2)",
                "excerpt": "другое",
                "relationship": "Противоречит",
                "explanation": "нет",
                "source_family": "",
            },
        ],
    }


def test_html_escaping():
    html = generate_html_report(_case())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img" in html
    assert "тест &lt;tag&gt;" in html


def test_safe_report_links():
    assert is_safe_http_url("https://example.com/a")
    assert is_safe_http_url("http://example.com/a")
    assert not is_safe_http_url("javascript:alert(1)")
    assert not is_safe_http_url("ftp://example.com/a")
    assert not is_safe_http_url("https://user:pass@example.com/")

    html = generate_html_report(_case())
    assert 'href="https://example.com/ok"' in html
    assert 'href="https://example.com/evidence"' in html
    assert 'href="javascript:alert(1)"' not in html
    assert 'href="javascript:alert(2)"' not in html
    assert 'href="javascript:evil"' not in html

    assert 'href="https://example.com/x"' in link_html("https://example.com/x", "метка")
    unsafe = link_html("javascript:alert(1)")
    assert "<a " not in unsafe
    assert "href=" not in unsafe


def test_csv_export_utf8_bom():
    data = export_evidence_csv(
        [
            {
                "source_title": "Источник",
                "reference": "https://example.com",
                "excerpt": "фрагмент",
                "relationship": "Поддерживает",
                "explanation": "пояснение",
                "source_family": "семья",
            }
        ]
    )
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "Источник" in text
    assert "Поддерживает" in text
