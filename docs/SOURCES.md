# Источники правды (Source of Truth)

| Слой | Файлы | Кто правит |
|------|-------|------------|
| **Инструкции (пары RU/GE)** | `MANAGER_PLAYBOOK_RU/GE`, `OPERATOR_TRAINING_GUIDE_RU/GE` | **Вручную**, вместе |
| **Процесс патча** | `UPDATE_RULES.md` | Тренер |
| **CTA / цена stubs** | `CTA_*_RU/GE`, `PRICE_*_RU/GE` | `--export-docs` (тонкие stubs) |
| **KB / DOCX analysis** | `KNOWLEDGE_BASE`, `APPENDIX_*`, `dialogs/` | `--export-docs` (архив DOCX + CRM в KB) |
| **CRM-отчёты** | `CRM_REPORT_*.md` | `crm_analysis` / `crm_batch` |
| **Инженерия** | README, PROJECT, CHANGELOG | Вручную |

**Активный корпус для правил продаж:** CRM **с 14.07.2026**. DOCX-41 — архив, не источник новых выводов.

Редиректы: `MANAGER_PLAYBOOK.md`, `OPERATOR_TRAINING_GUIDE.md`, `CTA_PLAYBOOK.md`, `PRICE_RESPONSE_RULES.md`.

См. [analysis/BASELINE.md](analysis/BASELINE.md).
