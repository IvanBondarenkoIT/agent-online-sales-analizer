# Baseline артефактов

## Исторический корпус (DOCX)

| Артефакт | Описание |
|----------|----------|
| `dav.docx` | Исходные переписки (маркеры `#1`…`#41`, дубликат `#14`) |
| `output/report_41.json` | Полный LLM-разбор (локально, в git не хранится) |
| `docs/analysis/dialogs/` | Разборы MD |
| `docs/analysis/APPENDIX_DIALOGS.md`, `SALES_PATTERNS.md`, `KNOWLEDGE_BASE.md` | Автоген из отчёта + CRM |

Пересборка MD: `py -3.12 main.py --export-docs`

## CRM-неделя (первый baseline)

**Период:** 2026-07-14 — 2026-07-20 (пн–вс)

| Артефакт | Где |
|----------|-----|
| Дневные / period MD | `docs/analysis/CRM_REPORT_*.md`, `CRM_REPORT_PERIOD_2026-07-14_2026-07-20.md` |
| JSON / Excel | `output/` (локально; пересобираются CLI) |

Пересчёт периода (дорого по LLM, если без `--crm-force` — skip существующих JSON):

```bash
py -3.12 main.py --crm-from 2026-07-14 --crm-to 2026-07-20
py -3.12 main.py --recalc-crm-rt --crm-date 2026-07-20   # только скорость
py -3.12 main.py --export-crm-excel
```

В git фиксируем **MD-отчёты** и инструкции; сырьё `crm_raw/` и большие JSON остаются локально.
