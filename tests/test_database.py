"""Тесты сохранения и редактирования проверок."""

from __future__ import annotations

import pytest

from database import (
    delete_case,
    delete_evidence_entry,
    get_case,
    init_db,
    list_cases,
    save_case,
    update_evidence_entry,
)


def _sample_payload(**overrides):
    payload = {
        "claim": "В указанном исследовании участвовали 120 человек.",
        "context": "Тестовый контекст",
        "conclusion": "Недостаточно данных",
        "conclusion_explanation": "",
        "is_demo": False,
        "label": "",
        "source": {
            "title": "Тест",
            "author": "",
            "publication_date": "",
            "canonical_url": "",
            "publisher": "Демо",
            "url": "",
            "text": "В указанном исследовании участвовали 120 человек.",
            "reference_links": [],
            "retrieval_time": "",
            "input_method": "manual",
            "extracted": {},
            "checklist": {"author_identified": "Нет"},
            "indicators": [],
        },
        "evidence": [
            {
                "source_title": "Тест",
                "reference": "локально",
                "excerpt": "120 человек",
                "relationship": "Даёт контекст",
                "explanation": "Число названо без методики.",
                "source_family": "A",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_persistence_roundtrip(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    case_id = save_case(_sample_payload(), db_path=db)
    loaded = get_case(case_id, db_path=db)
    assert loaded is not None
    assert loaded["claim"].startswith("В указанном исследовании")
    assert loaded["source"]["text"].find("120") >= 0
    assert len(loaded["evidence"]) == 1
    assert list_cases(db_path=db)[0]["id"] == case_id


def test_evidence_edit_and_delete(tmp_path):
    db = tmp_path / "test.db"
    case_id = save_case(_sample_payload(), db_path=db)
    loaded = get_case(case_id, db_path=db)
    evidence_id = loaded["evidence"][0]["id"]

    assert update_evidence_entry(
        case_id,
        evidence_id,
        {"explanation": "Обновлённое пояснение", "relationship": "Поддерживает"},
        db_path=db,
    )
    loaded = get_case(case_id, db_path=db)
    assert loaded["evidence"][0]["explanation"] == "Обновлённое пояснение"
    assert loaded["evidence"][0]["relationship"] == "Поддерживает"

    assert delete_evidence_entry(case_id, evidence_id, db_path=db)
    loaded = get_case(case_id, db_path=db)
    assert loaded["evidence"] == []


def test_conclusion_validation_on_save(tmp_path):
    db = tmp_path / "test.db"
    with pytest.raises(ValueError):
        save_case(
            _sample_payload(
                conclusion="Подтверждено собранными источниками",
                conclusion_explanation="",
                evidence=[],
            ),
            db_path=db,
        )


def test_update_and_delete_case(tmp_path):
    db = tmp_path / "test.db"
    case_id = save_case(_sample_payload(), db_path=db)
    save_case(
        _sample_payload(claim="Обновлённое утверждение.", evidence=[]),
        db_path=db,
        case_id=case_id,
    )
    loaded = get_case(case_id, db_path=db)
    assert loaded["claim"] == "Обновлённое утверждение."
    assert delete_case(case_id, db_path=db)
    assert get_case(case_id, db_path=db) is None
