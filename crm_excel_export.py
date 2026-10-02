"""Export CRM analysis to Excel: daily workbook + cumulative summary with charts."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.data_source import StrRef
from openpyxl.chart.text import RichText
from openpyxl.drawing.text import (
    CharacterProperties,
    Paragraph,
    ParagraphProperties,
    RichTextProperties,
)
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from models.crm_schemas import CrmAnalysisReport

SCORE_LABELS: dict[str, str] = {
    "needs_id": "Выявление потребности",
    "objections_handled": "Отработка возражений",
    "value_presented": "Подсветка ценностей",
    "cta": "CTA",
    "deal_closed": "Закрытие сделки",
}

CHECKLIST_LABELS: dict[str, str] = {
    "greeting_contact": "Приветствие и контакт",
    "needs_identified": "Потребность выявлена",
    "context_segmentation": "Сегментация (дом/бизнес)",
    "price_in_context": "Цена в контексте",
    "values_highlighted": "Ценности озвучены",
    "objections_handled": "Возражения отработаны",
    "concrete_cta": "Конкретный CTA",
    "next_step_fixed": "Следующий шаг зафиксирован",
    "no_price_chaos": "Нет ценового хаоса",
    "response_pace_ok": "Темп ответа OK",
}

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT = Font(bold=True, size=14)
SUBTITLE_FONT = Font(bold=True, size=11)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _save_workbook_atomic(wb: Workbook, path: Path, *, retries: int = 3) -> Path:
    """Save workbook via temp file + os.replace; clear error if Excel locks the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.{uuid.uuid4().hex[:8]}.tmp.xlsx")
    last_err: BaseException | None = None
    try:
        for attempt in range(1, retries + 1):
            try:
                wb.save(tmp)
                os.replace(tmp, path)
                return path
            except PermissionError as exc:
                last_err = exc
                if attempt < retries:
                    time.sleep(0.4 * attempt)
                    continue
                raise PermissionError(
                    f"Не удалось записать {path.name}: файл открыт в Excel. "
                    f"Закройте {path.name} и повторите."
                ) from last_err
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    raise RuntimeError(f"Failed to save {path}")  # pragma: no cover


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f} сек"
    if seconds < 3600:
        return f"{seconds / 60:.1f} мин"
    return f"{seconds / 3600:.1f} ч"


def _auto_width(ws, min_w: float = 10, max_w: float = 55) -> None:
    for col_cells in ws.columns:
        letter = get_column_letter(col_cells[0].column)
        length = 0
        for cell in col_cells:
            if cell.value is not None:
                lines = str(cell.value).split("\n")
                length = max(length, max(len(line) for line in lines))
        ws.column_dimensions[letter].width = min(max(length + 2, min_w), max_w)


def _style_header_row(ws, row: int, cols: int) -> None:
    for c in range(1, cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER


def _write_title(ws, title: str, row: int = 1) -> None:
    ws.cell(row=row, column=1, value=title).font = TITLE_FONT


def _build_recommendations(report: CrmAnalysisReport) -> str:
    agg = report.aggregate
    parts: list[str] = []
    needs = agg.avg_scores.get("needs_id", 0)
    cta = agg.avg_scores.get("cta", 0)
    if needs < 3:
        parts.append(
            f"Потребности ({needs}/5): системно не выявляются — "
            "внедрить вопрос «სახლისთვის თუ ბიზნესისთვის?» до цены."
        )
    if cta < 3:
        parts.append(
            f"CTA ({cta}/5): слабое закрытие — "
            "запретить «მოგვწერეთ ბიუჯეტი» без рекомендации."
        )
    rt = agg.response_time
    if getattr(rt, "over_sla_work", 0) and rt.over_sla_work > 0:
        parts.append(
            f"Скорость (рабочее время): {rt.over_sla_work} ответов дольше 2 мин — "
            "настроить уведомления CRM."
        )
    elif rt.over_15min > 0:
        parts.append(
            f"Скорость: {rt.over_15min} ответов дольше 15 мин — "
            "настроить уведомления в CRM."
        )
    low_checklist = [c for c, p in agg.checklist_pass_rate.items() if p < 50]
    if low_checklist:
        parts.append(f"Чеклист: слабые зоны — {', '.join(low_checklist[:5])}.")
    if not parts:
        parts.append("В целом показатели в норме; закрепить лучшие практики.")
    return "\n".join(f"• {p}" for p in parts)


def write_daily_excel(report: CrmAnalysisReport, path: Path) -> Path:
    """Daily workbook with themed tabs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    agg = report.aggregate
    rt = agg.response_time
    date_str = report.meta.target_date

    # --- Сводка ---
    ws = wb.active
    ws.title = "Сводка"
    _write_title(ws, f"CRM-анализ ДимКава — {date_str}")
    rows = [
        ("Дата", date_str),
        ("Диалогов", report.meta.dialogs_count),
        ("Сообщений", report.meta.messages_count),
        ("LLM", f"{report.meta.llm_provider} / {report.meta.model}"),
        ("", ""),
        ("Метрика", "Значение"),
    ]
    for key, label in SCORE_LABELS.items():
        rows.append((label, agg.avg_scores.get(key, "—")))
    rows += [
        ("", ""),
        ("--- Рабочее время (10–18, пн–пт) ---", ""),
        ("Медиана (рабочие сек)", _format_duration(rt.median_work_seconds)),
        ("Среднее (рабочие сек)", _format_duration(rt.avg_work_seconds)),
        ("Ответов в рабочее время", rt.responses_count_work),
        ("Нарушений SLA >2 мин", rt.over_sla_work),
        ("", ""),
        ("--- Вне рабочего времени ---", ""),
        ("Медиана (календарное)", _format_duration(rt.median_off_seconds)),
        ("Среднее (календарное)", _format_duration(rt.avg_off_seconds)),
        ("Ответов вне смены", rt.responses_count_off),
        ("Нарушений SLA >15 мин", rt.over_sla_off),
        ("", ""),
        ("--- Общее (календарное) ---", ""),
        ("Медиана", _format_duration(rt.median_seconds)),
        ("Среднее", _format_duration(rt.avg_seconds)),
        ("Мин", f"{_format_duration(rt.min_seconds)} ({rt.min_dialog or '—'})"),
        ("Макс", f"{_format_duration(rt.max_seconds)} ({rt.max_dialog or '—'})"),
        ("Пауз >15 мин", rt.over_15min),
        ("Пауз >1 ч", rt.over_1hour),
        ("", ""),
        ("--- Телефон → WhatsApp ---", ""),
        ("Попыток запросить номер", agg.phone_attempts_total),
        ("Успехов (номер получен)", agg.phone_successes_total),
        ("Конверсия попыток %", agg.phone_success_rate),
        ("", ""),
        ("RT scope", "Только client msg в день анализа; раб.≤2м / вне≤15м"),
    ]
    for i, (a, b) in enumerate(rows, start=3):
        ws.cell(row=i, column=1, value=a)
        ws.cell(row=i, column=2, value=b)
    ws.cell(row=8, column=1).font = SUBTITLE_FONT
    ws.cell(row=8, column=2).font = SUBTITLE_FONT
    _auto_width(ws, min_w=22, max_w=45)

    # --- Оценки ---
    ws = wb.create_sheet("Оценки")
    ws.append(["Критерий", "Средний балл (0–5)", "Интерпретация"])
    _style_header_row(ws, 1, 3)
    for key, label in SCORE_LABELS.items():
        val = agg.avg_scores.get(key, 0)
        note = "Хорошо" if val >= 3 else ("Средне" if val >= 2 else "Критично")
        ws.append([label, val, note])
    _auto_width(ws)

    # --- Чеклист ---
    ws = wb.create_sheet("Чеклист")
    ws.append(["Критерий", "Прохождение %", "Статус"])
    _style_header_row(ws, 1, 3)
    for crit, label in CHECKLIST_LABELS.items():
        pct = agg.checklist_pass_rate.get(crit, 0)
        status = "OK" if pct >= 50 else "Слабо"
        ws.append([label, pct, status])
    _auto_width(ws)

    # --- Скорость ---
    ws = wb.create_sheet("Скорость")
    ws.append(
        [
            "Клиент", "Платформа", "Ответов",
            "Ср. общее", "Ср. рабоч.", "Ср. вне смены",
            "SLA>2м", "SLA>15м",
        ]
    )
    _style_header_row(ws, 1, 8)
    for d in sorted(report.dialogs, key=lambda x: x.response_time.avg_seconds or 0, reverse=True):
        rt_d = d.response_time
        ws.append([
            d.person_name,
            d.platform,
            rt_d.responses_count,
            _format_duration(rt_d.avg_seconds),
            _format_duration(rt_d.avg_work_seconds),
            _format_duration(rt_d.avg_off_seconds),
            rt_d.over_sla_work,
            rt_d.over_sla_off,
        ])
    ws.append([])
    ws.append([
        "Итого по дню", "", rt.responses_count,
        _format_duration(rt.avg_seconds),
        _format_duration(rt.avg_work_seconds),
        _format_duration(rt.avg_off_seconds),
        rt.over_sla_work,
        rt.over_sla_off,
    ])
    _auto_width(ws)

    # --- Ошибки ---
    ws = wb.create_sheet("Ошибки")
    ws.append(["#", "Ошибка", "Кол-во", "%"])
    _style_header_row(ws, 1, 4)
    for i, item in enumerate(agg.top_errors[:20], 1):
        ws.append([i, item["error"], item["count"], item["percent"]])
    _auto_width(ws, max_w=70)

    # --- Плюсы ---
    ws = wb.create_sheet("Плюсы")
    ws.append(["#", "Сильная сторона", "Кол-во", "%"])
    _style_header_row(ws, 1, 4)
    for i, item in enumerate(agg.top_strengths[:20], 1):
        ws.append([i, item["strength"], item["count"], item["percent"]])
    _auto_width(ws, max_w=70)

    # --- Диалоги ---
    ws = wb.create_sheet("Диалоги")
    headers = [
        "Клиент", "Платформа", "Сообщений",
        "Needs", "Возраж.", "Ценность", "CTA", "Сделка",
        "Суть", "Killer phrase", "Плюсы", "Ошибки",
        "Avg ответ", "Min", "Max",
    ]
    ws.append(headers)
    _style_header_row(ws, 1, len(headers))
    for d in sorted(report.dialogs, key=lambda x: x.person_name):
        sc = d.analysis.scores
        rt_d = d.response_time
        ws.append([
            d.person_name,
            d.platform,
            d.message_count,
            sc.needs_id,
            sc.objections_handled,
            sc.value_presented,
            sc.cta,
            sc.deal_closed,
            d.analysis.summary,
            d.analysis.killer_phrase,
            "\n".join(d.analysis.strengths_found[:5]),
            "\n".join(d.analysis.errors_found[:5]),
            _format_duration(rt_d.avg_seconds),
            _format_duration(rt_d.min_seconds),
            _format_duration(rt_d.max_seconds),
        ])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.alignment = WRAP
    _auto_width(ws, min_w=12, max_w=50)
    ws.column_dimensions["I"].width = 50
    ws.column_dimensions["K"].width = 40
    ws.column_dimensions["L"].width = 40

    # --- Рекомендации ---
    ws = wb.create_sheet("Рекомендации")
    rec_text = _build_recommendations(report)
    ws.cell(row=1, column=1, value="Выводы и рекомендации").font = TITLE_FONT
    ws.cell(row=3, column=1, value=rec_text)
    ws.cell(row=3, column=1).alignment = WRAP
    ws.column_dimensions["A"].width = 90
    ws.append([])
    ws.cell(row=ws.max_row + 2, column=1, value="Сценарий действий для команды").font = SUBTITLE_FONT
    actions = [
        "Утренняя планёрка (15 мин): 2–3 худших диалога по needs и CTA",
        "Правило цены: на «ფასი?» — один вопрос (дом/бизнес), потом цена",
        "Правило CTA: конкретный шаг (время, звонок, ссылка, визит)",
        "Скорость: в рабочее время (10–18) — цель ≤2 мин; вне смены — ≤15 мин",
        "Чеклист: MANAGER_PLAYBOOK_GE.md перед отправкой",
    ]
    r = ws.max_row + 1
    for i, act in enumerate(actions, 1):
        ws.cell(row=r, column=1, value=f"{i}. {act}")
        r += 1

    _save_workbook_atomic(wb, path)
    return path


def load_report_from_json(path: Path) -> CrmAnalysisReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    return CrmAnalysisReport.model_validate(data)


_DAILY_REPORT_RE = re.compile(r"^crm_report_(\d{4}-\d{2}-\d{2})\.json$")


def load_all_daily_reports(output_dir: Path) -> list[CrmAnalysisReport]:
    reports: list[CrmAnalysisReport] = []
    for p in sorted(output_dir.glob("crm_report_*.json")):
        if not _DAILY_REPORT_RE.match(p.name):
            continue
        try:
            reports.append(load_report_from_json(p))
        except Exception:
            continue
    reports.sort(key=lambda r: r.meta.target_date)
    return reports


def load_daily_reports_in_range(
    output_dir: Path,
    date_from: str,
    date_to: str,
) -> list[CrmAnalysisReport]:
    reports = load_all_daily_reports(output_dir)
    return [r for r in reports if date_from <= r.meta.target_date <= date_to]


CHECKLIST_CRITICAL_KEYS = (
    "needs_identified",
    "price_in_context",
    "concrete_cta",
    "next_step_fixed",
)
CHECKLIST_SUPPORT_KEYS = (
    "values_highlighted",
    "objections_handled",
    "greeting_contact",
    "response_pace_ok",
    "no_price_chaos",
    "context_segmentation",
)

# Guide rows for sheet «Как читать»: #, title, why, what_to_watch, coaching_link, trap
ANALYTICS_CHART_GUIDE: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "1",
        "Needs + CTA + Deal",
        "Воронка качества диалога: понял ли потребность → дал ли конкретный шаг → закрыл ли сделку.",
        "Линии балл 0–5 по дням. Рост Needs до цены и CTA после тренинга — главный сигнал.",
        "После обучения «вопрос до цены» и жёсткого CTA смотрите Needs и CTA; Deal — отложенный эффект.",
        "Один «хороший» день при 5 диалогах ≠ тренд. Смотрите MA7 рядом.",
    ),
    (
        "2",
        "Возражения + Ценности",
        "Эффект обучения по отработке возражений и подсветке ценностей (value-selling).",
        "Две линии scores: objections_handled и value_presented.",
        "Тренинг по возражениям → линия возражений; тренинг ценностей → value_presented + чеклист values %. ",
        "Не смешивайте с Needs/CTA на одном графике — разные навыки.",
    ),
    (
        "3",
        "MA7: Needs + CTA + Deal",
        "Сглаживание шума: среднее за до 7 дней по тем же scores.",
        "Если день скачет вверх/вниз, а MA7 растёт 5–7 дней — попытки обучения работают.",
        "Используйте на планёрке как «честный» тренд после недели практики.",
        "MA7 запаздывает: резкий провал вчера ещё не виден полностью.",
    ),
    (
        "4",
        "MA7: Возражения + Ценности",
        "То же сглаживание для двух направлений коучинга.",
        "Сравнивайте MA7 до и после недели обучения по теме.",
        "После фокуса на возражениях/ценностях — этот график, не общий overview.",
        "При короткой серии (<7 дней) MA7 = среднее по всем имеющимся дням.",
    ),
    (
        "5",
        "Чеклист критичный %",
        "Процесс сделки: потребность → цена в контексте → конкретный CTA → следующий шаг.",
        "Четыре % прохождения чеклиста по дням (не балл LLM).",
        "Провал на price_in_context при высоком Needs = «цена-молчание». Провал CTA/next_step = слабое закрытие.",
        "% ≠ балл score: чеклист бинарный по диалогам, score — средняя оценка.",
    ),
    (
        "6",
        "Чеклист поддержка %",
        "Опоры качества: приветствие, ценности, возражения, темп, нет ценового хаоса, сегментация.",
        "Шесть % по дням — «гигиена» диалога.",
        "После обучения по ценностям смотрите values_highlighted % вместе со score value_presented.",
        "Не все 6 должны расти сразу — берите 1–2 фокуса на спринт.",
    ),
    (
        "7",
        "SLA % + медиана раб. мин",
        "Скорость ответа: доля соблюдения SLA и типичное время в рабочие часы.",
        "SLA раб.% / вне % — ↑ лучше; медиана раб. мин — ↓ лучше. Идеал: %↑ и медиана↓ вместе.",
        "После настройки уведомлений CRM / смены смены — этот блок.",
        "Рост SLA% при росте медианы = меньше грубых нарушений, но всё ещё медленно.",
    ),
    (
        "8",
        "Воронка качества %",
        "Здоровье этапов: needs → price → CTA → next step → Deal% (deal×20).",
        "Линии на одной шкале 0–100. Узкое место — этап, который заметно ниже предыдущего.",
        "Планёрка: «где рвётся воронка» → тема обучения на неделю.",
        "Deal% — proxy, не деньги CRM; не путать с выручкой.",
    ),
    (
        "9",
        "Диалогов / день",
        "Контекст объёма: сколько диалогов попало в анализ.",
        "Пики и провалы рядом с графиками качества.",
        "Не сравнивайте качество дня с 5 диалогами и дня с 40 без оглядки на объём.",
        "Малый объём → шумные scores; опирайтесь на MA7.",
    ),
)


def _trend_arrow(current: float, previous: float | None, higher_is_better: bool = True) -> str:
    if previous is None:
        return "—"
    diff = current - previous
    if abs(diff) < 0.05:
        return "→"
    if higher_is_better:
        return "↑" if diff > 0 else "↓"
    return "↓" if diff > 0 else "↑"


def _sla_compliance_pct(over: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (1.0 - over / total))), 1)


def _moving_average(values: list[float], idx: int, window: int = 7) -> float:
    start = max(0, idx - window + 1)
    chunk = values[start : idx + 1]
    if not chunk:
        return 0.0
    return round(sum(chunk) / len(chunk), 2)


def _add_line_chart(
    ws_charts,
    ws_data,
    *,
    title: str,
    y_title: str,
    col_indexes: list[int],
    n_rows: int,
    anchor: str,
    style: int = 10,
    width: float = 18,
    height: float = 9,
) -> None:
    """col_indexes are 1-based columns on ws_data (row 1 = headers).

    One series per column; dates (col A) are categories on the X axis — never
    legend entries. Avoid Excel style 16+ which often enables «vary colors by
    point» and puts every date into the legend.
    """
    if n_rows < 1 or not col_indexes:
        return
    # Styles 10–12 keep a single color per series; 16+ confuses line charts.
    safe_style = style if style <= 12 else 10
    chart = LineChart()
    chart.title = title
    chart.y_axis.title = y_title
    chart.x_axis.title = "День"
    chart.style = safe_style
    chart.width = width
    chart.height = height
    chart.varyColors = False
    chart.grouping = "standard"

    cats = Reference(ws_data, min_col=1, min_row=2, max_row=n_rows + 1)
    # Prefer one contiguous block when columns are adjacent (correct series/cats).
    ordered = sorted(set(col_indexes))
    contiguous = ordered == list(range(ordered[0], ordered[-1] + 1))
    if contiguous and len(ordered) == len(col_indexes):
        data = Reference(
            ws_data,
            min_col=ordered[0],
            min_row=1,
            max_col=ordered[-1],
            max_row=n_rows + 1,
        )
        chart.add_data(data, titles_from_data=True, from_rows=False)
    else:
        for col in col_indexes:
            data = Reference(
                ws_data,
                min_col=col,
                min_row=1,
                max_col=col,
                max_row=n_rows + 1,
            )
            chart.add_data(data, titles_from_data=True, from_rows=False)
    chart.set_categories(cats)

    # Force string categories so Excel does not reinterpret text dates via numRef.
    for ser in chart.series:
        if ser.cat is not None and ser.cat.numRef is not None:
            formula = ser.cat.numRef.f
            ser.cat.numRef = None
            ser.cat.strRef = StrRef(f=formula)

    chart.x_axis.tickLblPos = "nextTo"
    chart.x_axis.delete = False
    # Rotate category labels (~−45°) so all dates remain readable.
    chart.x_axis.txPr = RichText(
        bodyPr=RichTextProperties(rot=-2700000, upright=False),
        p=[Paragraph(pPr=ParagraphProperties(defRPr=CharacterProperties(sz=800)))],
    )
    if len(col_indexes) == 1:
        chart.legend = None
    ws_charts.add_chart(chart, anchor)


def _window_avg_score(reports: list[CrmAnalysisReport], keys: list[str], start: int, end: int) -> float:
    chunk = reports[start:end]
    if not chunk or not keys:
        return 0.0
    vals: list[float] = []
    for r in chunk:
        for k in keys:
            vals.append(float(r.aggregate.avg_scores.get(k, 0) or 0))
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def _window_avg_sla_work(reports: list[CrmAnalysisReport], start: int, end: int) -> float:
    chunk = reports[start:end]
    if not chunk:
        return 0.0
    vals = [
        _sla_compliance_pct(r.aggregate.response_time.over_sla_work, r.aggregate.response_time.responses_count_work)
        for r in chunk
    ]
    return round(sum(vals) / len(vals), 1)


def _trend_word(delta: float, *, flat: float = 0.05) -> str:
    if abs(delta) < flat:
        return "плоско"
    return "растёт" if delta > 0 else "падает"


def _build_period_snapshot(reports: list[CrmAnalysisReport]) -> list[tuple[str, str]]:
    """Auto snapshot rows for sheet «Как читать» from loaded daily reports."""
    if not reports:
        return [("Период", "нет данных")]
    n = len(reports)
    date_from = reports[0].meta.target_date
    date_to = reports[-1].meta.target_date
    dialogs = sum(r.meta.dialogs_count for r in reports)
    focus_keys = ["needs_id", "value_presented", "objections_handled", "cta"]
    w = min(7, n)
    first_scores = _window_avg_score(reports, focus_keys, 0, w)
    last_scores = _window_avg_score(reports, focus_keys, n - w, n)
    first_sla = _window_avg_sla_work(reports, 0, w)
    last_sla = _window_avg_sla_work(reports, n - w, n)

    score_series = {
        k: [float(r.aggregate.avg_scores.get(k, 0) or 0) for r in reports]
        for k in focus_keys
    }
    ma7_first = round(
        sum(_moving_average(score_series[k], w - 1, 7) for k in focus_keys) / len(focus_keys),
        2,
    )
    ma7_last = round(
        sum(_moving_average(score_series[k], n - 1, 7) for k in focus_keys) / len(focus_keys),
        2,
    )
    conclusion = (
        f"Качество (MA7 Needs/Value/Obj/CTA): {_trend_word(ma7_last - ma7_first)} "
        f"({ma7_first} → {ma7_last}). "
        f"SLA раб.%: {_trend_word(last_sla - first_sla, flat=1.0)} "
        f"({first_sla}% → {last_sla}%)."
    )
    return [
        ("Период", f"{date_from} … {date_to} ({n} дн.)"),
        ("Диалогов всего", str(dialogs)),
        ("Avg scores первые 7 дн.", str(first_scores)),
        ("Avg scores последние 7 дн.", str(last_scores)),
        ("SLA раб.% первые 7 дн.", f"{first_sla}%"),
        ("SLA раб.% последние 7 дн.", f"{last_sla}%"),
        ("MA7 качество (старт окна)", str(ma7_first)),
        ("MA7 качество (конец)", str(ma7_last)),
        ("Короткий вывод", conclusion),
    ]


def _write_howto_sheet(wb: Workbook, reports: list[CrmAnalysisReport]) -> None:
    """Sheet «Как читать»: intro + auto snapshot + per-chart guide."""
    ws = wb.create_sheet("Как читать")
    ws.cell(row=1, column=1, value="Как читать CRM_SUMMARY — гайд для новичков").font = TITLE_FONT

    intro_lines = [
        "Этот файл измеряет качество ответов операторов ДимКава в CRM Messenger "
        "(оценки 0–5, чеклист %, скорость ответа).",
        "Лист «Графики» — краткий обзор за все дни. Лист «Аналитика» — тренды по направлениям обучения.",
        "Правило стрелок: ↑ лучше для scores, checklist % и SLA%; ↓ лучше для медианы ответа (минуты).",
        "MA7 — скользящее среднее за до 7 дней. SLA% = 100×(1 − нарушения/ответы). Deal% = deal_closed×20 (не выручка).",
        "Снимок ниже пересчитывается при каждом --export-crm-excel из уже сохранённых дневных JSON.",
        "Скорость (SLA/медианы): только ответы на сообщения клиентов в день анализа; "
        "рабочее время ≤2 мин (рабочие сек), вне смены ≤15 мин (календарные).",
        "Телефон→WhatsApp: попытки менеджера за день и успехи (номер/контакт от клиента).",
    ]
    row = 3
    ws.cell(row=row, column=1, value="A. Зачем этот файл").font = SUBTITLE_FONT
    row += 1
    for line in intro_lines:
        cell = ws.cell(row=row, column=1, value=line)
        cell.alignment = WRAP
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        ws.row_dimensions[row].height = 30
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="B. Снимок по текущему корпусу (авто)").font = SUBTITLE_FONT
    row += 1
    ws.cell(row=row, column=1, value="Поле")
    ws.cell(row=row, column=2, value="Значение")
    _style_header_row(ws, row, 2)
    row += 1
    for label, value in _build_period_snapshot(reports):
        ws.cell(row=row, column=1, value=label)
        cell = ws.cell(row=row, column=2, value=value)
        cell.alignment = WRAP
        if label == "Короткий вывод":
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
            ws.row_dimensions[row].height = 40
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="C. Карточки графиков листа «Аналитика»").font = SUBTITLE_FONT
    row += 1
    headers = ["#", "График", "Зачем", "Что смотреть", "Связь с обучением", "Ловушка"]
    for c, h in enumerate(headers, 1):
        ws.cell(row=row, column=c, value=h)
    _style_header_row(ws, row, len(headers))
    row += 1
    for num, title, why, watch, coaching, trap in ANALYTICS_CHART_GUIDE:
        values = (num, title, why, watch, coaching, trap)
        for c, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=c, value=val)
            cell.alignment = WRAP
        ws.row_dimensions[row].height = 55
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="D. Лист «Графики» (краткий обзор)").font = SUBTITLE_FONT
    row += 1
    overview = [
        "1) Все 5 scores на одном графике — быстрый взгляд «всё ли в порядке», без разбора направлений.",
        "2) Медиана ответа общее vs рабочее (мин) — скорость; ↓ лучше.",
        "3) Столбцы чеклиста последнего дня — снимок «вчера», не тренд (тренд — на «Аналитика»).",
        "Символы ↑ ↓ → — на листе «По дням» сравнивают день с предыдущим.",
    ]
    for line in overview:
        cell = ws.cell(row=row, column=1, value=line)
        cell.alignment = WRAP
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        ws.row_dimensions[row].height = 28
        row += 1

    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 42
    ws.column_dimensions["D"].width = 42
    ws.column_dimensions["E"].width = 42
    ws.column_dimensions["F"].width = 38


def write_master_excel(reports: list[CrmAnalysisReport], path: Path) -> Path:
    """Cumulative workbook: daily table + trend charts + coaching analytics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    score_keys = list(SCORE_LABELS.keys())
    checklist_keys = list(CHECKLIST_LABELS.keys())

    score_series: dict[str, list[float]] = {
        k: [float(r.aggregate.avg_scores.get(k, 0) or 0) for r in reports]
        for k in score_keys
    }

    # --- По дням ---
    ws = wb.active
    ws.title = "По дням"
    headers = [
        "Дата", "Диалогов", "Сообщений",
        *SCORE_LABELS.values(),
        "Медиана общ. (сек)", "Медиана раб. (сек)", "SLA>2м", "SLA>15м вне смены",
        "Пауз >15м", "Пауз >1ч",
        "SLA раб. %", "SLA вне %",
        "Тел. попытки", "Тел. успех", "Тел. %",
        *[f"{CHECKLIST_LABELS[k]} %" for k in checklist_keys],
    ]
    for key in score_keys:
        headers.append(f"Δ {SCORE_LABELS[key][:12]}")
    ws.append(headers)
    _style_header_row(ws, 1, len(headers))

    prev_scores: dict[str, float] | None = None
    for report in reports:
        agg = report.aggregate
        rt = agg.response_time
        row: list[Any] = [
            report.meta.target_date,
            report.meta.dialogs_count,
            report.meta.messages_count,
        ]
        for key in score_keys:
            row.append(agg.avg_scores.get(key, 0))
        row += [
            rt.median_seconds or 0,
            rt.median_work_seconds or 0,
            rt.over_sla_work,
            rt.over_sla_off,
            rt.over_15min,
            rt.over_1hour,
            _sla_compliance_pct(rt.over_sla_work, rt.responses_count_work),
            _sla_compliance_pct(rt.over_sla_off, rt.responses_count_off),
            agg.phone_attempts_total,
            agg.phone_successes_total,
            agg.phone_success_rate,
        ]
        for key in checklist_keys:
            row.append(agg.checklist_pass_rate.get(key, 0))
        for key in score_keys:
            cur = float(agg.avg_scores.get(key, 0) or 0)
            prev = prev_scores.get(key) if prev_scores else None
            row.append(_trend_arrow(cur, prev, higher_is_better=True))
        ws.append(row)
        prev_scores = {k: float(agg.avg_scores.get(k, 0) or 0) for k in score_keys}

    _auto_width(ws)

    # --- Динамика ---
    # 1 Дата | 2-6 scores | 7-8 med | 9 dialogs | 10-11 SLA% | 12-21 checklist | 22 Deal% | 23-27 MA7
    ws_dyn = wb.create_sheet("Динамика")
    dyn_headers = (
        ["Дата"]
        + list(SCORE_LABELS.values())
        + [
            "Медиана общ. (мин)",
            "Медиана раб. (мин)",
            "Диалогов",
            "SLA раб. %",
            "SLA вне %",
            "Тел. попытки",
            "Тел. успех",
            "Тел. %",
        ]
        + [f"{CHECKLIST_LABELS[k]} %" for k in checklist_keys]
        + ["Deal %"]
        + [f"MA7 {SCORE_LABELS[k]}" for k in score_keys]
    )
    ws_dyn.append(dyn_headers)
    _style_header_row(ws_dyn, 1, len(dyn_headers))

    for i, report in enumerate(reports):
        agg = report.aggregate
        rt = agg.response_time
        row = [report.meta.target_date]
        for key in score_keys:
            row.append(agg.avg_scores.get(key, 0))
        row += [
            round((rt.median_seconds or 0) / 60, 1),
            round((rt.median_work_seconds or 0) / 60, 1),
            report.meta.dialogs_count,
            _sla_compliance_pct(rt.over_sla_work, rt.responses_count_work),
            _sla_compliance_pct(rt.over_sla_off, rt.responses_count_off),
            agg.phone_attempts_total,
            agg.phone_successes_total,
            agg.phone_success_rate,
        ]
        for key in checklist_keys:
            row.append(agg.checklist_pass_rate.get(key, 0))
        row.append(round(float(agg.avg_scores.get("deal_closed", 0) or 0) * 20, 1))
        for key in score_keys:
            row.append(_moving_average(score_series[key], i, 7))
        ws_dyn.append(row)
    _auto_width(ws_dyn)

    n = len(reports)
    col = {
        "needs": 2,
        "objections": 3,
        "value": 4,
        "cta": 5,
        "deal": 6,
        "med": 7,
        "med_work": 8,
        "dialogs": 9,
        "sla_work": 10,
        "sla_off": 11,
        "phone_att": 12,
        "phone_ok": 13,
        "phone_pct": 14,
    }
    chk_start = 15
    chk_col = {k: chk_start + i for i, k in enumerate(checklist_keys)}
    deal_pct_col = chk_start + len(checklist_keys)
    ma7_start = deal_pct_col + 1
    ma7_col = {k: ma7_start + i for i, k in enumerate(score_keys)}

    # --- Графики ---
    ws_ch = wb.create_sheet("Графики")
    ws_ch.cell(row=1, column=1, value="Краткий обзор (детали → лист «Аналитика»)").font = TITLE_FONT
    if n >= 1:
        _add_line_chart(
            ws_ch, ws_dyn,
            title="Средние оценки по дням",
            y_title="Балл (0–5)",
            col_indexes=[col["needs"], col["objections"], col["value"], col["cta"], col["deal"]],
            n_rows=n, anchor="A3", style=10,
        )
        _add_line_chart(
            ws_ch, ws_dyn,
            title="Медиана ответа: общее vs рабочее (мин) — ↓ лучше",
            y_title="Минуты",
            col_indexes=[col["med"], col["med_work"]],
            n_rows=n, anchor="A22", style=11, height=8,
        )
        last = reports[-1]
        ws_ch.cell(row=40, column=1, value=f"Чеклист — {last.meta.target_date}").font = SUBTITLE_FONT
        chk_start_row = 41
        ws_ch.cell(row=chk_start_row, column=1, value="Критерий")
        ws_ch.cell(row=chk_start_row, column=2, value="%")
        for i, (crit, label) in enumerate(CHECKLIST_LABELS.items(), 1):
            ws_ch.cell(row=chk_start_row + i, column=1, value=label)
            ws_ch.cell(
                row=chk_start_row + i, column=2,
                value=last.aggregate.checklist_pass_rate.get(crit, 0),
            )
        bar = BarChart()
        bar.type = "bar"
        bar.title = "Чеклист последнего дня"
        bar.y_axis.title = "%"
        bar.width = 16
        bar.height = 12
        data_bar = Reference(
            ws_ch, min_col=2, min_row=chk_start_row,
            max_row=chk_start_row + len(CHECKLIST_LABELS),
        )
        cats_bar = Reference(
            ws_ch, min_col=1, min_row=chk_start_row + 1,
            max_row=chk_start_row + len(CHECKLIST_LABELS),
        )
        bar.add_data(data_bar, titles_from_data=True)
        bar.set_categories(cats_bar)
        ws_ch.add_chart(bar, "D40")

    # --- Аналитика ---
    ws_an = wb.create_sheet("Аналитика")
    ws_an.cell(row=1, column=1, value="Аналитика улучшений — тренды по направлениям коучинга").font = TITLE_FONT
    tip = ws_an.cell(
        row=2, column=1,
        value=(
            "↑ лучше для scores / checklist % / SLA%. "
            "↓ лучше для медианы ответа. "
            "MA7 — сглаживание за 7 дней: если день скачет, а MA7 растёт — попытки работают. "
            "Подробно: лист «Как читать»."
        ),
    )
    tip.alignment = WRAP
    ws_an.merge_cells("A2:H2")
    ws_an.row_dimensions[2].height = 36

    if n >= 1:
        for row_i, text in [
            (3, "1. Качество: Needs + CTA + Deal (↑)"),
            (20, "2. Направления обучения: Возражения + Ценности (↑)"),
            (37, "3. Сглаживание MA7: Needs/CTA/Deal (↑)"),
            (54, "4. Сглаживание MA7: Возражения + Ценности (↑)"),
            (71, "5. Процесс критичный: needs / price / CTA / next step % (↑)"),
            (88, "6. Процесс поддержка: ценности, возражения, greeting, pace… (↑)"),
            (105, "7. Скорость: SLA раб.% / вне % (↑) и медиана раб. мин (↓)"),
            (122, "8. Воронка качества %: needs → price → CTA → next step → Deal% (↑)"),
            (139, "9. Объём диалогов/день (контекст шума)"),
        ]:
            ws_an.cell(row=row_i, column=1, value=text).font = SUBTITLE_FONT

        _add_line_chart(
            ws_an, ws_dyn, title="Needs + CTA + Deal", y_title="Балл (0–5)",
            col_indexes=[col["needs"], col["cta"], col["deal"]],
            n_rows=n, anchor="A4", style=10,
        )
        _add_line_chart(
            ws_an, ws_dyn, title="Отработка возражений + Подсветка ценностей",
            y_title="Балл (0–5)",
            col_indexes=[col["objections"], col["value"]],
            n_rows=n, anchor="A21", style=12,
        )
        _add_line_chart(
            ws_an, ws_dyn, title="MA7: Needs + CTA + Deal", y_title="Балл MA7",
            col_indexes=[ma7_col["needs_id"], ma7_col["cta"], ma7_col["deal_closed"]],
            n_rows=n, anchor="A38", style=10,
        )
        _add_line_chart(
            ws_an, ws_dyn, title="MA7: Возражения + Ценности", y_title="Балл MA7",
            col_indexes=[ma7_col["objections_handled"], ma7_col["value_presented"]],
            n_rows=n, anchor="A55", style=12,
        )
        _add_line_chart(
            ws_an, ws_dyn, title="Чеклист критичный %", y_title="%",
            col_indexes=[chk_col[k] for k in CHECKLIST_CRITICAL_KEYS],
            n_rows=n, anchor="A72", style=10,
        )
        _add_line_chart(
            ws_an, ws_dyn, title="Чеклист поддержка %", y_title="%",
            col_indexes=[chk_col[k] for k in CHECKLIST_SUPPORT_KEYS],
            n_rows=n, anchor="A89", style=12,
        )
        _add_line_chart(
            ws_an, ws_dyn,
            title="SLA compliance % (↑) + медиана раб. мин (↓)",
            y_title="% / мин",
            col_indexes=[col["sla_work"], col["sla_off"], col["med_work"]],
            n_rows=n, anchor="A106", style=11,
        )
        _add_line_chart(
            ws_an, ws_dyn, title="Воронка качества %", y_title="%",
            col_indexes=[
                chk_col["needs_identified"],
                chk_col["price_in_context"],
                chk_col["concrete_cta"],
                chk_col["next_step_fixed"],
                deal_pct_col,
            ],
            n_rows=n, anchor="A123", style=10,
        )
        _add_line_chart(
            ws_an, ws_dyn, title="Объём: диалогов в день", y_title="Диалогов",
            col_indexes=[col["dialogs"]],
            n_rows=n, anchor="A140", style=10, height=9,
        )
        _add_line_chart(
            ws_an, ws_dyn, title="Телефон → WhatsApp: попытки и успехи",
            y_title="Кол-во",
            col_indexes=[col["phone_att"], col["phone_ok"]],
            n_rows=n, anchor="A157", style=11, height=8,
        )

    # --- Как читать ---
    _write_howto_sheet(wb, reports)

    _save_workbook_atomic(wb, path)
    return path


def write_period_excel(
    period_report: CrmAnalysisReport,
    daily_reports: list[CrmAnalysisReport],
    path: Path,
) -> Path:
    """Period summary workbook."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    agg = period_report.aggregate
    rt = agg.response_time
    date_from = period_report.meta.date_from or period_report.meta.target_date
    date_to = period_report.meta.date_to or period_report.meta.target_date

    ws = wb.active
    ws.title = "Итог периода"
    _write_title(ws, f"CRM — период {date_from} … {date_to}")
    rows = [
        ("Период", f"{date_from} — {date_to}"),
        ("Дней", period_report.meta.days_in_period or len(daily_reports)),
        ("Диалогов", period_report.meta.dialogs_count),
        ("Сообщений", period_report.meta.messages_count),
        ("", ""),
    ]
    for key, label in SCORE_LABELS.items():
        rows.append((label, agg.avg_scores.get(key, "—")))
    rows += [
        ("", ""),
        ("Медиана раб. (сек)", _format_duration(rt.median_work_seconds)),
        ("SLA>2 мин (рабочее)", rt.over_sla_work),
        ("SLA>15 мин (вне смены)", rt.over_sla_off),
        ("Медиана общ. (сек)", _format_duration(rt.median_seconds)),
    ]
    for i, (a, b) in enumerate(rows, start=3):
        ws.cell(row=i, column=1, value=a)
        ws.cell(row=i, column=2, value=b)
    _auto_width(ws, min_w=28, max_w=50)

    ws_days = wb.create_sheet("По дням")
    headers = ["Дата", "Диалогов"] + list(SCORE_LABELS.values()) + [
        "Мед. раб.", "SLA>2м", "Мед. общ.", "CTA %",
    ]
    ws_days.append(headers)
    _style_header_row(ws_days, 1, len(headers))
    for report in daily_reports:
        a = report.aggregate
        r = a.response_time
        ws_days.append([
            report.meta.target_date,
            report.meta.dialogs_count,
            *[a.avg_scores.get(k, 0) for k in SCORE_LABELS],
            _format_duration(r.median_work_seconds),
            r.over_sla_work,
            _format_duration(r.median_seconds),
            a.checklist_pass_rate.get("concrete_cta", 0),
        ])
    _auto_width(ws_days)

    ws_sp = wb.create_sheet("Скорость")
    ws_sp.append([
        "Дата", "Ответов", "Мед. раб.", "SLA>2м", "Мед. вне смены", "SLA>15м",
        "Мед. общ.", "Пауз >15м", "Пауз >1ч",
    ])
    _style_header_row(ws_sp, 1, 9)
    for report in daily_reports:
        r = report.aggregate.response_time
        ws_sp.append([
            report.meta.target_date,
            r.responses_count,
            _format_duration(r.median_work_seconds),
            r.over_sla_work,
            _format_duration(r.median_off_seconds),
            r.over_sla_off,
            _format_duration(r.median_seconds),
            r.over_15min,
            r.over_1hour,
        ])
    ws_sp.append([
        "ИТОГО", rt.responses_count,
        _format_duration(rt.median_work_seconds), rt.over_sla_work,
        _format_duration(rt.median_off_seconds), rt.over_sla_off,
        _format_duration(rt.median_seconds), rt.over_15min, rt.over_1hour,
    ])
    _auto_width(ws_sp)

    ws_err = wb.create_sheet("Ошибки недели")
    ws_err.append(["#", "Ошибка", "Кол-во", "%"])
    _style_header_row(ws_err, 1, 4)
    for i, item in enumerate(agg.top_errors[:25], 1):
        ws_err.append([i, item["error"], item["count"], item["percent"]])
    _auto_width(ws_err, max_w=70)

    ws_plus = wb.create_sheet("Плюсы недели")
    ws_plus.append(["#", "Сильная сторона", "Кол-во", "%"])
    _style_header_row(ws_plus, 1, 4)
    for i, item in enumerate(agg.top_strengths[:25], 1):
        ws_plus.append([i, item["strength"], item["count"], item["percent"]])
    _auto_width(ws_plus, max_w=70)

    if len(daily_reports) >= 1:
        ws_dyn = wb.create_sheet("Динамика")
        ws_dyn.append(["Дата"] + list(SCORE_LABELS.values()) + ["Мед. раб. (мин)", "Мед. общ. (мин)"])
        _style_header_row(ws_dyn, 1, 2 + len(SCORE_LABELS) + 2)
        for report in daily_reports:
            a = report.aggregate
            r = a.response_time
            ws_dyn.append([
                report.meta.target_date,
                *[a.avg_scores.get(k, 0) for k in SCORE_LABELS],
                round((r.median_work_seconds or 0) / 60, 1),
                round((r.median_seconds or 0) / 60, 1),
            ])
        ws_ch = wb.create_sheet("Графики")
        ws_ch.cell(row=1, column=1, value="Динамика за период").font = TITLE_FONT
        n = len(daily_reports)
        chart = LineChart()
        chart.title = "Оценки по дням"
        chart.width = 18
        chart.height = 10
        cats = Reference(ws_dyn, min_col=1, min_row=2, max_row=n + 1)
        for col_offset, key in enumerate(SCORE_LABELS.keys(), start=2):
            data = Reference(ws_dyn, min_col=col_offset, min_row=1, max_row=n + 1)
            chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        ws_ch.add_chart(chart, "A3")

    _save_workbook_atomic(wb, path)
    return path


def export_crm_excel(report: CrmAnalysisReport, excel_dir: Path) -> dict[str, str]:
    """Write daily + update master summary.

    Master failure after a successful daily write is not swallowed — callers see
    PermissionError with a clear «close Excel» message.
    """
    date_str = report.meta.target_date
    daily_path = excel_dir / f"CRM_DAILY_{date_str}.xlsx"
    master_path = excel_dir / "CRM_SUMMARY.xlsx"

    write_daily_excel(report, daily_path)

    by_date = {r.meta.target_date: r for r in load_all_daily_reports(excel_dir.parent)}
    by_date[report.meta.target_date] = report
    all_reports = sorted(by_date.values(), key=lambda r: r.meta.target_date)
    write_master_excel(all_reports, master_path)

    from crm_mobile_export import export_crm_mobile

    # excel_dir = <project>/output/crm_excel → docs live at <project>/docs/analysis
    docs_dir = excel_dir.parent.parent / "docs" / "analysis"
    mobile_paths = export_crm_mobile(all_reports, docs_dir, focus_date=date_str)

    result = {"daily": str(daily_path), "master": str(master_path)}
    result.update({f"mobile_{k}": v for k, v in mobile_paths.items()})
    return result


def export_excel_from_existing_json(
    output_dir: Path,
    target_date: str | None = None,
) -> dict[str, str]:
    """Rebuild Excel from saved JSON without LLM."""
    excel_dir = output_dir / "crm_excel"
    if target_date:
        json_path = output_dir / f"crm_report_{target_date}.json"
        if not json_path.exists():
            raise FileNotFoundError(json_path)
        report = load_report_from_json(json_path)
        return export_crm_excel(report, excel_dir)

    all_reports = load_all_daily_reports(output_dir)
    if not all_reports:
        raise FileNotFoundError(f"No crm_report_*.json in {output_dir}")
    paths: dict[str, str] = {}
    for report in all_reports:
        paths = export_crm_excel(report, excel_dir)
    master_path = excel_dir / "CRM_SUMMARY.xlsx"
    write_master_excel(all_reports, master_path)
    paths["master"] = str(master_path)
    return paths
