"""Анализ прозрачности источника и текстовых индикаторов."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

CHECKLIST_KEYS = [
    ("author_identified", "Указан ли автор?"),
    ("publication_date_identified", "Указана ли дата публикации?"),
    ("reference_links_present", "Есть ли ссылки на источники?"),
    ("original_document_linked", "Есть ли ссылка на исходный документ или набор данных?"),
    ("publisher_identifiable", "Можно ли определить издателя?"),
    ("independent_corroboration", "Есть ли независимые подтверждения утверждения?"),
]

CHECKLIST_VALUES = ("Да", "Нет", "Неизвестно")

TRANSPARENCY_NOTE = (
    "Прозрачность источника помогает проверке, но сама по себе не доказывает "
    "достоверность утверждения."
)

INDICATORS_NOTE = (
    "Такие выражения могут привлекать внимание. Их наличие не доказывает, "
    "что текст ложный."
)

CONCLUSION_OPTIONS = (
    "Не проверено",
    "Недостаточно данных",
    "Подтверждено собранными источниками",
    "Опровергнуто собранными источниками",
    "Частично подтверждено",
)

CONCLUSIONS_REQUIRING_EVIDENCE = {
    "Подтверждено собранными источниками",
    "Опровергнуто собранными источниками",
    "Частично подтверждено",
}

RELATIONSHIP_OPTIONS = ("Поддерживает", "Противоречит", "Даёт контекст")

_CONTENT_DIR = Path(__file__).resolve().parent / "content"
_WORD_CHAR = r"0-9A-Za-zА-Яа-яЁё"


@dataclass
class IndicatorFinding:
    fragment: str
    category: str
    explanation: str
    start: int
    end: int


@dataclass
class ChecklistResult:
    items: dict[str, str] = field(default_factory=dict)
    known_count: int = 0
    unknown_count: int = 0
    note: str = TRANSPARENCY_NOTE

    def as_display_rows(self) -> list[tuple[str, str]]:
        return [(label, self.items.get(key, "Неизвестно")) for key, label in CHECKLIST_KEYS]


def load_indicators(path: Optional[Path] = None) -> list[dict[str, str]]:
    indicators_path = path or (_CONTENT_DIR / "indicators.json")
    with indicators_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("indicators.json должен содержать список.")
    return data


def _boundary_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase)
    return re.compile(
        rf"(?<![{_WORD_CHAR}]){escaped}(?![{_WORD_CHAR}])",
        flags=re.IGNORECASE,
    )


def find_phrase_indicators(
    text: str, phrases: Optional[list[dict[str, str]]] = None
) -> list[IndicatorFinding]:
    if not text:
        return []
    catalog = phrases if phrases is not None else load_indicators()
    findings: list[IndicatorFinding] = []
    occupied: list[tuple[int, int]] = []

    # Более длинные фразы раньше — меньше дубликатов.
    ordered = sorted(catalog, key=lambda item: len(item.get("phrase", "")), reverse=True)
    for item in ordered:
        phrase = (item.get("phrase") or "").strip()
        if not phrase:
            continue
        pattern = _boundary_pattern(phrase)
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            if any(not (end <= a or start >= b) for a, b in occupied):
                continue
            occupied.append((start, end))
            findings.append(
                IndicatorFinding(
                    fragment=text[start:end],
                    category=item.get("category", "Индикатор"),
                    explanation=item.get(
                        "explanation",
                        "Выражение может привлекать внимание.",
                    ),
                    start=start,
                    end=end,
                )
            )
    findings.sort(key=lambda f: f.start)
    return findings


_EXCLAMATION_RUN = re.compile(r"!{3,}")
_CAPS_PHRASE = re.compile(
    rf"(?<![{_WORD_CHAR}])([A-ZА-ЯЁ]{{4,}}(?:\s+[A-ZА-ЯЁ]{{3,}}){{0,6}})(?![{_WORD_CHAR}])"
)


def find_style_indicators(text: str) -> list[IndicatorFinding]:
    if not text:
        return []
    findings: list[IndicatorFinding] = []
    occupied: list[tuple[int, int]] = []

    for match in _EXCLAMATION_RUN.finditer(text):
        start, end = match.start(), match.end()
        occupied.append((start, end))
        findings.append(
            IndicatorFinding(
                fragment=text[start:end],
                category="Повтор восклицательных знаков",
                explanation=(
                    "Несколько восклицательных знаков подряд могут усиливать "
                    "эмоциональное давление текста."
                ),
                start=start,
                end=end,
            )
        )

    for match in _CAPS_PHRASE.finditer(text):
        start, end = match.start(), match.end()
        fragment = match.group(1)
        # Игнорировать короткие аббревиатуры из одной «слова».
        letters = re.sub(rf"[^{_WORD_CHAR}]", "", fragment)
        if len(letters) < 6:
            continue
        if any(not (end <= a or start >= b) for a, b in occupied):
            continue
        occupied.append((start, end))
        findings.append(
            IndicatorFinding(
                fragment=fragment,
                category="Фраза в верхнем регистре",
                explanation=(
                    "Набор слов целиком заглавными буквами часто используется "
                    "для привлечения внимания."
                ),
                start=start,
                end=end,
            )
        )

    findings.sort(key=lambda f: f.start)
    return findings


def analyze_text_indicators(
    text: str, phrases: Optional[list[dict[str, str]]] = None
) -> list[IndicatorFinding]:
    phrase_hits = find_phrase_indicators(text, phrases)
    style_hits = find_style_indicators(text)
    occupied = [(f.start, f.end) for f in phrase_hits]
    merged = list(phrase_hits)
    for finding in style_hits:
        if any(not (finding.end <= a or finding.start >= b) for a, b in occupied):
            continue
        merged.append(finding)
        occupied.append((finding.start, finding.end))
    merged.sort(key=lambda f: f.start)
    return merged


def _has_value(value: Optional[str]) -> bool:
    if value is None:
        return False
    cleaned = str(value).strip()
    return bool(cleaned) and cleaned.lower() not in {"не найдено", "n/a", "-"}


def build_checklist_from_source(
    *,
    author: str = "",
    publication_date: str = "",
    reference_links: Optional[list[str]] = None,
    publisher: str = "",
    user_overrides: Optional[dict[str, str]] = None,
) -> ChecklistResult:
    """Автозаполняет только пункты, поддерживаемые извлечёнными метаданными."""
    links = reference_links or []
    items = {
        "author_identified": "Да" if _has_value(author) else "Нет",
        "publication_date_identified": "Да" if _has_value(publication_date) else "Нет",
        "reference_links_present": "Да" if links else "Нет",
        "original_document_linked": "Неизвестно",
        "publisher_identifiable": "Да" if _has_value(publisher) else "Неизвестно",
        "independent_corroboration": "Неизвестно",
    }
    if user_overrides:
        for key, value in user_overrides.items():
            if key in items and value in CHECKLIST_VALUES:
                items[key] = value

    known = sum(1 for value in items.values() if value in {"Да", "Нет"})
    unknown = sum(1 for value in items.values() if value == "Неизвестно")
    return ChecklistResult(items=items, known_count=known, unknown_count=unknown)


def validate_conclusion(
    conclusion: str,
    explanation: str,
    evidence_count: int,
) -> list[str]:
    errors: list[str] = []
    if conclusion not in CONCLUSION_OPTIONS:
        errors.append("Выберите допустимый вывод проверки.")
        return errors
    if conclusion in CONCLUSIONS_REQUIRING_EVIDENCE:
        if evidence_count < 1:
            errors.append(
                "Для выбранного вывода добавьте хотя бы одну запись доказательства."
            )
        if not (explanation or "").strip():
            errors.append("Для выбранного вывода требуется письменное пояснение.")
    return errors


def findings_to_dicts(findings: list[IndicatorFinding]) -> list[dict[str, Any]]:
    return [
        {
            "fragment": f.fragment,
            "category": f.category,
            "explanation": f.explanation,
            "start": f.start,
            "end": f.end,
        }
        for f in findings
    ]
