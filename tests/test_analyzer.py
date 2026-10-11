"""Тесты индикаторов и чек-листа."""

from __future__ import annotations

from analyzer import (
    analyze_text_indicators,
    build_checklist_from_source,
    find_phrase_indicators,
    find_style_indicators,
    validate_conclusion,
)


def test_empty_input_indicators():
    assert analyze_text_indicators("") == []
    assert find_phrase_indicators("") == []
    assert find_style_indicators("") == []


def test_russian_phrase_boundaries():
    text = "Это шокирующая правда дня, но не шокирующаяправдавместе."
    findings = find_phrase_indicators(
        text,
        [
            {
                "phrase": "шокирующая правда",
                "category": "Привлечение внимания",
                "explanation": "тест",
            }
        ],
    )
    assert len(findings) == 1
    assert findings[0].fragment.lower() == "шокирующая правда"
    assert findings[0].start >= 0
    assert text[findings[0].start : findings[0].end].lower() == "шокирующая правда"


def test_no_duplicate_overlapping_findings():
    text = "срочно распространите срочно распространите"
    findings = analyze_text_indicators(
        text,
        [
            {
                "phrase": "срочно распространите",
                "category": "Призыв",
                "explanation": "тест",
            }
        ],
    )
    assert len(findings) == 2
    spans = {(f.start, f.end) for f in findings}
    assert len(spans) == 2


def test_repeated_exclamation_marks():
    text = "Читайте немедленно!!!"
    findings = find_style_indicators(text)
    assert any(f.category == "Повтор восклицательных знаков" for f in findings)
    hit = next(f for f in findings if f.category == "Повтор восклицательных знаков")
    assert hit.fragment == "!!!"


def test_fully_capitalized_phrase():
    text = "ЭТО РЕВОЛЮЦИЯ В ИЗМЕРЕНИЯХ и обычный текст"
    findings = find_style_indicators(text)
    assert any(f.category == "Фраза в верхнем регистре" for f in findings)


def test_checklist_missing_metadata():
    result = build_checklist_from_source(
        author="",
        publication_date="",
        reference_links=[],
        publisher="",
    )
    assert result.items["author_identified"] == "Нет"
    assert result.items["publication_date_identified"] == "Нет"
    assert result.items["reference_links_present"] == "Нет"
    assert result.items["original_document_linked"] == "Неизвестно"
    assert result.items["independent_corroboration"] == "Неизвестно"
    assert result.unknown_count >= 2


def test_checklist_autofill_from_metadata():
    result = build_checklist_from_source(
        author="Иванов",
        publication_date="2024-01-01",
        reference_links=["https://example.com/a"],
        publisher="Журнал",
    )
    assert result.items["author_identified"] == "Да"
    assert result.items["publication_date_identified"] == "Да"
    assert result.items["reference_links_present"] == "Да"
    assert result.items["publisher_identifiable"] == "Да"


def test_conclusion_validation_requires_evidence_and_explanation():
    errors = validate_conclusion(
        "Подтверждено собранными источниками",
        "",
        0,
    )
    assert any("доказательств" in e.lower() for e in errors)
    assert any("пояснен" in e.lower() for e in errors)

    ok = validate_conclusion(
        "Подтверждено собранными источниками",
        "Есть прямая цитата из отчёта.",
        1,
    )
    assert ok == []

    unchecked = validate_conclusion("Не проверено", "", 0)
    assert unchecked == []
