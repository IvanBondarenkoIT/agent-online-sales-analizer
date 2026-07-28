# ИИ-Аналитик и Суфлер онлайн-продаж — ДимКава

Python-приложение для анализа переписок Facebook Messenger и обучения менеджеров продаж.

## Статус проекта

**Готово (0.2.0):** ретро-анализ DOCX (Stage‑1), операционные playbooks + training, CRM daily/weekly с SLA рабочего времени и Excel.  
**Отложено:** суфлёр UI, OpenRouter как основной путь.  
Подробности: [CHANGELOG.md](CHANGELOG.md) · источники правды: [docs/SOURCES.md](docs/SOURCES.md) · baseline: [docs/analysis/BASELINE.md](docs/analysis/BASELINE.md)

## Ежедневный запуск (Windows)

Закройте `CRM_SUMMARY.xlsx` в Excel, затем двойной клик или из консоли:

```bat
run_crm_daily.bat                 :: полный цикл за вчера
run_crm_daily.bat 2026-07-22      :: за конкретную дату
run_crm_period.bat 2026-07-22 2026-07-23   :: несколько дней + period
```

Цикл: fetch CRM → LLM → JSON/MD/Excel (в т.ч. обновление summary) → `--export-docs`.

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
# или зафиксированные версии: pip install -r requirements.lock.txt
copy .env.example .env        # заполните CURSOR_API_KEY
```

### Экспорт знаний в MD (без API)

```bash
py -3.12 main.py --export-docs
```

Пересобирает анализ/KB/CTA/PRICE и оглавления. **Не перезаписывает** `MANAGER_PLAYBOOK*`, `OPERATOR_TRAINING_GUIDE` (их правят вручную).

Результат: `docs/instructions/`, `docs/analysis/` — см. [docs/SOURCES.md](docs/SOURCES.md).

### Переписки из CRM Leeloo.ai (последние 7 дней)

```bash
py -3.12 main.py --fetch-crm
py -3.12 main.py --fetch-crm --crm-days 14
```

### Анализ CRM за вчера (LLM + отчёт)

```bash
py -3.12 main.py --analyze-crm-yesterday
py -3.12 main.py --crm-date 2026-07-20
```

Результат: `output/crm_report_YYYY-MM-DD.json`, `docs/analysis/CRM_REPORT_YYYY-MM-DD.md`, Excel (см. ниже)

### Excel-сводки CRM

При каждом `--analyze-crm-yesterday` / `--crm-date` автоматически создаются:

- `output/crm_excel/CRM_DAILY_YYYY-MM-DD.xlsx` — дневной отчёт
- `output/crm_excel/CRM_SUMMARY.xlsx` — накопительный файл с графиками

Пересобрать Excel из уже сохранённого JSON (без LLM):

```bash
py -3.12 main.py --export-crm-excel --crm-date 2026-07-20
py -3.12 main.py --export-crm-excel
```

### Основной прогон за неделю (период)

```bash
py -3.12 main.py --crm-main-run
py -3.12 main.py --crm-from 2026-07-14 --crm-to 2026-07-20
py -3.12 main.py --recalc-crm-rt --crm-date 2026-07-20
```

Результат периода: `output/crm_report_period_*.json`, `CRM_PERIOD_*.xlsx`, `docs/analysis/CRM_REPORT_PERIOD_*.md`

**SLA скорости:** рабочее время 10–18 (Тbilisi) — ≤2 мин; вне смены — ≤15 мин.

### Полный LLM-анализ (тратит лимиты!)

```bash
py -3.12 main.py --analyze
```

### Проверка парсера (без LLM)

```bash
py -3.12 main.py --parse-only
```

## Структура

См. [PROJECT.md](PROJECT.md) — полная спецификация проекта.
