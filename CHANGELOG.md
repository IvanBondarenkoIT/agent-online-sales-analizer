# Changelog

## 0.3.0 — 2026-07-28

Инструкции: пары RU/GE, корпус CRM с 14.07, чеклист оператора, `UPDATE_RULES.md`.

### Готово

- `MANAGER_PLAYBOOK_RU` / `GE`, `OPERATOR_TRAINING_GUIDE_RU` / `GE` — полное зеркало
- Чеклист 9 пунктов в Playbook §8 (GE) / §8 (RU)
- CTA/PRICE — тонкие stubs RU+GE
- DOCX-41 больше не источник актуальных выводов

## 0.2.0 — 2026-07-21

Фиксация текущего уровня: DOCX Stage‑1 + CRM дневной/недельный пайплайн.

### Готово

- **Stage‑1 (DOCX):** парсинг `dav.docx`, LLM-разбор → `output/report_41.json`, playbooks RU/GE, training guide, KB/dialogs через `--export-docs`
- **CRM daily:** `--analyze-crm-yesterday` / `--crm-date` → JSON + MD + Excel
- **CRM period:** `--crm-main-run`, `--crm-from` / `--crm-to`, period JSON/MD/`CRM_PERIOD_*.xlsx`
- **SLA скорости:** Asia/Tbilisi, пн–пт 10–18; рабочее ≤2 мин, вне смены ≤15 мин (`crm_response_time.py`)
- **Baseline CRM-неделя:** 2026-07-14 … 2026-07-20 (см. `docs/analysis/BASELINE.md`)

### Не входит (отложено)

- Суфлёр UI (Streamlit / `prompter.py`)
- OpenRouter как основной провайдер (клиент есть, основной путь — Cursor)
- Перенос модулей в `src/`, переименование каталога проекта

### Документация

- `docs/SOURCES.md` — что вручную / что генерируется
- `docs/analysis/BASELINE.md` — замороженная CRM-неделя
- `.python-version` 3.12, `requirements.lock.txt`, CRM_* в `.env.example`
