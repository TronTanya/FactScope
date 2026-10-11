"""FactScope — рабочее пространство проверки утверждений и источников."""

from __future__ import annotations

import copy
from typing import Any

import streamlit as st

from analyzer import (
    CHECKLIST_KEYS,
    CHECKLIST_VALUES,
    CONCLUSION_OPTIONS,
    INDICATORS_NOTE,
    RELATIONSHIP_OPTIONS,
    TRANSPARENCY_NOTE,
    analyze_text_indicators,
    build_checklist_from_source,
    findings_to_dicts,
    validate_conclusion,
)
from database import (
    DEFAULT_DB_PATH,
    delete_cases,
    ensure_demo_cases,
    get_case,
    init_db,
    list_cases,
    save_case,
)
from reporting import export_evidence_csv, generate_html_report
from source_loader import (
    MAX_TEXT_CHARS,
    SourceLoadError,
    fetch_public_url,
    read_uploaded_text,
    source_from_manual_text,
)

st.set_page_config(
    page_title="FactScope",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
.block-container {
  max-width: 1100px;
  padding-top: 1.4rem;
  padding-bottom: 3rem;
}
h1, h2, h3, h4 {
  color: #202733;
  letter-spacing: -0.01em;
}
.fs-subtitle {
  color: #667085;
  font-size: 1.05rem;
  margin-top: -0.4rem;
  margin-bottom: 0.35rem;
}
.fs-desc {
  color: #667085;
  margin-bottom: 1.2rem;
}
.fs-panel {
  background: #FFFFFF;
  border: 1px solid #E4E7EC;
  border-radius: 6px;
  padding: 1rem 1.1rem;
  margin-bottom: 0.9rem;
}
.fs-muted {
  color: #667085;
  font-size: 0.92rem;
}
.fs-label {
  font-size: 0.85rem;
  color: #667085;
  margin-bottom: 0.15rem;
}
.fs-value {
  color: #202733;
  margin-bottom: 0.65rem;
}
.fs-status-yes { color: #027A48; font-weight: 600; }
.fs-status-no { color: #B42318; font-weight: 600; }
.fs-status-unknown { color: #B54708; font-weight: 600; }
.fs-note {
  background: #F7F8FA;
  border: 1px solid #E4E7EC;
  border-radius: 4px;
  padding: 0.75rem 0.9rem;
  color: #667085;
  font-size: 0.92rem;
}
div[data-testid="stTabs"] button {
  color: #667085;
}
</style>
"""


def _status_class(value: str) -> str:
    if value == "Да":
        return "fs-status-yes"
    if value == "Нет":
        return "fs-status-no"
    return "fs-status-unknown"


def _empty_state() -> dict[str, Any]:
    return {
        "case_id": None,
        "claim": "",
        "context": "",
        "conclusion": "Не проверено",
        "conclusion_explanation": "",
        "is_demo": False,
        "label": "",
        "source": {
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
        },
        "evidence": [],
        "url_input": "",
        "manual_text": "",
    }


def init_session() -> None:
    init_db(DEFAULT_DB_PATH)
    ensure_demo_cases(DEFAULT_DB_PATH)
    if "state" not in st.session_state:
        st.session_state.state = _empty_state()
    if "flash" not in st.session_state:
        st.session_state.flash = None
    if "evidence_edit_index" not in st.session_state:
        st.session_state.evidence_edit_index = None


def load_case_into_state(case_id: int) -> None:
    case = get_case(case_id, DEFAULT_DB_PATH)
    if case is None:
        st.session_state.flash = ("error", "Проверка не найдена.")
        return
    state = _empty_state()
    state["case_id"] = case["id"]
    state["claim"] = case["claim"]
    state["context"] = case["context"]
    state["conclusion"] = case["conclusion"]
    state["conclusion_explanation"] = case["conclusion_explanation"]
    state["is_demo"] = case["is_demo"]
    state["label"] = case["label"]
    state["source"] = copy.deepcopy(case["source"])
    state["evidence"] = copy.deepcopy(case["evidence"])
    state["manual_text"] = case["source"].get("text") or ""
    state["url_input"] = case["source"].get("url") or ""
    st.session_state.state = state
    st.session_state.evidence_edit_index = None
    st.session_state.flash = ("success", f"Открыта проверка №{case_id}.")


def refresh_analysis(state: dict[str, Any]) -> None:
    source = state["source"]
    text = source.get("text") or ""
    findings = analyze_text_indicators(text)
    source["indicators"] = findings_to_dicts(findings)

    overrides = source.get("checklist") or {}
    checklist = build_checklist_from_source(
        author=source.get("author") or "",
        publication_date=source.get("publication_date") or "",
        reference_links=source.get("reference_links") or [],
        publisher=source.get("publisher") or "",
        user_overrides=overrides if overrides else None,
    )
    # Сохраняем пользовательские ответы для контекстных пунктов.
    for key, _ in CHECKLIST_KEYS:
        if key in overrides and overrides[key] in CHECKLIST_VALUES:
            checklist.items[key] = overrides[key]
    checklist.known_count = sum(
        1 for value in checklist.items.values() if value in {"Да", "Нет"}
    )
    checklist.unknown_count = sum(
        1 for value in checklist.items.values() if value == "Неизвестно"
    )
    source["checklist"] = checklist.items


def apply_extracted_source(state: dict[str, Any], extracted: Any, *, url: str = "") -> None:
    source = state["source"]
    extracted_meta = {
        "title": extracted.title,
        "author": extracted.author,
        "publication_date": extracted.publication_date,
        "canonical_url": extracted.canonical_url,
        "publisher": extracted.publisher,
    }
    source["extracted"] = extracted_meta
    source["title"] = extracted.title
    source["author"] = extracted.author
    source["publication_date"] = extracted.publication_date
    source["canonical_url"] = extracted.canonical_url
    source["publisher"] = extracted.publisher
    source["text"] = extracted.main_text
    source["reference_links"] = list(extracted.reference_links)
    source["retrieval_time"] = extracted.retrieval_time or ""
    source["input_method"] = extracted.input_method
    source["url"] = extracted.final_url or url
    source["checklist"] = {}
    state["manual_text"] = extracted.main_text
    refresh_analysis(state)


def render_header() -> None:
    st.markdown("# FactScope")
    st.markdown(
        '<p class="fs-subtitle">Проверка утверждений и анализ источников</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="fs-desc">Разберите утверждение, изучите источники и сохраните доказательства.</p>',
        unsafe_allow_html=True,
    )


def meta_display(source: dict[str, Any], field: str) -> str:
    value = (source.get(field) or "").strip()
    return value if value else "Не найдено"


def render_verification_tab() -> None:
    state = st.session_state.state

    if state.get("is_demo"):
        st.info(
            "Открыт демонстрационный пример. Это учебный материал, а не реальное расследование."
        )

    st.markdown("### 1. Утверждение")
    state["claim"] = st.text_area(
        "Утверждение для проверки",
        value=state["claim"],
        height=90,
        placeholder="Например: В указанном исследовании участвовали 120 человек.",
        help="Формулируйте одно конкретное проверяемое утверждение на случай.",
    )
    state["context"] = st.text_area(
        "Контекст (необязательно)",
        value=state["context"],
        height=70,
        placeholder="Откуда встретилось утверждение, зачем проверяется.",
    )

    st.markdown("### 2. Источник")
    input_mode = st.radio(
        "Способ ввода источника",
        options=["Вставить текст", "Загрузить .txt", "URL веб-страницы"],
        horizontal=True,
    )

    if input_mode == "Вставить текст":
        state["manual_text"] = st.text_area(
            "Текст источника",
            value=state["manual_text"],
            height=220,
            placeholder="Вставьте текст источника для разбора.",
            max_chars=MAX_TEXT_CHARS,
        )
        if st.button("Применить текст источника", type="primary"):
            try:
                extracted = source_from_manual_text(
                    state["manual_text"],
                    title=state["source"].get("title") or "",
                    author=state["source"].get("author") or "",
                    publication_date=state["source"].get("publication_date") or "",
                    canonical_url=state["source"].get("canonical_url") or "",
                    publisher=state["source"].get("publisher") or "",
                    url=state["source"].get("url") or "",
                )
                apply_extracted_source(state, extracted)
                st.success("Текст источника принят.")
            except SourceLoadError as exc:
                st.error(str(exc))

    elif input_mode == "Загрузить .txt":
        uploaded = st.file_uploader("Файл UTF-8 (.txt), до 1 МБ", type=["txt"])
        if uploaded is not None and st.button("Прочитать файл", type="primary"):
            try:
                text = read_uploaded_text(uploaded.getvalue(), uploaded.name)
                extracted = source_from_manual_text(text)
                apply_extracted_source(state, extracted)
                st.success("Файл загружен.")
            except SourceLoadError as exc:
                st.error(str(exc))

    else:
        state["url_input"] = st.text_input(
            "Публичный HTTP/HTTPS URL",
            value=state.get("url_input") or "",
            placeholder="https://example.com/article",
        )
        st.caption(
            "Загрузка выполняется только по явному запросу. "
            "Локальные, частные и служебные адреса блокируются."
        )
        if st.button("Загрузить источник", type="primary"):
            try:
                extracted = fetch_public_url(state["url_input"])
                apply_extracted_source(state, extracted, url=state["url_input"])
                msg = "Страница загружена."
                if extracted.warnings:
                    msg += " " + " ".join(extracted.warnings)
                st.success(msg)
            except SourceLoadError as exc:
                st.error(str(exc))

    source = state["source"]
    if source.get("text"):
        st.markdown("#### Метаданные источника")
        st.caption(
            "Извлечённые значения можно исправить вручную. "
            "Отсутствие метаданных обозначается как «Не найдено» и не доказывает недостоверность."
        )
        extracted = source.get("extracted") or {}
        c1, c2 = st.columns(2)
        with c1:
            source["title"] = st.text_input("Заголовок", value=source.get("title") or "")
            if extracted.get("title") and extracted.get("title") != source["title"]:
                st.caption(f"Извлечено: {extracted.get('title')}")
            source["author"] = st.text_input("Автор", value=source.get("author") or "")
            if "author" in extracted:
                st.caption(
                    f"Извлечено: {extracted.get('author') or 'Не найдено'}"
                )
            source["publication_date"] = st.text_input(
                "Дата публикации",
                value=source.get("publication_date") or "",
            )
            if "publication_date" in extracted:
                st.caption(
                    f"Извлечено: {extracted.get('publication_date') or 'Не найдено'}"
                )
        with c2:
            source["publisher"] = st.text_input(
                "Издатель", value=source.get("publisher") or ""
            )
            if "publisher" in extracted:
                st.caption(
                    f"Извлечено: {extracted.get('publisher') or 'Не найдено'}"
                )
            source["canonical_url"] = st.text_input(
                "Канонический URL",
                value=source.get("canonical_url") or "",
            )
            source["url"] = st.text_input(
                "URL источника",
                value=source.get("url") or "",
            )
            st.text_input(
                "Время получения (отдельно от даты публикации)",
                value=meta_display(source, "retrieval_time"),
                disabled=True,
            )

        with st.expander("Текст источника", expanded=True):
            st.text_area(
                "Сохранённый текст",
                value=source.get("text") or "",
                height=240,
                disabled=True,
                label_visibility="collapsed",
            )

        if source.get("reference_links"):
            with st.expander("Исходящие ссылки"):
                for link in source["reference_links"]:
                    st.write(link)
        else:
            st.caption("Исходящие ссылки: Не найдено")

        refresh_analysis(state)

        st.markdown("### 3. Сведения об источнике")
        st.markdown(f'<div class="fs-note">{TRANSPARENCY_NOTE}</div>', unsafe_allow_html=True)
        checklist = source.get("checklist") or {}
        known = sum(1 for v in checklist.values() if v in {"Да", "Нет"})
        unknown = sum(1 for v in checklist.values() if v == "Неизвестно")
        st.caption(
            f"Известных ответов: {known}; неизвестных: {unknown}. "
            "Это не вероятность истинности утверждения."
        )

        new_checklist: dict[str, str] = {}
        for key, label in CHECKLIST_KEYS:
            auto_keys = {
                "author_identified",
                "publication_date_identified",
                "reference_links_present",
                "publisher_identifiable",
            }
            current = checklist.get(key, "Неизвестно")
            help_text = None
            if key in auto_keys:
                help_text = "Предзаполнено по метаданным; можно изменить."
            elif key == "original_document_linked":
                help_text = "Оцените вручную по содержанию источника."
            elif key == "independent_corroboration":
                help_text = "Оцените вручную; повтор одной истории не считается автоматически."
            new_checklist[key] = st.selectbox(
                label,
                options=list(CHECKLIST_VALUES),
                index=list(CHECKLIST_VALUES).index(current)
                if current in CHECKLIST_VALUES
                else 2,
                key=f"checklist_{key}_{state.get('case_id')}",
                help=help_text,
            )
            st.markdown(
                f'<span class="{_status_class(new_checklist[key])}">{new_checklist[key]}</span>',
                unsafe_allow_html=True,
            )
        source["checklist"] = new_checklist

        st.markdown("### 4. Текстовые индикаторы")
        st.markdown(f'<div class="fs-note">{INDICATORS_NOTE}</div>', unsafe_allow_html=True)
        indicators = source.get("indicators") or []
        if not indicators:
            st.write("Индикаторы внимания не обнаружены.")
        else:
            for item in indicators:
                st.markdown(
                    f"**Фрагмент:** `{item.get('fragment', '')}`  \n"
                    f"**Категория:** {item.get('category', '')}  \n"
                    f"**Пояснение:** {item.get('explanation', '')}"
                )
                st.divider()

    else:
        st.caption("Добавьте текст источника, чтобы увидеть метаданные и индикаторы.")

    st.markdown("### 5. Доказательства")
    st.caption(
        "Метки «Поддерживает», «Противоречит» и «Даёт контекст» — оценки пользователя, "
        "а не автоматический вердикт. Семейство источника помогает заметить повторы одной истории."
    )

    with st.form("evidence_form", clear_on_submit=True):
        e1, e2 = st.columns(2)
        with e1:
            ev_title = st.text_input("Название источника")
            ev_ref = st.text_input("URL или библиографическая ссылка")
            ev_rel = st.selectbox("Отношение к утверждению", RELATIONSHIP_OPTIONS)
        with e2:
            ev_family = st.text_input("Семейство / происхождение источника (необязательно)")
            ev_excerpt = st.text_area("Релевантный фрагмент", height=90)
            ev_explain = st.text_area("Пояснение", height=90)
        submitted = st.form_submit_button("Добавить доказательство")
        if submitted:
            if not (ev_title.strip() or ev_excerpt.strip() or ev_ref.strip()):
                st.warning("Заполните хотя бы название, ссылку или фрагмент.")
            else:
                state["evidence"].append(
                    {
                        "source_title": ev_title.strip(),
                        "reference": ev_ref.strip(),
                        "excerpt": ev_excerpt.strip(),
                        "relationship": ev_rel,
                        "explanation": ev_explain.strip(),
                        "source_family": ev_family.strip(),
                    }
                )
                st.success("Доказательство добавлено.")

    if state["evidence"]:
        for index, item in enumerate(state["evidence"]):
            with st.expander(
                f"{index + 1}. {item.get('source_title') or 'Без названия'} — {item.get('relationship')}",
                expanded=False,
            ):
                if st.session_state.evidence_edit_index == index:
                    item["source_title"] = st.text_input(
                        "Название",
                        value=item.get("source_title") or "",
                        key=f"edit_title_{index}",
                    )
                    item["reference"] = st.text_input(
                        "Ссылка",
                        value=item.get("reference") or "",
                        key=f"edit_ref_{index}",
                    )
                    item["excerpt"] = st.text_area(
                        "Фрагмент",
                        value=item.get("excerpt") or "",
                        key=f"edit_excerpt_{index}",
                    )
                    item["relationship"] = st.selectbox(
                        "Отношение",
                        RELATIONSHIP_OPTIONS,
                        index=RELATIONSHIP_OPTIONS.index(item.get("relationship"))
                        if item.get("relationship") in RELATIONSHIP_OPTIONS
                        else 2,
                        key=f"edit_rel_{index}",
                    )
                    item["explanation"] = st.text_area(
                        "Пояснение",
                        value=item.get("explanation") or "",
                        key=f"edit_expl_{index}",
                    )
                    item["source_family"] = st.text_input(
                        "Семейство",
                        value=item.get("source_family") or "",
                        key=f"edit_fam_{index}",
                    )
                    if st.button("Готово", key=f"done_{index}"):
                        st.session_state.evidence_edit_index = None
                        st.rerun()
                else:
                    st.write(f"**Ссылка / библиография:** {item.get('reference') or '—'}")
                    st.write(f"**Фрагмент:** {item.get('excerpt') or '—'}")
                    st.write(f"**Пояснение:** {item.get('explanation') or '—'}")
                    st.write(f"**Семейство:** {item.get('source_family') or '—'}")
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("Изменить", key=f"edit_{index}"):
                            st.session_state.evidence_edit_index = index
                            st.rerun()
                    with b2:
                        if st.button("Удалить", key=f"del_{index}"):
                            state["evidence"].pop(index)
                            st.session_state.evidence_edit_index = None
                            st.rerun()
    else:
        st.caption("Пока нет записей доказательств.")

    st.markdown("### 6. Вывод проверки")
    st.markdown(
        '<div class="fs-note">Вывод сформулирован пользователем на основе указанных источников.</div>',
        unsafe_allow_html=True,
    )
    state["conclusion"] = st.selectbox(
        "Итоговый вывод",
        options=list(CONCLUSION_OPTIONS),
        index=list(CONCLUSION_OPTIONS).index(state["conclusion"])
        if state["conclusion"] in CONCLUSION_OPTIONS
        else 0,
    )
    state["conclusion_explanation"] = st.text_area(
        "Пояснение к выводу",
        value=state["conclusion_explanation"],
        height=100,
        help="Обязательно для выводов «подтверждено», «опровергнуто» и «частично подтверждено».",
    )

    errors = validate_conclusion(
        state["conclusion"],
        state["conclusion_explanation"],
        len(state["evidence"]),
    )
    if errors:
        for err in errors:
            st.warning(err)

    col_save, col_new, col_report, col_csv = st.columns(4)
    with col_save:
        if st.button("Сохранить проверку", type="primary", use_container_width=True):
            if not state["claim"].strip():
                st.error("Укажите утверждение.")
            elif errors:
                st.error(errors[0])
            else:
                if source.get("text"):
                    refresh_analysis(state)
                payload = {
                    "claim": state["claim"],
                    "context": state["context"],
                    "conclusion": state["conclusion"],
                    "conclusion_explanation": state["conclusion_explanation"],
                    "is_demo": state.get("is_demo", False),
                    "label": state.get("label") or "",
                    "source": state["source"],
                    "evidence": state["evidence"],
                }
                try:
                    saved_id = save_case(
                        payload,
                        DEFAULT_DB_PATH,
                        case_id=state.get("case_id"),
                    )
                    state["case_id"] = saved_id
                    st.success(f"Проверка сохранена (№{saved_id}).")
                except ValueError as exc:
                    st.error(str(exc))
    with col_new:
        if st.button("Новая проверка", use_container_width=True):
            st.session_state.state = _empty_state()
            st.session_state.evidence_edit_index = None
            st.rerun()
    with col_report:
        if state.get("case_id"):
            case = get_case(state["case_id"], DEFAULT_DB_PATH)
            if case:
                html = generate_html_report(case)
                st.download_button(
                    "Скачать HTML-отчёт",
                    data=html.encode("utf-8"),
                    file_name=f"factscope_report_{case['id']}.html",
                    mime="text/html",
                    use_container_width=True,
                )
        else:
            # Черновик без сохранения
            draft = {
                "claim": state["claim"],
                "context": state["context"],
                "conclusion": state["conclusion"],
                "conclusion_explanation": state["conclusion_explanation"],
                "is_demo": state.get("is_demo", False),
                "created_at": "",
                "updated_at": "",
                "source": state["source"],
                "evidence": state["evidence"],
            }
            if state["claim"] and state["source"].get("text"):
                html = generate_html_report(draft)
                st.download_button(
                    "Скачать HTML-отчёт",
                    data=html.encode("utf-8"),
                    file_name="factscope_report_draft.html",
                    mime="text/html",
                    use_container_width=True,
                )
    with col_csv:
        if state["evidence"]:
            csv_data = export_evidence_csv(state["evidence"])
            st.download_button(
                "Скачать CSV доказательств",
                data=csv_data,
                file_name="factscope_evidence.csv",
                mime="text/csv",
                use_container_width=True,
            )


def render_history_tab() -> None:
    cases = list_cases(DEFAULT_DB_PATH)
    st.markdown("### История проверок")
    if not cases:
        st.info("История пуста. Сохраните проверку на вкладке «Проверка» или откройте демо-примеры.")
        return

    st.caption("Демонстрационные примеры помечены и не являются реальными расследованиями.")
    selected_ids: list[int] = []
    for case in cases:
        label = case.get("label") or ""
        prefix = "[Демо] " if case.get("is_demo") else ""
        title = f"{prefix}№{case['id']}: {case['claim'][:100]}"
        cols = st.columns([0.08, 0.62, 0.15, 0.15])
        with cols[0]:
            checked = st.checkbox(
                "Выбрать",
                key=f"sel_{case['id']}",
                label_visibility="collapsed",
            )
            if checked:
                selected_ids.append(case["id"])
        with cols[1]:
            st.markdown(f"**{title}**")
            meta = (
                f"{label + ' · ' if label else ''}"
                f"Вывод: {case['conclusion']} · "
                f"Обновлено: {case['updated_at']}"
            )
            st.caption(meta)
        with cols[2]:
            if st.button("Открыть", key=f"open_{case['id']}", use_container_width=True):
                load_case_into_state(case["id"])
                st.rerun()
        with cols[3]:
            full = get_case(case["id"], DEFAULT_DB_PATH)
            if full:
                html = generate_html_report(full)
                st.download_button(
                    "Отчёт",
                    data=html.encode("utf-8"),
                    file_name=f"factscope_report_{case['id']}.html",
                    mime="text/html",
                    key=f"dl_{case['id']}",
                    use_container_width=True,
                )

    if selected_ids:
        if st.button("Удалить выбранные", type="secondary"):
            delete_cases(selected_ids, DEFAULT_DB_PATH)
            if st.session_state.state.get("case_id") in selected_ids:
                st.session_state.state = _empty_state()
            st.success(f"Удалено: {len(selected_ids)}.")
            st.rerun()


def render_about_tab() -> None:
    st.markdown("### О проекте")
    st.markdown(
        """
**Назначение.** FactScope помогает структурированно разбирать утверждения:
собрать источник, оценить прозрачность выходных данных, зафиксировать доказательства
и сформулировать собственный вывод.

**Аудитория.** Учащиеся и преподаватели, работающие с проверкой информации
на уроках, в проектной деятельности и на научных конференциях.

**Правила анализа источников.**
- Отсутствие автора или даты показывается как «Не найдено» и не считается доказательством недостоверности.
- Чек-лист прозрачности не превращается в вероятность истинности утверждения.
- Текстовые индикаторы внимания не означают, что материал ложный.
- Повтор одного исходного сообщения в разных публикациях не считается независимым подтверждением автоматически.

**Рабочий процесс.**
1. Сформулировать одно конкретное утверждение.
2. Добавить текст источника вручную, из файла или с публичной веб-страницы.
3. Просмотреть метаданные и индикаторы.
4. Записать поддерживающие, противоречащие и контекстные доказательства.
5. Выбрать вывод и пояснить его.
6. Сохранить проверку и скачать отчёт.

**Технологии.** Python, Streamlit, SQLite, requests/сокеты для безопасной загрузки,
BeautifulSoup4 для разбора HTML, pytest для проверок.

**Практическая польза.** Приложение удерживает внимание на проверяемом утверждении,
разделяет качество оформления источника и силу доказательств, помогает подготовить
отчёт для обсуждения на конференции.

**Ограничения.**
- Нет автоматического вердикта об истинности.
- Нет обхода paywall и выполнения JavaScript.
- Нет облачных ИИ-моделей и внешних платных API.
- Загрузка страниц опциональна и ограничена публичными адресами.

**Исследовательская гипотеза.**
«Структурированный разбор утверждений и источников может помочь учащимся
обосновывать выводы при проверке информации.»

Гипотеза обозначает возможное направление будущей учебной работы.
В этом проекте не приводятся вымышленные результаты опросов или прирост навыков.
"""
    )


def main() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    init_session()
    render_header()

    if st.session_state.flash:
        level, message = st.session_state.flash
        if level == "success":
            st.success(message)
        else:
            st.error(message)
        st.session_state.flash = None

    tab_check, tab_history, tab_about = st.tabs(["Проверка", "История", "О проекте"])
    with tab_check:
        render_verification_tab()
    with tab_history:
        render_history_tab()
    with tab_about:
        render_about_tab()


if __name__ == "__main__":
    main()
