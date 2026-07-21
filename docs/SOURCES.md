# Источники правды (Source of Truth)

Кратко: что править вручную, что пересобирать CLI.

| Слой | Файлы | Кто правит |
|------|-------|------------|
| **Инструкции оператора** | `docs/instructions/MANAGER_PLAYBOOK.md`, `MANAGER_PLAYBOOK_GE.md`, `OPERATOR_TRAINING_GUIDE.md` | **Вручную** — `--export-docs` их не трогает |
| **Справочники CTA / цена** | `CTA_PLAYBOOK.md`, `PRICE_RESPONSE_RULES.md` | `--export-docs` (можно править шаблон в `export_knowledge.py`) |
| **Анализ DOCX / KB** | `KNOWLEDGE_BASE.md`, `APPENDIX_DIALOGS.md`, `SALES_PATTERNS.md`, `dialogs/` | `--export-docs` из `output/report_41.json` + CRM JSON |
| **CRM-отчёты** | `CRM_REPORT_YYYY-MM-DD.md`, `CRM_REPORT_PERIOD_*.md` | `crm_analysis` / `crm_batch` (не править руками) |
| **Инженерия** | `README.md`, `PROJECT.md`, `CHANGELOG.md`, этот файл | Вручную |

## Правило

Не редактируйте сгенерированные MD «поверх» — изменения затрутся при следующем `--export-docs` или CRM-прогоне. Меняйте playbooks/training и код экспорта.

См. также: [analysis/BASELINE.md](analysis/BASELINE.md), [CHANGELOG.md](../CHANGELOG.md).
