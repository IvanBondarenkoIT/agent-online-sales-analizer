# Проект: ИИ-Аналитик и Суфлер онлайн-продаж для ДимКава (Грузия)

## Бизнес-контекст

**Компания:** ДимКава, Грузия (B2C: кофемашины, кофе в пачках).

**Проблема:** Высокий трафик в Facebook Messenger (90% диалогов на грузинском), низкая конверсия. Критические ошибки менеджеров:

1. **Паттерн «Цена-Молчание»** — на вопрос о цене называют цифру без выявления потребности.
2. **Отсутствие CTA** — диалог не закрывается призывом к действию.

**Цель:** Python-приложение, которое анализирует переписки, формирует базу знаний лучших практик и работает как суфлёр (идеальные ответы на грузинском + объяснение логики на русском).

---

## Этапы реализации

| Этап | Задача | Статус | Тест-маркер |
|------|--------|--------|-------------|
| 1 | Ретро-анализ 41 переписки + playbooks | **Готово** | `output/report_41.json`, `docs/instructions/` |
| 1b | CRM daily + weekly, SLA, Excel | **Готово** | period 14–20.07, `crm_response_time` tests |
| 2 | База знаний для суфлёра (`knowledge_base.txt` / KB) | **Частично** — есть `KNOWLEDGE_BASE.md`; мини-экзамен отложен | MD в `docs/analysis/` |
| 3 | Режим суфлёра (Streamlit/CLI) | **Отложено** | — |
| 4 | OpenRouter как основной путь | **Отложено** (клиент есть) | — |

Актуальный снимок: [CHANGELOG.md](CHANGELOG.md), [docs/SOURCES.md](docs/SOURCES.md).

---

## Формат исходных данных (`dav.docx`)

| Ожидание | Факт |
|----------|------|
| Маркер `--- Диалог №N ---` | Маркер `#N` на отдельной строке (`#1` … `#41`) |
| 41 переписка | 42 секции (дубликат `#14`) |
| Роли клиент/менеджер | **Нет** — только строки текста |
| Язык | Грузинский (мхедрули), 2–26 реплик на диалог |

**Роли:** LLM определяет клиента и менеджера на этапе анализа. Парсер отдаёт нумерованный список реплик.

**Дубликат `#14`:** обе секции анализируются отдельно; в отчёте — `warnings: ["duplicate_marker_14"]`.

---

## Структура проекта

```
agent-online-sales-analizer/
├── PROJECT.md
├── README.md
├── CHANGELOG.md
├── main.py
├── config.py
├── analyzer.py             # DOCX → LLM → report_41.json
├── export_knowledge.py     # --export-docs (KB/CTA; не playbooks)
├── crm_fetch.py            # Выгрузка из Leeloo.ai (lilu_chats)
├── crm_analysis.py         # Дневной CRM-анализ
├── crm_batch.py            # Недельный / period прогон
├── crm_excel_export.py     # Daily / summary / period Excel
├── crm_response_time.py    # SLA 10–18 Tbilisi
├── dav.docx
├── docs/
│   ├── SOURCES.md          # Что вручную / что генерируется
│   ├── instructions/       # Playbooks (ручные) + CTA/PRICE
│   └── analysis/           # KB, dialogs, CRM_REPORT_*.md
├── parsers/docx_parser.py
├── llm/
├── prompts/
│   ├── analyzer_system.txt
│   └── crm_analyzer_system.txt
├── models/
│   ├── schemas.py
│   └── crm_schemas.py
├── tests/
├── output/                 # gitignored: JSON, Excel, crm_raw
└── logs/
```

---

## Документация (`docs/`)

См. [docs/SOURCES.md](docs/SOURCES.md): playbooks и training — **вручную**; KB/CTA/dialogs — `--export-docs`; CRM MD — пайплайн CRM.

| Файл | Назначение |
|------|------------|
| [docs/README.md](docs/README.md) | Главное оглавление |
| [docs/SOURCES.md](docs/SOURCES.md) | Source of truth |
| [docs/instructions/](docs/instructions/) | **Инструкции для менеджеров** |
| [docs/instructions/MANAGER_PLAYBOOK.md](docs/instructions/MANAGER_PLAYBOOK.md) | RU + перевод GE (тренер), вручную |
| [docs/instructions/MANAGER_PLAYBOOK_GE.md](docs/instructions/MANAGER_PLAYBOOK_GE.md) | Только GE (оператор), вручную |
| [docs/instructions/OPERATOR_TRAINING_GUIDE.md](docs/instructions/OPERATOR_TRAINING_GUIDE.md) | Обучение + кейсы CRM, вручную |
| [docs/instructions/CTA_PLAYBOOK.md](docs/instructions/CTA_PLAYBOOK.md) | CTA на грузинском (автоген) |
| [docs/instructions/PRICE_RESPONSE_RULES.md](docs/instructions/PRICE_RESPONSE_RULES.md) | Ответ на «ფასი?» (автоген) |
| [docs/analysis/](docs/analysis/) | Результаты анализа + CRM |
| [docs/analysis/BASELINE.md](docs/analysis/BASELINE.md) | Замороженная CRM-неделя |
| [docs/analysis/APPENDIX_DIALOGS.md](docs/analysis/APPENDIX_DIALOGS.md) | Таблица scores (автоген) |
| [docs/analysis/SALES_PATTERNS.md](docs/analysis/SALES_PATTERNS.md) | Паттерны ошибок |
| [docs/analysis/KNOWLEDGE_BASE.md](docs/analysis/KNOWLEDGE_BASE.md) | База знаний для суфлёра |
| [docs/analysis/dialogs/](docs/analysis/dialogs/) | Разборы по диалогам |
| [docs/ANALYSIS_SUMMARY.md](docs/ANALYSIS_SUMMARY.md) | Сводка проекта |

---

## CLI

| Команда | API | Описание |
|---------|-----|----------|
| `py -3.12 main.py` | Нет | Справка |
| `py -3.12 main.py --export-docs` | Нет | Перегенерировать `docs/` из локальных данных |
| `py -3.12 main.py --fetch-crm` | Leeloo API | Переписки за 7 дней → `output/crm_raw/` |
| `py -3.12 main.py --fetch-crm --crm-days 14` | Leeloo API | Переписки за N дней |
| `py -3.12 main.py --analyze-crm-yesterday` | Leeloo + Cursor | **Основной ежедневный** режим: CRM за вчера |
| `py -3.12 main.py --crm-date 2026-07-20` | Leeloo + Cursor | CRM-анализ за дату |
| `py -3.12 main.py --crm-main-run` | Leeloo + Cursor | Основной прогон: прошлая календарная неделя пн–вс |
| `py -3.12 main.py --crm-from … --crm-to …` | Leeloo + Cursor | Произвольный период + period JSON/MD/Excel |
| `py -3.12 main.py --crm-force` | Leeloo + Cursor | Пересчитать день, даже если JSON есть |
| `py -3.12 main.py --recalc-crm-rt --crm-date …` | Нет | Пересчёт метрик скорости (work/off) без LLM |
| `py -3.12 main.py --export-crm-excel` | Нет | Excel из сохранённых JSON |
| `py -3.12 main.py --parse-only` | Нет | Парсинг DOCX → `parsed_dialogs.json` |
| `py -3.12 main.py --analyze` | Да | Полный LLM-анализ |
| `py -3.12 main.py --analyze --resume` | Да | Дозагрузить только недостающие диалоги |

**Не запускать `--analyze` без необходимости** — каждый диалог = отдельный вызов Cursor Cloud API.

---

## Переменные окружения (`.env`)

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `LLM_PROVIDER` | `cursor` \| `openrouter` \| `mock` | `cursor` |
| `CURSOR_API_KEY` | Ключ Cursor Dashboard → Integrations | — |
| `OPENROUTER_API_KEY` | Для Этапа 4 | — |
| `LLM_MODEL` | Модель (`composer-2.5` / `anthropic/claude-3.5-sonnet`) | `composer-2.5` |
| `INPUT_FILE` | Путь к DOCX | `dav.docx` |
| `OUTPUT_DIR` | Каталог отчётов | `output` |
| `LOGS_DIR` | Каталог логов | `logs` |
| `MAX_RETRIES` | Повторы при невалидном JSON | `2` |
| `REQUEST_DELAY_SEC` | Пауза между вызовами LLM | `1` |
| `LILU_API_SECRET` | Токен Leeloo.ai API (для `--fetch-crm`) | — |
| `LILU_API_URL` | Базовый URL Leeloo | `https://api.leeloo.ai` |
| `LILU_VERIFY_SSL` | Проверка SSL (`false` при антивирусе) | `true` |
| `CRM_TIMEZONE` | Часовой пояс для SLA | `Asia/Tbilisi` |
| `CRM_WORK_START` / `CRM_WORK_END` | Рабочие часы | `10:00` / `18:00` |
| `CRM_WORK_DAYS` | Рабочие дни (0=пн) | `0,1,2,3,4` |
| `CRM_SLA_WORK_SEC` | SLA в рабочее время | `120` (2 мин) |
| `CRM_SLA_OFF_SEC` | SLA вне смены | `900` (15 мин) |

Переключение провайдера LLM: одна строка `LLM_PROVIDER=openrouter` в `.env`.  
CRM-токен можно скопировать из `D:\CursorProjects\lilu_chats\.env` или оставить пустым — тогда `crm_fetch` подхватит `lilu_chats/.env`.

---

## Схема JSON-отчёта (`output/report_41.json`)

```json
{
  "meta": {
    "source_file": "dav.docx",
    "dialogs_count": 42,
    "llm_provider": "cursor",
    "model": "composer-2.5",
    "generated_at": "2026-06-30T12:00:00"
  },
  "aggregate": {
    "avg_scores": {"needs_id": 2.1, "cta": 1.8},
    "team_top_errors": [
      {"error": "Цена без вовлекающего вопроса", "count": 28, "percent": 66.7}
    ],
    "low_score_dialogs": [3, 14, 35]
  },
  "warnings": ["duplicate_marker_14"],
  "dialogs": [
    {
      "dialog_id": 3,
      "section_index": 3,
      "message_count": 7,
      "analysis": {
        "summary": "...",
        "client_emotion": "...",
        "errors_found": ["..."],
        "killer_phrase": "...",
        "scores": {"needs_id": 1, "cta": 0},
        "ideal_response_georgian": "..."
      }
    }
  ]
}
```

### Поля анализа одного диалога

| Поле | Тип | Описание |
|------|-----|----------|
| `summary` | string | О чём диалог |
| `client_emotion` | string | Скрытая эмоция/триггер клиента |
| `errors_found` | string[] | Ошибки менеджера |
| `killer_phrase` | string | Фраза, убившая диалог (грузинский) |
| `scores.needs_id` | 0–5 | Выявление потребностей |
| `scores.cta` | 0–5 | Наличие CTA |
| `ideal_response_georgian` | string | Идеальный ответ менеджера |

---

## Системный промпт анализатора

См. [`prompts/analyzer_system.txt`](prompts/analyzer_system.txt).

---

## Архитектурные принципы

- **Изоляция модулей:** `analyzer.py` (DOCX), `crm_*.py` (Leeloo), `config.py`; суфлёр (`prompter.py`) — этап 3, отложен.
- **Абстракция LLM:** переключение провайдера через `.env`, без правок бизнес-логики.
- **Логирование:** каждый шаг в `logs/analyzer_YYYYMMDD.log` / CRM-логгеры.
- **Безопасность:** API-ключи только в `.env`, не в коде.

---

## Открытые вопросы

### Критично

1. **Дубликат `#14`** — по умолчанию: обе секции отдельно + warning.
2. **CURSOR_API_KEY** — без ключа: `--parse-only` или `LLM_PROVIDER=mock`.
3. **Время анализа** — 41+ последовательных вызовов LLM (~1–3 мин).

### Для отложенных этапов 2–4

4. **Методология ДимКава** — скрипт на «ფასი?», подарок кофе, CTA Тбилиси/Батуми, тон «კიბატონო» (частично уже в playbooks).
5. **Валидация грузинского** — кто проверяет суфлёр (носитель / менеджер)?
6. **PII в логах** — имена клиентов в логах; для продакшена — маскирование.
7. **Messenger** — вне scope; суфлёр через Streamlit/CLI.
8. **OpenRouter model slug** — проверить актуальность на Этапе 4.

### Опционально после Этапа 1

- Progress bar (tqdm)
- ~~Resume частично готового отчёта~~ — реализовано: `--analyze --resume`
- Unit-тест парсера на фикстуре
