"""Формирование HTML-отчётов и CSV экспорта доказательств."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional
from urllib.parse import urlparse

from analyzer import CHECKLIST_KEYS, INDICATORS_NOTE, TRANSPARENCY_NOTE

SAFE_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

METHOD_LIMITATIONS = [
    "FactScope не определяет истинность утверждения автоматически.",
    "Индикаторы внимания и чек-лист прозрачности источника не являются вердиктом о достоверности.",
    "Вывод формулирует пользователь на основе указанных источников и доказательств.",
    "Загрузка веб-страниц не выполняет JavaScript и не обходит ограничения доступа.",
    "Повторные публикации одного исходного материала не считаются независимым подтверждением автоматически.",
]


def is_safe_http_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    candidate = url.strip()
    if not SAFE_URL_RE.match(candidate):
        return False
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username or parsed.password:
        return False
    if not parsed.hostname:
        return False
    return True


def link_html(url: str, label: Optional[str] = None) -> str:
    text = escape(label or url)
    if is_safe_http_url(url):
        return f'<a href="{escape(url, quote=True)}">{text}</a>'
    return text


def _display(value: Any) -> str:
    if value is None:
        return "Не найдено"
    text = str(value).strip()
    return text if text else "Не найдено"


def generate_html_report(case: dict[str, Any]) -> str:
    source = case.get("source") or {}
    evidence = case.get("evidence") or []
    checklist = source.get("checklist") or {}
    indicators = source.get("indicators") or []
    analysis_date = case.get("updated_at") or case.get("created_at") or datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    checklist_rows = []
    for key, label in CHECKLIST_KEYS:
        value = checklist.get(key, "Неизвестно")
        checklist_rows.append(
            f"<tr><td>{escape(label)}</td><td>{escape(str(value))}</td></tr>"
        )

    indicator_rows = []
    if indicators:
        for item in indicators:
            indicator_rows.append(
                "<tr>"
                f"<td>{escape(str(item.get('fragment', '')))}</td>"
                f"<td>{escape(str(item.get('category', '')))}</td>"
                f"<td>{escape(str(item.get('explanation', '')))}</td>"
                "</tr>"
            )
    else:
        indicator_rows.append(
            "<tr><td colspan='3'>Индикаторы внимания не обнаружены.</td></tr>"
        )

    evidence_blocks = []
    if evidence:
        for index, item in enumerate(evidence, start=1):
            ref = item.get("reference") or ""
            ref_html = link_html(ref) if is_safe_http_url(ref) else escape(_display(ref))
            evidence_blocks.append(
                "<article class='evidence'>"
                f"<h3>Доказательство {index}</h3>"
                f"<p><strong>Источник:</strong> {escape(_display(item.get('source_title')))}</p>"
                f"<p><strong>Ссылка / библиография:</strong> {ref_html}</p>"
                f"<p><strong>Фрагмент:</strong> {escape(_display(item.get('excerpt')))}</p>"
                f"<p><strong>Отношение к утверждению (оценка пользователя):</strong> "
                f"{escape(_display(item.get('relationship')))}</p>"
                f"<p><strong>Пояснение:</strong> {escape(_display(item.get('explanation')))}</p>"
                f"<p><strong>Семейство источника:</strong> "
                f"{escape(_display(item.get('source_family')))}</p>"
                "</article>"
            )
    else:
        evidence_blocks.append("<p>Записи доказательств отсутствуют.</p>")

    links = source.get("reference_links") or []
    if links:
        links_html = "<ul>" + "".join(f"<li>{link_html(u)}</li>" for u in links) + "</ul>"
    else:
        links_html = "<p>Не найдено</p>"

    limitations = "".join(f"<li>{escape(item)}</li>" for item in METHOD_LIMITATIONS)
    demo_note = ""
    if case.get("is_demo"):
        demo_note = (
            "<p class='note'><strong>Демонстрационный пример.</strong> "
            "Не является реальным расследованием.</p>"
        )

    title_bit = escape((case.get("claim") or "Проверка")[:80])
    source_url = source.get("url") or source.get("canonical_url") or ""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Отчёт FactScope — {title_bit}</title>
  <style>
    body {{
      font-family: Georgia, "Times New Roman", serif;
      color: #202733;
      background: #F7F8FA;
      margin: 0;
      padding: 32px 16px;
      line-height: 1.5;
    }}
    main {{
      max-width: 900px;
      margin: 0 auto;
      background: #FFFFFF;
      border: 1px solid #E4E7EC;
      border-radius: 6px;
      padding: 28px 32px;
    }}
    h1, h2, h3 {{ font-family: "Segoe UI", Arial, sans-serif; }}
    h1 {{ font-size: 1.6rem; margin-top: 0; color: #202733; }}
    h2 {{ font-size: 1.15rem; margin-top: 1.8rem; border-bottom: 1px solid #E4E7EC; padding-bottom: 0.35rem; }}
    .muted {{ color: #667085; }}
    .note {{
      background: #F7F8FA;
      border: 1px solid #E4E7EC;
      border-radius: 4px;
      padding: 12px 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 0.95rem;
    }}
    th, td {{
      border: 1px solid #E4E7EC;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #F7F8FA; }}
    .evidence {{
      border: 1px solid #E4E7EC;
      border-radius: 4px;
      padding: 12px 14px;
      margin: 12px 0;
    }}
    a {{ color: #315EFB; }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #F7F8FA;
      border: 1px solid #E4E7EC;
      border-radius: 4px;
      padding: 12px;
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 0.95rem;
    }}
  </style>
</head>
<body>
<main>
  <p class="muted">FactScope — отчёт о проверке утверждения</p>
  <h1>Утверждение</h1>
  {demo_note}
  <p>{escape(_display(case.get("claim")))}</p>
  <p class="muted"><strong>Контекст:</strong> {escape(_display(case.get("context")))}</p>
  <p class="muted"><strong>Дата анализа:</strong> {escape(str(analysis_date))}</p>

  <h2>Источник</h2>
  <table>
    <tr><th>Поле</th><th>Значение</th></tr>
    <tr><td>Заголовок</td><td>{escape(_display(source.get("title")))}</td></tr>
    <tr><td>Автор</td><td>{escape(_display(source.get("author")))}</td></tr>
    <tr><td>Дата публикации</td><td>{escape(_display(source.get("publication_date")))}</td></tr>
    <tr><td>Канонический URL</td><td>{link_html(source.get("canonical_url") or "") if is_safe_http_url(source.get("canonical_url") or "") else escape(_display(source.get("canonical_url")))}</td></tr>
    <tr><td>Издатель</td><td>{escape(_display(source.get("publisher")))}</td></tr>
    <tr><td>URL загрузки</td><td>{link_html(source_url) if is_safe_http_url(source_url) else escape(_display(source_url))}</td></tr>
    <tr><td>Время получения</td><td>{escape(_display(source.get("retrieval_time")))}</td></tr>
    <tr><td>Способ ввода</td><td>{escape(_display(source.get("input_method")))}</td></tr>
  </table>
  <h3>Текст источника</h3>
  <pre>{escape(source.get("text") or "")}</pre>
  <h3>Исходящие ссылки</h3>
  {links_html}

  <h2>Чек-лист сведений об источнике</h2>
  <p class="note">{escape(TRANSPARENCY_NOTE)}</p>
  <table>
    <tr><th>Вопрос</th><th>Ответ</th></tr>
    {''.join(checklist_rows)}
  </table>

  <h2>Текстовые индикаторы внимания</h2>
  <p class="note">{escape(INDICATORS_NOTE)}</p>
  <table>
    <tr><th>Фрагмент</th><th>Категория</th><th>Пояснение</th></tr>
    {''.join(indicator_rows)}
  </table>

  <h2>Доказательства</h2>
  <p class="muted">Метки отношений к утверждению заданы пользователем.</p>
  {''.join(evidence_blocks)}

  <h2>Вывод</h2>
  <p><strong>{escape(_display(case.get("conclusion")))}</strong></p>
  <p>{escape(_display(case.get("conclusion_explanation")))}</p>
  <p class="note">Вывод сформулирован пользователем на основе указанных источников.</p>

  <h2>Ограничения метода</h2>
  <ul>{limitations}</ul>
</main>
</body>
</html>
"""


def export_evidence_csv(evidence: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(
        [
            "source_title",
            "reference",
            "excerpt",
            "relationship",
            "explanation",
            "source_family",
        ]
    )
    for item in evidence:
        writer.writerow(
            [
                item.get("source_title") or "",
                item.get("reference") or "",
                item.get("excerpt") or "",
                item.get("relationship") or "",
                item.get("explanation") or "",
                item.get("source_family") or "",
            ]
        )
    # UTF-8 с BOM для совместимости с Excel (русский текст).
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
