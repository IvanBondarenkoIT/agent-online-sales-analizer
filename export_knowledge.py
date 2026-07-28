"""Export local analysis data to Markdown (no API calls)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from config import Settings

SCORE_LOG_RE = re.compile(
    r"Dialog #(\d+) scores: needs_id=(\d+), cta=(\d+)"
)
PRICE_RE = re.compile(r"ლარი|ფას|ღირს", re.IGNORECASE)
CTA_RE = re.compile(r"\?|გსურთ|მობრძანდ|გსურთ|დაგიკავშირდ|შეგიძლიათ", re.IGNORECASE)


@dataclass
class DialogScores:
    dialog_id: int
    needs_id: int
    cta: int


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_report(settings: Settings) -> dict:
    """Prefer full report_41.json, fall back to report_partial.json."""
    for name in ("report_41.json", "report_partial.json"):
        data = _load_json(settings.output_dir / name)
        if data and data.get("dialogs"):
            return data
    return {"dialogs": [], "meta": {}, "aggregate": {}}


def parse_scores_from_log(log_path: Path, run_start: str = "16:54:") -> dict[int, DialogScores]:
    """Take scores from the first full cursor run (16:54–17:20)."""
    if not log_path.exists():
        return {}

    scores_by_id: dict[int, DialogScores] = {}
    in_run = False

    for line in log_path.read_text(encoding="utf-8").splitlines():
        if "Starting analysis, provider=cursor" in line and "16:54:" in line:
            in_run = True
            scores_by_id.clear()
            continue
        if in_run and "Starting analysis, provider=cursor" in line and "16:54:" not in line:
            break
        if not in_run:
            continue
        match = SCORE_LOG_RE.search(line)
        if match:
            did = int(match.group(1))
            scores_by_id[did] = DialogScores(
                dialog_id=did,
                needs_id=int(match.group(2)),
                cta=int(match.group(3)),
            )
    return scores_by_id


def _normalize_error(error: str) -> str:
    return error.strip().lower()


def _aggregate_errors(dialogs: list[dict]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for d in dialogs:
        analysis = d.get("analysis", {})
        for err in analysis.get("errors_found", []):
            key = _normalize_error(err)
            if key:
                counter[key] += 1
    return counter.most_common(10)


def _offline_flags(messages: list[str]) -> dict[str, bool]:
    if len(messages) < 2:
        return {"price_early": False, "ends_with_cta": False}
    manager_first = messages[1] if len(messages) > 1 else ""
    last = messages[-1]
    return {
        "price_early": bool(PRICE_RE.search(manager_first)),
        "ends_with_cta": bool(CTA_RE.search(last)),
    }


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _export_dialog_md(
    dialogs_dir: Path,
    did: int,
    analysis: dict,
    messages: list[str],
) -> None:
    lines = [
        f"# Диалог #{did}\n",
        f"## Суть\n{analysis['summary']}\n",
        f"## Эмоция клиента\n{analysis['client_emotion']}\n",
        "## Ошибки менеджера\n",
    ]
    for err in analysis.get("errors_found", []):
        lines.append(f"- {err}")
    lines += [
        f"\n## Фраза, убившая диалог\n> {analysis.get('killer_phrase', '—')}\n",
        f"## Оценки: потребности {analysis['scores']['needs_id']}/5, "
        f"CTA {analysis['scores']['cta']}/5\n",
        f"## Идеальный ответ (грузинский)\n{analysis.get('ideal_response_georgian', '')}\n",
        "## Исходные реплики\n",
    ]
    for i, msg in enumerate(messages, 1):
        lines.append(f"{i}. {msg}")
    _write(dialogs_dir / f"dialog_{did:02d}.md", "\n".join(lines) + "\n")


def _export_appendix(analysis_dir: Path, report: dict) -> None:
    dialogs = sorted(report.get("dialogs", []), key=lambda d: d["dialog_id"])
    aggregate = report.get("aggregate", {})
    avg = aggregate.get("avg_scores", {})
    low_needs = sum(
        1 for d in dialogs if d["analysis"]["scores"]["needs_id"] <= 2
    )
    low_cta = sum(
        1 for d in dialogs if d["analysis"]["scores"]["cta"] <= 2
    )

    lines = [
        "# Приложение: все диалоги ДимКава\n",
        "Автогенерация из `output/report_41.json`. "
        "Перегенерация: `py -3.12 main.py --export-docs`\n",
        "## Сводка scores\n",
        f"- Диалогов: **{len(dialogs)}**",
        f"- Средний **needs_id**: {avg.get('needs_id', '—')} / 5",
        f"- Средний **cta**: {avg.get('cta', '—')} / 5",
        f"- Диалогов с needs_id ≤ 2: **{low_needs}**",
        f"- Диалогов с cta ≤ 2: **{low_cta}**\n",
        "## Таблица диалогов\n",
        "| # | needs | cta | killer_phrase | Разбор |",
        "|---|-------|-----|---------------|--------|",
    ]
    for d in dialogs:
        a = d["analysis"]
        killer = (a.get("killer_phrase") or "—").replace("|", "\\|")
        if len(killer) > 60:
            killer = killer[:57] + "..."
        lines.append(
            f"| {d['dialog_id']} | {a['scores']['needs_id']} | "
            f"{a['scores']['cta']} | {killer} | "
            f"[dialog_{d['dialog_id']:02d}.md](dialogs/dialog_{d['dialog_id']:02d}.md) |"
        )

    lines += [
        "\n## Таблица killer_phrases (полный текст)\n",
        "| # | killer_phrase |",
        "|---|---------------|",
    ]
    for d in dialogs:
        killer = (d["analysis"].get("killer_phrase") or "—").replace("|", "\\|")
        lines.append(f"| {d['dialog_id']} | {killer} |")

    worst = sorted(
        dialogs,
        key=lambda d: (d["analysis"]["scores"]["needs_id"], d["analysis"]["scores"]["cta"]),
    )[:10]
    lines += [
        "\n## Худшие 10 диалогов (для планёрки)\n",
        "| # | needs | cta | killer_phrase |",
        "|---|-------|-----|---------------|",
    ]
    for d in worst:
        a = d["analysis"]
        killer = (a.get("killer_phrase") or "—").replace("|", "\\|")
        if len(killer) > 50:
            killer = killer[:47] + "..."
        lines.append(
            f"| {d['dialog_id']} | {a['scores']['needs_id']} | "
            f"{a['scores']['cta']} | {killer} |"
        )

    _write(analysis_dir / "APPENDIX_DIALOGS.md", "\n".join(lines) + "\n")


def _load_crm_reports(output_dir: Path) -> list[dict]:
    """Daily CRM reports only (exclude period)."""
    import re

    daily_re = re.compile(r"^crm_report_\d{4}-\d{2}-\d{2}\.json$")
    reports: list[dict] = []
    for path in sorted(output_dir.glob("crm_report_*.json")):
        if not daily_re.match(path.name):
            continue
        data = _load_json(path)
        if data and data.get("meta"):
            reports.append(data)
    return reports


def _load_period_report(output_dir: Path) -> dict | None:
    paths = sorted(output_dir.glob("crm_report_period_*.json"))
    if not paths:
        return None
    return _load_json(paths[-1])


def _collect_killer_phrases(
    report_dialogs: list[dict],
    crm_reports: list[dict],
) -> list[str]:
    seen: set[str] = set()
    phrases: list[str] = []
    for d in report_dialogs:
        kp = (d.get("analysis") or {}).get("killer_phrase", "").strip()
        if kp and kp not in seen:
            seen.add(kp)
            phrases.append(kp)
    for crm in crm_reports:
        for d in crm.get("dialogs", []):
            kp = (d.get("analysis") or {}).get("killer_phrase", "").strip()
            if kp and kp not in seen:
                seen.add(kp)
                phrases.append(kp)
    return phrases[:15]


def _build_knowledge_base(
    report: dict,
    crm_reports: list[dict],
    period_report: dict | None = None,
) -> str:
    """Build enriched knowledge base from historical + CRM reports."""
    from datetime import date

    report_dialogs = report.get("dialogs", [])
    hist_agg = report.get("aggregate", {}).get("avg_scores", {})
    latest_crm = crm_reports[-1] if crm_reports else None
    crm_date = latest_crm["meta"]["target_date"] if latest_crm else None
    crm_agg = latest_crm.get("aggregate", {}) if latest_crm else {}
    crm_scores = crm_agg.get("avg_scores", {})
    crm_checklist = crm_agg.get("checklist_pass_rate", {})
    crm_rt = crm_agg.get("response_time", {})
    killers = _collect_killer_phrases(report_dialogs, crm_reports)

    lines = [
        "# База знаний ДимКава (для суфлёра)\n",
        "Синтез из анализа переписок: 42 исторических диалога (Facebook DOCX)"
        + (f" + CRM Leeloo.ai (отчёты: {', '.join(r['meta']['target_date'] for r in crm_reports)})."
           if crm_reports else "."),
        "\n",
        f"**Обновлено:** {date.today().isoformat()}"
        + (f" (CRM {crm_date})" if crm_date else "")
        + "  \n",
        "**Развёрнутое обучение:** [OPERATOR_TRAINING_GUIDE_RU.md](../instructions/OPERATOR_TRAINING_GUIDE_RU.md) / "
        "[GE](../instructions/OPERATOR_TRAINING_GUIDE_GE.md)\n",
        "---\n",
        "## Метрики команды (бенчмарк)\n",
        "| Источник | Диалогов | needs_id | cta | deal_closed |",
        "|----------|----------|----------|-----|-------------|",
    ]
    if hist_agg:
        lines.append(
            f"| Исторический (06.2026) | {len(report_dialogs)} | "
            f"{hist_agg.get('needs_id', '—')} / 5 | {hist_agg.get('cta', '—')} / 5 | — |"
        )
    if latest_crm:
        lines.append(
            f"| CRM {crm_date} | {latest_crm['meta']['dialogs_count']} | "
            f"{crm_scores.get('needs_id', '—')} / 5 | {crm_scores.get('cta', '—')} / 5 | "
            f"{crm_scores.get('deal_closed', '—')} / 5 |"
        )
        lines.append(
            "\n**Вывод:** CRM-переписки хуже по needs и CTA. Системные проблемы не решены.\n"
        )

    if crm_checklist:
        lines += [
            f"### Чеклист CRM {crm_date} (% прохождения)\n",
            "| Критерий | % |",
            "|----------|---|",
        ]
        for crit, pct in sorted(crm_checklist.items(), key=lambda x: x[1]):
            lines.append(f"| {crit} | {pct} |")

    if period_report:
        p_meta = period_report.get("meta", {})
        p_agg = period_report.get("aggregate", {})
        p_scores = p_agg.get("avg_scores", {})
        p_rt = p_agg.get("response_time", {})
        lines += [
            "",
            f"### Метрики за период {p_meta.get('date_from')} — {p_meta.get('date_to')}",
            "",
            "| Критерий | Среднее |",
            "|----------|---------|",
        ]
        for key, label in [
            ("needs_id", "needs_id"),
            ("cta", "cta"),
            ("deal_closed", "deal_closed"),
        ]:
            lines.append(f"| {label} | {p_scores.get(key, '—')} / 5 |")
        if p_rt:
            med_w = p_rt.get("median_work_seconds")
            lines += [
                "",
                f"- SLA рабочее (>2 мин): **{p_rt.get('over_sla_work', 0)}** нарушений",
                f"- Медиана рабочая: **{med_w / 60:.1f} мин**" if med_w else "- Медиана рабочая: —",
                f"- SLA вне смены (>15 мин): **{p_rt.get('over_sla_off', 0)}**",
            ]
        summaries = period_report.get("daily_summaries") or []
        if summaries:
            lines += ["", "| День | needs | cta | мед. раб. | SLA>2м |", "|------|-------|-----|-----------|--------|"]
            for s in summaries:
                rt_d = s.get("response_time") or {}
                lines.append(
                    f"| {s.get('target_date')} | {s.get('avg_scores', {}).get('needs_id', '—')} | "
                    f"{s.get('avg_scores', {}).get('cta', '—')} | "
                    f"{rt_d.get('median_work_seconds') or '—'} | {rt_d.get('over_sla_work', 0)} |"
                )

    if crm_rt:
        med = crm_rt.get("median_seconds")
        med_w = crm_rt.get("median_work_seconds")
        med_str = f"{med / 60:.0f} мин" if med else "—"
        med_w_str = f"{med_w / 60:.1f} мин" if med_w else "—"
        lines += [
            "\n### Скорость ответа (последний день CRM)\n",
            f"- Медиана рабочая (10–18): **{med_w_str}**",
            f"- Нарушений SLA >2 мин: **{crm_rt.get('over_sla_work', 0)}**",
            f"- Медиана общая: **{med_str}**",
            f"- Пауз >15 мин: **{crm_rt.get('over_15min', '—')}**",
            "- Правило: рабочее время — **≤2 мин**; вне смены — **≤15 мин**\n",
        ]

    lines += [
        "---\n",
        "## Продукт\n",
        "### Кофемашины\n",
        "- B2C: DeLonghi и др.; B2B: кафе, офис, drive-through",
        "- **Автомат** (ერთი თითის დაჭერით) — дом, офис",
        "- **Механика** (~480 ₾) — бюджет, молоко вручную",
        "- **Автомат с капучинатором** (~1190–1685 ₾)",
        "- **Премиум** (~1899–2299 ₾) — встроенный помол, 8+ напитков",
        "- **Коммерческий класс** (70–160 чашек/день) — не домашняя 1899 ₾\n",
        "### Кофе\n",
        "- Blasercafe: 250 г от ~30 ₾, 1 кг от ~118 ₾",
        "- Decaf / Swiss Water — отвечать прямо на метод декaffeination\n",
        "### В комплекте к машине\n",
        "- Доставка, монтаж, обучение тренером, кофе в подарок, гарантия De'Longhi",
        "- Messenger-скидка (ниже walk-in)\n",
        "### Рассрочка TBC\n",
        "- ~80–100 ₾/мес; при отказе банка — альтернативы оплаты + дemo\n",
        "## Локация и каналы\n",
        "- Шоурум: ზ. ფალიაშვილის 66 (ვაკე), თბილისი",
        "- Также: გორგილadze 1, Batumi Mall (1 этаж)",
        "- Доставка регион: +8 ₾ Кутаisi, 2–3 раб. дня",
        "- Онлайн-скидка через Messenger; визит — написать заранее\n",
        "## Тон (грузинский)\n",
        "- `გამარჯობა` + имя из CRM",
        "- Один вопрос за сообщение; без англ. автоответов",
        "- Извинение за задержку — в начале: `ბოდიში შეყოვნებისთვის!`\n",
        "## Алгоритм (4 шага)\n",
        "```",
        "Приветствие + имя → Один вопрос → Цена в контексте → Конкретный CTA",
        "```\n",
        "| Триггер | Первый вопрос |",
        "|---------|---------------|",
        "| `ფასი?` | `სახლისთვის თუ ბიზნესისთვის?` |",
        "| «სახლისთვის» | `დღეში რამდენ ფინჯანს?` |",
        "| Кафе | `დღეში რამდენ ჭიქას?` |",
        "| «დამირეკეთ» | Позвонить за 15 мин |\n",
        "## CTA — сильные фразы\n",
        "- `გსურთ ხვალ 15:00-ზე ვაკეში, ფალიაშვილის 66-ზე გაჩვენოთ?`",
        "- `გსურთ ლინკი გამოგიგზავნოთ ონლაინ შესაძენად?`",
        "- `რა გაჩერებთ — ფასი, ზომა თუ ხარისხი? დავაჯავშნოთ ფასდაკლება 48 საათით?`",
        "- `5 წუთში დაგირეკავთ [номер]-ზe`\n",
        "## CTA — ЗАПРЕЩЕНО\n",
        "- `მოგვწერეთ ბიუჯეტი` без рекомендации",
        "- `ნებისმიერი კითხვაზე მოგვმართეთ`",
        "- `რამდენად დაინტერესებული ხართ?`",
        "- `რას გულისხმობთ?` на ясный запрос\n",
        "## Сценарии по типу запроса\n",
        "### Кофемашина — `ფასი?`\n",
        "1. Имя + `სახლისთვის თუ ბიზნესისთვის?` → 2. Цена + ценность → 3. CTA (шоурум/ссылка)\n",
        "### Кофе в зёрнах\n",
        "1. Сорт / способ заваривания → 2. **Конкретная** цена на названный сорт → 3. CTA (доставка/Batumi)\n",
        "### «მოვიფიქრებ»\n",
        "`გასაგებია` + `რა გაჩერებთ?` + фото + бронь скидки 48 ч\n",
        "### Конкурент (ee.ge)\n",
        "Сравнить честно + 10 мин звонок или дemo\n",
        "### Аксессуар\n",
        "Проверить наличие в ДимKава за 5 мин; не сразу в сервис\n",
        "### Handoff шоурум → Messenger\n",
        "Завершить продажу в Messenger, не терять клиента между каналами\n",
        "## Успешные паттерны (CRM)\n",
        "- Персонализация по имени из CRM",
        "- B2B: нагрузка в чашках → модель под нагрузку",
        "- `გსურთ გავაფორმოთ შეკვეთa?` → клиент даёт реквизиты",
        "- Самовывоз из Тбилиisi для горячих лидов",
        "- После отказа TBC — 2–3 альтернативы оплаты\n",
    ]

    if killers:
        lines += ["## Killer phrases (из разборов)\n"]
        for i, kp in enumerate(killers, 1):
            lines.append(f"{i}. `{kp}`")
        lines.append("")

    lines += [
        "## Запреты\n",
        "- Не давать цену в первом предложении",
        "- Не путать дом / кафе (50+ чашек)",
        "- Не 3 цены без объяснения",
        "- Не игнорировать «დამირეკეთ» и «ხვალ მოვალ»",
        "- Не отправлять в сервис при запросе покупки аксессуара\n",
        "## Чеклист качества (суфлёр)\n",
        "| Критерий | Порог CRM |",
        "|----------|-----------|",
    ]
    if crm_checklist:
        for crit, pct in sorted(crm_checklist.items(), key=lambda x: x[1]):
            lines.append(f"| {crit} | {pct}% |")
        lines.append("")
    lines += [
        "**Перед отправкой:** нет цены в 1-м предложении? имя? один вопрос? CTA? <15 мин?\n",
        "## Чеклист перед отправкой\n",
        "- [ ] Нет цены в первом предложении?",
        "- [ ] Есть имя клиента?",
        "- [ ] Один уточняющий вопрос?",
        "- [ ] Конкретный CTA в конце?",
        "- [ ] Ответ < 15 мин?\n",
        "## Связанные документы\n",
        "- [OPERATOR_TRAINING_GUIDE_RU.md](../instructions/OPERATOR_TRAINING_GUIDE_RU.md) / "
        "[GE](../instructions/OPERATOR_TRAINING_GUIDE_GE.md) — полное обучение",
        "- [MANAGER_PLAYBOOK_RU.md](../instructions/MANAGER_PLAYBOOK_RU.md) / "
        "[GE](../instructions/MANAGER_PLAYBOOK_GE.md) — шпаргалка + чеклист",
        "- [MANAGER_PLAYBOOK_GE.md](../instructions/MANAGER_PLAYBOOK_GE.md) — шпаргалка",
        "- [CTA_PLAYBOOK.md](../instructions/CTA_PLAYBOOK.md)",
        "- [PRICE_RESPONSE_RULES.md](../instructions/PRICE_RESPONSE_RULES.md)",
    ]
    if crm_date:
        lines.append(f"- [CRM_REPORT_{crm_date}.md](CRM_REPORT_{crm_date}.md)")
    lines += [
        "- [SALES_PATTERNS.md](SALES_PATTERNS.md)",
        "- `output/crm_excel/CRM_SUMMARY.xlsx` — динамика по дням\n",
        "## Открытые вопросы (PM)\n",
        "- Политика подарка кофe к моделям",
        "- Актуальный прайс Blaser по сортам",
        "- SLA ответа в CRM\n",
    ]
    return "\n".join(lines) + "\n"


def export_docs(settings: Settings) -> Path:
    docs_dir = settings.project_root / "docs"
    instructions_dir = docs_dir / "instructions"
    analysis_dir = docs_dir / "analysis"
    dialogs_dir = analysis_dir / "dialogs"

    report = _load_report(settings)
    parsed_path = settings.output_dir / "parsed_dialogs.json"
    log_path = settings.logs_dir / "analyzer_20260630.log"

    parsed = _load_json(parsed_path) or {"dialogs": [], "warnings": []}
    report_dialogs = report.get("dialogs", [])
    full_analyses = {d["dialog_id"]: d for d in report_dialogs}
    parsed_by_id = {d["id"]: d for d in parsed.get("dialogs", [])}
    log_scores = parse_scores_from_log(log_path)

    for did, dialog_report in sorted(full_analyses.items()):
        analysis = dialog_report["analysis"]
        messages = parsed_by_id.get(did, {}).get("messages", [])
        _export_dialog_md(dialogs_dir, did, analysis, messages)

    offline_lines = [
        "# Офлайн-флаги по диалогам\n",
        "Дополнение к [APPENDIX_DIALOGS.md](../APPENDIX_DIALOGS.md): "
        "эвристики по сырому тексту (цена в первом ответе, CTA в конце).\n",
        "| # | needs_id | cta | Цена в 1-м ответе | CTA в конце |",
        "|---|----------|-----|-------------------|-------------|",
    ]
    for did in sorted(full_analyses.keys()):
        sc = full_analyses[did]["analysis"]["scores"]
        msgs = parsed_by_id.get(did, {}).get("messages", [])
        flags = _offline_flags(msgs)
        offline_lines.append(
            f"| {did} | {sc['needs_id']} | {sc['cta']} | "
            f"{'да' if flags['price_early'] else 'нет'} | "
            f"{'да' if flags['ends_with_cta'] else 'нет'} |"
        )
    _write(dialogs_dir / "dialog_offline_flags.md", "\n".join(offline_lines) + "\n")

    _export_appendix(analysis_dir, report)

    errors_top = _aggregate_errors(report_dialogs)
    pattern_categories: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for err, count in errors_top:
        low = err
        if "цена" in low or "ლარი" in low or "голым" in low or "1899" in low:
            pattern_categories["Цена-Молчание"].append((err, count))
        elif "cta" in low or "пассив" in low or "бюджет" in low or "შემოგთავაზ" in low:
            pattern_categories["Слабый CTA"].append((err, count))
        elif "дом" in low or "бизнес" in low or "кафе" in low or "სახლ" in low:
            pattern_categories["Дом vs бизнес"].append((err, count))
        elif "მოვიფიქრებ" in low or "отлож" in low or "подума" in low:
            pattern_categories["Не отработано «подумаю»"].append((err, count))
        else:
            pattern_categories["Прочее"].append((err, count))

    aggregate = report.get("aggregate", {})
    avg_scores = aggregate.get("avg_scores", {})
    patterns_md = [
        "# Паттерны ошибок команды ДимКава\n",
        "Источник: архив DOCX + актуальный CRM с 14.07 (`CRM_REPORT_*.md`).\n",
        "Инструкции: [MANAGER_PLAYBOOK_RU.md](../instructions/MANAGER_PLAYBOOK_RU.md) / "
        "[GE](../instructions/MANAGER_PLAYBOOK_GE.md)\n",
        "## Сводка по scores (DOCX-архив; для правил смотри CRM)\n",
    ]
    if avg_scores:
        low_needs = sum(
            1 for d in report_dialogs if d["analysis"]["scores"]["needs_id"] <= 2
        )
        low_cta = sum(
            1 for d in report_dialogs if d["analysis"]["scores"]["cta"] <= 2
        )
        patterns_md += [
            f"- Средний **needs_id**: {avg_scores.get('needs_id', '—')} / 5",
            f"- Средний **cta**: {avg_scores.get('cta', '—')} / 5",
            f"- Диалогов с needs_id ≤ 2: {low_needs}",
            f"- Диалогов с cta ≤ 2: {low_cta}\n",
        ]
    elif log_scores:
        avg_needs = sum(s.needs_id for s in log_scores.values()) / len(log_scores)
        avg_cta = sum(s.cta for s in log_scores.values()) / len(log_scores)
        patterns_md += [
            f"- Средний **needs_id**: {avg_needs:.2f} / 5 (из лога)",
            f"- Средний **cta**: {avg_cta:.2f} / 5 (из лога)\n",
        ]

    patterns_md.append("## Top-ошибки (из полного разбора)\n")
    for err, count in errors_top[:8]:
        patterns_md.append(f"- ({count}x) {err}")

    patterns_md.append("\n## Категории паттернов\n")
    for cat, items in pattern_categories.items():
        patterns_md.append(f"\n### {cat}\n")
        for err, count in items:
            patterns_md.append(f"- ({count}x) {err}")

    patterns_md += [
        "\n## Правило для менеджеров\n",
        "1. На «ფასი?» — **не** начинать с цифры. Сначала 1 вопрос о контексте.",
        "2. Каждый ответ заканчивать **конкретным CTA** (звонок, демо, ссылка, визит).",
        "3. Если клиент пишет «მოვიფიქრებ» — выяснить, что сдерживает, и предложить шаг.",
        "4. Не смешивать 3 цены в одном сообщении (1899 + от 1300 + от 470).",
    ]
    _write(analysis_dir / "SALES_PATTERNS.md", "\n".join(patterns_md) + "\n")

    crm_reports = _load_crm_reports(settings.output_dir)
    period_report = _load_period_report(settings.output_dir)
    kb_content = _build_knowledge_base(report, crm_reports, period_report)
    _write(analysis_dir / "KNOWLEDGE_BASE.md", kb_content)

    price_ru = [
        "# Ответ на «ფასი?» (RU)\n",
        "Полные правила: [MANAGER_PLAYBOOK_RU.md](MANAGER_PLAYBOOK_RU.md) §3 и §7.\n",
        "GE: [PRICE_RESPONSE_RULES_GE.md](PRICE_RESPONSE_RULES_GE.md)\n",
        "**Шаг 1 (без цены):**\n```\n",
        "გამარჯობა [სახელი]! ☕️ სანამ ფასს გეტყვით —\n",
        "სახლისთვის გჭირდებათ თუ ბიზნესისთვის?\n```\n",
        "**Шаг 2:** одна цена + польза + CTA.\n",
        "**Запрет:** цена в первом предложении; три цены подряд.\n",
    ]
    price_ge = [
        "# პასუხი «ფასი?»-ზე (GE)\n",
        "სრული წესები: [MANAGER_PLAYBOOK_GE.md](MANAGER_PLAYBOOK_GE.md) §3 და §8.\n",
        "RU: [PRICE_RESPONSE_RULES_RU.md](PRICE_RESPONSE_RULES_RU.md)\n",
        "**ნაბიჯი 1:**\n```\n",
        "გამარჯობა [სახელი]! ☕️ სანამ ფასს გეტყვით —\n",
        "სახლისთვის გჭირდებათ თუ ბიზნესისთვის?\n```\n",
        "**ნაბიჯი 2:** ერთი ფასი + სარგებელი + CTA.\n",
    ]
    _write(instructions_dir / "PRICE_RESPONSE_RULES_RU.md", "\n".join(price_ru) + "\n")
    _write(instructions_dir / "PRICE_RESPONSE_RULES_GE.md", "\n".join(price_ge) + "\n")
    _write(
        instructions_dir / "PRICE_RESPONSE_RULES.md",
        "# Перенаправление: ответ на цену\n\n"
        "- [PRICE_RESPONSE_RULES_RU.md](PRICE_RESPONSE_RULES_RU.md)\n"
        "- [PRICE_RESPONSE_RULES_GE.md](PRICE_RESPONSE_RULES_GE.md)\n",
    )

    cta_ru = [
        "# CTA — шпаргалка (RU)\n",
        "Полные правила: [MANAGER_PLAYBOOK_RU.md](MANAGER_PLAYBOOK_RU.md) §4.\n",
        "GE: [CTA_PLAYBOOK_GE.md](CTA_PLAYBOOK_GE.md)\n",
        "| Нельзя | Надо |\n|--------|------|\n",
        "| `მოგვწერეთ ბიუჯეტი` | `გსურთ ხვალ 15:00-ზე ვაკეში გაჩვენოთ?` |\n",
        "| `ნებისმიერ კითხვაზე მოგვმართეთ` | `გსურთ ლინკი გამოგიგზავნოთ ონლაინ შესაძენად?` |\n",
        "| `განიხილავთ ამ ვარიანტს?` | `დავაჯავშნოთ ფასდაკლება 48 საათით?` |\n",
    ]
    cta_ge = [
        "# CTA — შპარგალკა (GE)\n",
        "სრული წესები: [MANAGER_PLAYBOOK_GE.md](MANAGER_PLAYBOOK_GE.md) §4.\n",
        "RU: [CTA_PLAYBOOK_RU.md](CTA_PLAYBOOK_RU.md)\n",
        "| არა | კი |\n|----|-----|\n",
        "| `მოგვწერეთ ბიუჯეტი` | `გსურთ ხვალ 15:00-ზე ვაკეში გაჩვენოთ?` |\n",
        "| `ნებისმიერ კითხვაზე მოგვმართეთ` | `გსურთ ლინკი გამოგიგზავნოთ ონლაინ შესაძენად?` |\n",
        "| `განიხილავთ ამ ვარიანტს?` | `დავაჯავშნოთ ფასდაკლება 48 საათით?` |\n",
    ]
    _write(instructions_dir / "CTA_PLAYBOOK_RU.md", "\n".join(cta_ru) + "\n")
    _write(instructions_dir / "CTA_PLAYBOOK_GE.md", "\n".join(cta_ge) + "\n")
    _write(
        instructions_dir / "CTA_PLAYBOOK.md",
        "# Перенаправление CTA\n\n"
        "- [CTA_PLAYBOOK_RU.md](CTA_PLAYBOOK_RU.md)\n"
        "- [CTA_PLAYBOOK_GE.md](CTA_PLAYBOOK_GE.md)\n",
    )

    summary = [
        "# Сводка анализа переписок\n",
        f"- Источник DOCX (архив): `{settings.input_file.name}`",
        f"- Секций диалогов: {parsed.get('dialogs_count', len(parsed.get('dialogs', [])))}",
        f"- Полный AI-разбор DOCX: **{len(full_analyses)}** диалогов",
        f"- Предупреждения: {', '.join(parsed.get('warnings', [])) or '—'}\n",
        "**Актуальные выводы для инструкций:** CRM с 14.07 — см. `CRM_REPORT_*.md` "
        "и [UPDATE_RULES.md](instructions/UPDATE_RULES.md).\n",
        "## Файлы\n",
        "| Файл | Описание |",
        "|------|----------|",
        "| `output/report_41.json` | Архив DOCX-разбора |",
        "| `output/crm_report_*.json` | Актуальный CRM |\n",
        "## Документация\n",
        "### Инструкции ([instructions/](instructions/))\n",
        "- **[MANAGER_PLAYBOOK_RU.md](instructions/MANAGER_PLAYBOOK_RU.md)** / "
        "**[GE](instructions/MANAGER_PLAYBOOK_GE.md)**",
        "- **[OPERATOR_TRAINING_GUIDE_RU.md](instructions/OPERATOR_TRAINING_GUIDE_RU.md)** / "
        "**[GE](instructions/OPERATOR_TRAINING_GUIDE_GE.md)**",
        "- [UPDATE_RULES.md](instructions/UPDATE_RULES.md)",
        "- CTA/PRICE stubs: `*_RU.md` / `*_GE.md`\n",
        "### Анализ ([analysis/](analysis/))\n",
        "- [BASELINE.md](analysis/BASELINE.md) — активный корпус = CRM с 14.07",
        "- [KNOWLEDGE_BASE.md](analysis/KNOWLEDGE_BASE.md)",
        "- `CRM_REPORT_*.md`\n",
        "См. [SOURCES.md](SOURCES.md).\n",
    ]
    _write(docs_dir / "ANALYSIS_SUMMARY.md", "\n".join(summary) + "\n")

    readme = [
        "# Документация ДимКава Sales Analyzer\n",
        "См. [SOURCES.md](SOURCES.md).\n",
        "Актуальные инструкции — пары **RU / GE** (вручную). ",
        "`--export-docs` не перезаписывает Playbook/Training.\n",
        "## Инструкции\n",
        "| Роль | RU | GE |",
        "|------|----|----|",
        "| Шпаргалка + чеклист | [MANAGER_PLAYBOOK_RU](instructions/MANAGER_PLAYBOOK_RU.md) | "
        "[MANAGER_PLAYBOOK_GE](instructions/MANAGER_PLAYBOOK_GE.md) |",
        "| Обучение | [OPERATOR_TRAINING_GUIDE_RU](instructions/OPERATOR_TRAINING_GUIDE_RU.md) | "
        "[OPERATOR_TRAINING_GUIDE_GE](instructions/OPERATOR_TRAINING_GUIDE_GE.md) |",
        "| Обновление | [UPDATE_RULES](instructions/UPDATE_RULES.md) | — |\n",
        "Оператору: Playbook GE §8 (чеклист).\n",
        "## Анализ\n",
        "- CRM с 14.07: `CRM_REPORT_*.md`, [BASELINE.md](analysis/BASELINE.md)",
        "- [KNOWLEDGE_BASE.md](analysis/KNOWLEDGE_BASE.md) (автоген)\n",
        "## Прочее\n",
        "- [ANALYSIS_SUMMARY.md](ANALYSIS_SUMMARY.md)",
        "- [CHANGELOG.md](../CHANGELOG.md)\n",
    ]

    instructions_readme = [
        "# Инструкции ДимКава — Messenger\n",
        "Пары **RU / GE** — полное зеркало. Оператору GE; тренеру RU.\n",
        "## Кому что читать\n",
        "| Роль | Файл |",
        "|------|------|",
        "| **Оператор** | [MANAGER_PLAYBOOK_GE.md](MANAGER_PLAYBOOK_GE.md) — чеклист §8 |",
        "| **Обучение GE** | [OPERATOR_TRAINING_GUIDE_GE.md](OPERATOR_TRAINING_GUIDE_GE.md) |",
        "| **Тренер RU** | [MANAGER_PLAYBOOK_RU.md](MANAGER_PLAYBOOK_RU.md) + "
        "[OPERATOR_TRAINING_GUIDE_RU.md](OPERATOR_TRAINING_GUIDE_RU.md) |",
        "| Процесс патча | [UPDATE_RULES.md](UPDATE_RULES.md) |",
        "| CTA | [CTA_PLAYBOOK_RU](CTA_PLAYBOOK_RU.md) / [GE](CTA_PLAYBOOK_GE.md) |",
        "| Цена | [PRICE_RESPONSE_RULES_RU](PRICE_RESPONSE_RULES_RU.md) / "
        "[GE](PRICE_RESPONSE_RULES_GE.md) |\n",
        "## CRM\n",
        "- Ежедневно: `run_crm_daily.bat` / `--analyze-crm-yesterday`",
        "- Активный корпус: CRM с 14.07 — [../analysis/BASELINE.md](../analysis/BASELINE.md)\n",
    ]
    _write(instructions_dir / "README.md", "\n".join(instructions_readme) + "\n")
    _write(docs_dir / "README.md", "\n".join(readme) + "\n")

    return docs_dir
