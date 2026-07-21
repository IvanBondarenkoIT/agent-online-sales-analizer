# Документация ДимКава Sales Analyzer

Оглавление `docs/`. Часть файлов **ручная**, часть — автоген (без API для `--export-docs`).

См. [SOURCES.md](SOURCES.md) — что править вручную.

Перегенерация анализа/KB/CTA: `py -3.12 main.py --export-docs`  
(не трогает playbooks и `OPERATOR_TRAINING_GUIDE`)

## Инструкции для сотрудников

Папка **[instructions/](instructions/)** — гайды и скрипты для Messenger.

**Вручную:**
- **[MANAGER_PLAYBOOK.md](instructions/MANAGER_PLAYBOOK.md)** — RU + перевод GE (тренер)
- **[MANAGER_PLAYBOOK_GE.md](instructions/MANAGER_PLAYBOOK_GE.md)** — только GE (оператор)
- **[OPERATOR_TRAINING_GUIDE.md](instructions/OPERATOR_TRAINING_GUIDE.md)** — обучение + разборы CRM

**Автоген (`--export-docs`):**
- [CTA_PLAYBOOK.md](instructions/CTA_PLAYBOOK.md) — призывы к действию
- [PRICE_RESPONSE_RULES.md](instructions/PRICE_RESPONSE_RULES.md) — ответ на «ფასი?»

## Результаты анализа

Папка **[analysis/](analysis/)**.

**DOCX / KB (автоген):**
- [APPENDIX_DIALOGS.md](analysis/APPENDIX_DIALOGS.md) — таблица всех диалогов
- [SALES_PATTERNS.md](analysis/SALES_PATTERNS.md) — паттерны ошибок
- [KNOWLEDGE_BASE.md](analysis/KNOWLEDGE_BASE.md) — база для суфлёра
- [dialogs/](analysis/dialogs/) — разборы по диалогам

**CRM (пайплайн `crm_analysis` / `crm_batch`):**
- [BASELINE.md](analysis/BASELINE.md) — замороженная неделя 14–20.07.2026
- [CRM_REPORT_PERIOD_2026-07-14_2026-07-20.md](analysis/CRM_REPORT_PERIOD_2026-07-14_2026-07-20.md) — сводка периода
- дневные `CRM_REPORT_YYYY-MM-DD.md`

## Прочее

- [ANALYSIS_SUMMARY.md](ANALYSIS_SUMMARY.md) — сводка проекта
- [CHANGELOG.md](../CHANGELOG.md) — статус релизов
