# Инструкции ДимКава — Messenger

Операционные гайды для менеджеров продаж.

Playbooks и training — **вручную** (не перезаписываются `--export-docs`). 
CTA/PRICE — автоген. См. [../SOURCES.md](../SOURCES.md).

## Кому что читать

| Роль | Файл |
|------|------|
| **Оператор** (пишет клиентам) | [MANAGER_PLAYBOOK_GE.md](MANAGER_PLAYBOOK_GE.md) |
| **Обучение** (теория + разборы) | [OPERATOR_TRAINING_GUIDE.md](OPERATOR_TRAINING_GUIDE.md) |
| **Тренер / руководитель** | [MANAGER_PLAYBOOK.md](MANAGER_PLAYBOOK.md) |
| Справочник CTA | [CTA_PLAYBOOK.md](CTA_PLAYBOOK.md) |
| Ответ на вопрос о цене | [PRICE_RESPONSE_RULES.md](PRICE_RESPONSE_RULES.md) |

## Примеры из реальных диалогов

Разборы переписок: [../analysis/dialogs/](../analysis/dialogs/)

Таблица scores: [../analysis/APPENDIX_DIALOGS.md](../analysis/APPENDIX_DIALOGS.md)

## CRM-анализ

- Ежедневно: `py -3.12 main.py --analyze-crm-yesterday`
- Недельный прогон: `py -3.12 main.py --crm-main-run` или `--crm-from` / `--crm-to`
- SLA: 2 мин в рабочее время (10–18), 15 мин вне смены
- Baseline: [../analysis/BASELINE.md](../analysis/BASELINE.md)
- Отчёты: [../analysis/CRM_REPORT_PERIOD_2026-07-14_2026-07-20.md](../analysis/CRM_REPORT_PERIOD_2026-07-14_2026-07-20.md)

