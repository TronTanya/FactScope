"""Сохранение и загрузка проверок FactScope в SQLite."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from analyzer import validate_conclusion

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "factscope.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path | str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '',
                conclusion TEXT NOT NULL DEFAULT 'Не проверено',
                conclusion_explanation TEXT NOT NULL DEFAULT '',
                is_demo INTEGER NOT NULL DEFAULT 0,
                label TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                publication_date TEXT NOT NULL DEFAULT '',
                canonical_url TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                reference_links_json TEXT NOT NULL DEFAULT '[]',
                retrieval_time TEXT NOT NULL DEFAULT '',
                input_method TEXT NOT NULL DEFAULT 'manual',
                extracted_json TEXT NOT NULL DEFAULT '{}',
                checklist_json TEXT NOT NULL DEFAULT '{}',
                indicators_json TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                source_title TEXT NOT NULL DEFAULT '',
                reference TEXT NOT NULL DEFAULT '',
                excerpt TEXT NOT NULL DEFAULT '',
                relationship TEXT NOT NULL DEFAULT 'Даёт контекст',
                explanation TEXT NOT NULL DEFAULT '',
                source_family TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            );
            """
        )


def _row_to_case(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    case_id = row["id"]
    source_row = conn.execute(
        "SELECT * FROM sources WHERE case_id = ?", (case_id,)
    ).fetchone()
    evidence_rows = conn.execute(
        """
        SELECT * FROM evidence
        WHERE case_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (case_id,),
    ).fetchall()

    source: dict[str, Any]
    if source_row:
        source = {
            "id": source_row["id"],
            "title": source_row["title"],
            "author": source_row["author"],
            "publication_date": source_row["publication_date"],
            "canonical_url": source_row["canonical_url"],
            "publisher": source_row["publisher"],
            "url": source_row["url"],
            "text": source_row["text"],
            "reference_links": json.loads(source_row["reference_links_json"] or "[]"),
            "retrieval_time": source_row["retrieval_time"],
            "input_method": source_row["input_method"],
            "extracted": json.loads(source_row["extracted_json"] or "{}"),
            "checklist": json.loads(source_row["checklist_json"] or "{}"),
            "indicators": json.loads(source_row["indicators_json"] or "[]"),
        }
    else:
        source = {
            "title": "",
            "author": "",
            "publication_date": "",
            "canonical_url": "",
            "publisher": "",
            "url": "",
            "text": "",
            "reference_links": [],
            "retrieval_time": "",
            "input_method": "manual",
            "extracted": {},
            "checklist": {},
            "indicators": [],
        }

    evidence = [
        {
            "id": er["id"],
            "source_title": er["source_title"],
            "reference": er["reference"],
            "excerpt": er["excerpt"],
            "relationship": er["relationship"],
            "explanation": er["explanation"],
            "source_family": er["source_family"],
            "sort_order": er["sort_order"],
        }
        for er in evidence_rows
    ]

    return {
        "id": case_id,
        "claim": row["claim"],
        "context": row["context"],
        "conclusion": row["conclusion"],
        "conclusion_explanation": row["conclusion_explanation"],
        "is_demo": bool(row["is_demo"]),
        "label": row["label"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "source": source,
        "evidence": evidence,
    }


def list_cases(db_path: Path | str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, claim, context, conclusion, is_demo, label, created_at, updated_at
            FROM cases
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        return [
            {
                "id": r["id"],
                "claim": r["claim"],
                "context": r["context"],
                "conclusion": r["conclusion"],
                "is_demo": bool(r["is_demo"]),
                "label": r["label"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]


def get_case(case_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> Optional[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            return None
        return _row_to_case(row, conn)


def save_case(
    payload: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
    *,
    case_id: Optional[int] = None,
) -> int:
    """Сохраняет проверку целиком. Возвращает id записи."""
    init_db(db_path)
    claim = (payload.get("claim") or "").strip()
    if not claim:
        raise ValueError("Укажите утверждение для проверки.")

    evidence = list(payload.get("evidence") or [])
    conclusion = payload.get("conclusion") or "Не проверено"
    explanation = payload.get("conclusion_explanation") or ""
    errors = validate_conclusion(conclusion, explanation, len(evidence))
    if errors:
        raise ValueError(errors[0])

    source = payload.get("source") or {}
    now = utc_now()

    with connect(db_path) as conn:
        if case_id is None:
            cur = conn.execute(
                """
                INSERT INTO cases (
                    claim, context, conclusion, conclusion_explanation,
                    is_demo, label, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim,
                    payload.get("context") or "",
                    conclusion,
                    explanation,
                    1 if payload.get("is_demo") else 0,
                    payload.get("label") or "",
                    now,
                    now,
                ),
            )
            case_id = int(cur.lastrowid)
        else:
            existing = conn.execute(
                "SELECT id FROM cases WHERE id = ?", (case_id,)
            ).fetchone()
            if existing is None:
                raise ValueError("Проверка не найдена.")
            conn.execute(
                """
                UPDATE cases
                SET claim = ?, context = ?, conclusion = ?,
                    conclusion_explanation = ?, is_demo = ?, label = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    claim,
                    payload.get("context") or "",
                    conclusion,
                    explanation,
                    1 if payload.get("is_demo") else 0,
                    payload.get("label") or "",
                    now,
                    case_id,
                ),
            )
            conn.execute("DELETE FROM sources WHERE case_id = ?", (case_id,))
            conn.execute("DELETE FROM evidence WHERE case_id = ?", (case_id,))

        conn.execute(
            """
            INSERT INTO sources (
                case_id, title, author, publication_date, canonical_url,
                publisher, url, text, reference_links_json, retrieval_time,
                input_method, extracted_json, checklist_json, indicators_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                source.get("title") or "",
                source.get("author") or "",
                source.get("publication_date") or "",
                source.get("canonical_url") or "",
                source.get("publisher") or "",
                source.get("url") or "",
                source.get("text") or "",
                json.dumps(source.get("reference_links") or [], ensure_ascii=False),
                source.get("retrieval_time") or "",
                source.get("input_method") or "manual",
                json.dumps(source.get("extracted") or {}, ensure_ascii=False),
                json.dumps(source.get("checklist") or {}, ensure_ascii=False),
                json.dumps(source.get("indicators") or [], ensure_ascii=False),
            ),
        )

        for index, item in enumerate(evidence):
            conn.execute(
                """
                INSERT INTO evidence (
                    case_id, source_title, reference, excerpt,
                    relationship, explanation, source_family, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    item.get("source_title") or "",
                    item.get("reference") or "",
                    item.get("excerpt") or "",
                    item.get("relationship") or "Даёт контекст",
                    item.get("explanation") or "",
                    item.get("source_family") or "",
                    index,
                ),
            )

        return int(case_id)


def delete_case(case_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        return cur.rowcount > 0


def delete_cases(case_ids: list[int], db_path: Path | str = DEFAULT_DB_PATH) -> int:
    if not case_ids:
        return 0
    init_db(db_path)
    deleted = 0
    with connect(db_path) as conn:
        for case_id in case_ids:
            cur = conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
            deleted += cur.rowcount
    return deleted


def update_evidence_entry(
    case_id: int,
    evidence_id: int,
    updates: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> bool:
    allowed = {
        "source_title",
        "reference",
        "excerpt",
        "relationship",
        "explanation",
        "source_family",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    init_db(db_path)
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [case_id, evidence_id]
    with connect(db_path) as conn:
        cur = conn.execute(
            f"""
            UPDATE evidence
            SET {assignments}
            WHERE case_id = ? AND id = ?
            """,
            values,
        )
        if cur.rowcount:
            conn.execute(
                "UPDATE cases SET updated_at = ? WHERE id = ?",
                (utc_now(), case_id),
            )
        return cur.rowcount > 0


def delete_evidence_entry(
    case_id: int,
    evidence_id: int,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM evidence WHERE case_id = ? AND id = ?",
            (case_id, evidence_id),
        )
        if cur.rowcount:
            conn.execute(
                "UPDATE cases SET updated_at = ? WHERE id = ?",
                (utc_now(), case_id),
            )
        return cur.rowcount > 0


def load_demo_payloads(path: Optional[Path] = None) -> list[dict[str, Any]]:
    demo_path = path or (Path(__file__).resolve().parent / "content" / "demo_cases.json")
    with demo_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("demo_cases.json должен содержать список.")
    return data


def ensure_demo_cases(db_path: Path | str = DEFAULT_DB_PATH) -> list[int]:
    """Загружает демо-кейсы, если в базе ещё нет помеченных is_demo."""
    init_db(db_path)
    with connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM cases WHERE is_demo = 1"
        ).fetchone()["c"]
    if count:
        return []

    created: list[int] = []
    for demo in load_demo_payloads():
        source = demo.get("source") or {}
        indicators_payload = {
            "claim": demo["claim"],
            "context": demo.get("context") or "",
            "conclusion": demo.get("conclusion") or "Не проверено",
            "conclusion_explanation": demo.get("conclusion_explanation") or "",
            "is_demo": True,
            "label": demo.get("label") or "Демонстрационный пример",
            "source": {
                **source,
                "checklist": demo.get("checklist") or source.get("checklist") or {},
                "indicators": source.get("indicators") or [],
                "extracted": {
                    "title": source.get("title") or "",
                    "author": source.get("author") or "",
                    "publication_date": source.get("publication_date") or "",
                    "canonical_url": source.get("canonical_url") or "",
                    "publisher": source.get("publisher") or "",
                },
            },
            "evidence": demo.get("evidence") or [],
        }
        # Индикаторы считаем при первом сохранении демо.
        from analyzer import analyze_text_indicators, findings_to_dicts

        findings = analyze_text_indicators(source.get("text") or "")
        indicators_payload["source"]["indicators"] = findings_to_dicts(findings)
        created.append(save_case(indicators_payload, db_path=db_path))
    return created
