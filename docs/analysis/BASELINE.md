# Baseline артефактов

## Активный корпус (для инструкций)

**CRM с 2026-07-14** — дневные и period отчёты в `docs/analysis/CRM_REPORT_*.md`.

Текущий срез инструкций: **14.07–27.07.2026** (209 диалогов).  
Обновление правил: [../instructions/UPDATE_RULES.md](../instructions/UPDATE_RULES.md).

Пересчёт / новые дни:

```bash
run_crm_daily.bat
run_crm_period.bat 2026-07-14 2026-07-27
```

## Архив DOCX (июнь 2026)

| Артефакт | Роль |
|----------|------|
| `dav.docx`, `output/report_41.json` | Исторический разбор |
| `docs/analysis/dialogs/` | Архив кейсов открытия проблем |

**Не использовать** для новых правил Playbook/Training.
