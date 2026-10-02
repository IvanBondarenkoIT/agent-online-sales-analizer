# ИИ-Аналитик и Суфлер онлайн-продаж — ДимКава

Python-приложение для анализа переписок Facebook Messenger и обучения менеджеров продаж.

## Статус проекта

**Готово (0.3.0):** инструкции RU/GE (Playbook + Training), чеклист оператора, CRM daily/weekly, корпус правил с 14.07.  
**Отложено:** суфлёр UI, OpenRouter как основной путь.  
[CHANGELOG](CHANGELOG.md) · [SOURCES](docs/SOURCES.md) · [UPDATE_RULES](docs/instructions/UPDATE_RULES.md) · [BASELINE](docs/analysis/BASELINE.md)

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

При обрыве сети прогресс сохраняется в `output/crm_partial_YYYY-MM-DD.json` — повторный `--crm-date` дожимает оставшиеся диалоги из кэша `output/crm_raw/`. Если `crm_report_*.json` уже есть, `--crm-date` **не** гоняет LLM повторно (как период); полный пересчёт: `--crm-force`.

**Скорость:** Cursor Agents API тратит ~1 мин на диалог (create agent). Поставьте `CRM_LLM_CONCURRENCY=4` в `.env`, чтобы анализировать несколько диалогов параллельно. `REQUEST_DELAY_SEC` — пауза перед каждым вызовом.

### Excel-сводки CRM

При каждом `--analyze-crm-yesterday` / `--crm-date` автоматически создаются:

- `output/crm_excel/CRM_DAILY_YYYY-MM-DD.xlsx` — дневной отчёт
- `output/crm_excel/CRM_SUMMARY.xlsx` — накопительный файл: «Графики» (обзор), «Аналитика» (тренды коучинга, SLA%, MA7), «Как читать» (гайд для новичков + автоснимок периода)
- `docs/analysis/CRM_MOBILE_YYYY-MM-DD.html` (+ `.md`, `CRM_MOBILE_LATEST.*`) — дайджест для телефона: KPI, sparkline, Chart.js

Пересобрать Excel / mobile из уже сохранённого JSON (без LLM):

```bash
py -3.12 main.py --export-crm-excel --crm-date 2026-07-20
py -3.12 main.py --export-crm-excel
py -3.12 main.py --export-crm-mobile --crm-date 2026-08-04
```

На телефоне откройте `CRM_MOBILE_LATEST.html` в браузере (графики) или киньте `.md` в Telegram.
### Основной прогон за неделю (период)

```bash
py -3.12 main.py --crm-main-run
py -3.12 main.py --crm-from 2026-07-14 --crm-to 2026-07-20
py -3.12 main.py --recalc-crm-rt --crm-date 2026-07-20
```

Результат периода: `output/crm_report_period_*.json`, `CRM_PERIOD_*.xlsx`, `docs/analysis/CRM_REPORT_PERIOD_*.md`

**SLA скорости:** рабочее время 10–18 (Тbilisi) — ≤2 мин; вне смены — ≤15 мин. В дневных метриках учитываются только ответы на сообщения клиентов **за день анализа** (без дубля длинных пауз из истории).

**Телефон → WhatsApp:** в отчётах — попытки запросить номер и успехи за день (`phone_capture` в JSON).

Сравнить двух операторов по окнам дат (без LLM, из готовых дневных JSON):

```bash
py -3.12 main.py --crm-compare-operators --op-a-name "Основной" --op-a-from 2026-09-05 --op-a-to 2026-09-18 --op-b-name "Замена" --op-b-from 2026-09-19 --op-b-to 2026-09-20
```

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
