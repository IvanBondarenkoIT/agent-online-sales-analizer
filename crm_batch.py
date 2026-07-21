"""Batch CRM analysis: main run for calendar week or custom period."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import Settings, setup_logging
from crm_analysis import (
    aggregate_crm_results,
    compute_channel_response_times,
    find_jsonl_for_date,
    load_channels_from_jsonl,
    recalc_response_times_in_report,
    run_crm_analysis,
)
from crm_excel_export import (
    export_crm_excel,
    load_daily_reports_in_range,
    load_report_from_json,
    write_period_excel,
)
from crm_response_time import ResponsePairMetrics, WorkSchedule, build_response_time_stats
from models.crm_schemas import CrmAnalysisReport, CrmDialogReport, CrmReportMeta

logger = logging.getLogger("dimkava.crm_batch")


@dataclass
class PeriodRunResult:
    date_from: date
    date_to: date
    days_analyzed: list[str] = field(default_factory=list)
    days_skipped: list[str] = field(default_factory=list)
    days_failed: list[str] = field(default_factory=list)
    period_json: str | None = None
    period_md: str | None = None
    period_excel: str | None = None


def daterange(date_from: date, date_to: date) -> list[date]:
    days: list[date] = []
    cur = date_from
    while cur <= date_to:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def previous_calendar_week(today: date | None = None) -> tuple[date, date]:
    """Monday–Sunday of the week before `today`'s week."""
    if today is None:
        today = date.today()
    start_of_this_week = today - timedelta(days=today.weekday())
    end_prev = start_of_this_week - timedelta(days=1)
    start_prev = end_prev - timedelta(days=6)
    return start_prev, end_prev


def _daily_report_path(output_dir: Path, d: date) -> Path:
    return output_dir / f"crm_report_{d.isoformat()}.json"


def _collect_period_pairs(
    settings: Settings,
    dates: list[date],
    schedule: WorkSchedule,
) -> list[ResponsePairMetrics]:
    all_pairs: list[ResponsePairMetrics] = []
    for d in dates:
        jsonl = find_jsonl_for_date(settings.output_dir, d)
        if not jsonl:
            continue
        for ch in load_channels_from_jsonl(jsonl).values():
            pairs, _ = compute_channel_response_times(ch, schedule)
            all_pairs.extend(pairs)
    return all_pairs


def build_period_report(
    settings: Settings,
    daily_reports: list[CrmAnalysisReport],
    date_from: date,
    date_to: date,
) -> CrmAnalysisReport:
    schedule = WorkSchedule.from_settings(settings)
    all_dialogs: list[CrmDialogReport] = []
    total_messages = 0
    daily_summaries: list[dict[str, Any]] = []

    for dr in daily_reports:
        all_dialogs.extend(dr.dialogs)
        total_messages += dr.meta.messages_count
        daily_summaries.append({
            "target_date": dr.meta.target_date,
            "dialogs_count": dr.meta.dialogs_count,
            "messages_count": dr.meta.messages_count,
            "avg_scores": dr.aggregate.avg_scores,
            "checklist_pass_rate": dr.aggregate.checklist_pass_rate,
            "response_time": dr.aggregate.response_time.model_dump(),
        })

    dates = [date.fromisoformat(r.meta.target_date) for r in daily_reports]
    all_pairs = _collect_period_pairs(settings, dates, schedule)
    response_stats, _, _, _ = build_response_time_stats(all_pairs, schedule)
    aggregate = aggregate_crm_results(all_dialogs, response_stats)

    dialog_to_date: dict[str, str] = {}
    for dr in daily_reports:
        for d in dr.dialogs:
            dialog_to_date[d.channel_id] = dr.meta.target_date

    worst = sorted(
        all_dialogs,
        key=lambda d: (d.analysis.scores.needs_id + d.analysis.scores.cta),
    )[:5]
    worst_dialogs = [
        {
            "person_name": d.person_name,
            "date": dialog_to_date.get(d.channel_id, ""),
            "needs_id": d.analysis.scores.needs_id,
            "cta": d.analysis.scores.cta,
            "summary": d.analysis.summary,
            "killer_phrase": d.analysis.killer_phrase,
        }
        for d in worst
    ]

    last = daily_reports[-1]
    meta = CrmReportMeta(
        source=f"period:{date_from.isoformat()}..{date_to.isoformat()}",
        target_date=f"{date_from.isoformat()}_{date_to.isoformat()}",
        dialogs_count=len(all_dialogs),
        messages_count=total_messages,
        llm_provider=last.meta.llm_provider,
        model=last.meta.model,
        generated_at=datetime.now(timezone.utc).isoformat(),
        report_type="period",
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        days_in_period=len(daily_reports),
    )

    return CrmAnalysisReport(
        meta=meta,
        aggregate=aggregate,
        dialogs=all_dialogs,
        daily_summaries=daily_summaries,
        worst_dialogs=worst_dialogs,
    )


def write_period_report_md(
    period_report: CrmAnalysisReport,
    daily_reports: list[CrmAnalysisReport],
    path: Path,
    schedule: WorkSchedule | None = None,
) -> None:
    if schedule is None:
        schedule = WorkSchedule()
    agg = period_report.aggregate
    rt = agg.response_time
    date_from = period_report.meta.date_from or ""
    date_to = period_report.meta.date_to or ""

    def _sec(v: float | None) -> str:
        if v is None:
            return "—"
        if v < 60:
            return f"{v:.0f} сек"
        return f"{v / 60:.1f} мин"

    lines = [
        f"# Отчёт CRM за период {date_from} — {date_to}",
        "",
        f"- Дней в отчёте: **{period_report.meta.days_in_period}**",
        f"- Диалогов (сумма по дням): **{period_report.meta.dialogs_count}**",
        f"- Сообщений: **{period_report.meta.messages_count}**",
        "",
        "## Сводка за период (средние оценки)",
        "",
        "| Критерий | Среднее |",
        "|----------|---------|",
    ]
    labels = {
        "needs_id": "Выявление потребности",
        "objections_handled": "Отработка возражений",
        "value_presented": "Подсветка ценностей",
        "cta": "CTA",
        "deal_closed": "Закрытие сделки",
    }
    for key, label in labels.items():
        lines.append(f"| {label} | {agg.avg_scores.get(key, '—')} |")

    lines += [
        "",
        "## Скорость ответа за период",
        "",
        "### Рабочее время (10–18, пн–пт, SLA ≤2 мин)",
        f"- Медиана (рабочие сек): **{_sec(rt.median_work_seconds)}**",
        f"- Нарушений SLA >2 мин: **{rt.over_sla_work}**",
        f"- Ответов в рабочее время: {rt.responses_count_work}",
        "",
        "### Вне рабочего времени (SLA ≤15 мин)",
        f"- Медиана (календарное): **{_sec(rt.median_off_seconds)}**",
        f"- Нарушений SLA >15 мин: **{rt.over_sla_off}**",
        "",
        "### Общее (календарное)",
        f"- Медиана: **{_sec(rt.median_seconds)}**",
        f"- Пауз >15 мин: {rt.over_15min}",
        f"- Пауз >1 ч: {rt.over_1hour}",
        "",
        "## Динамика по дням",
        "",
        "| Дата | Диалогов | Needs | CTA | Мед. раб. | SLA>2м |",
        "|------|----------|-------|-----|-----------|--------|",
    ]
    for dr in daily_reports:
        a = dr.aggregate
        r = a.response_time
        lines.append(
            f"| {dr.meta.target_date} | {dr.meta.dialogs_count} | "
            f"{a.avg_scores.get('needs_id', '—')} | {a.avg_scores.get('cta', '—')} | "
            f"{_sec(r.median_work_seconds)} | {r.over_sla_work} |"
        )

    lines += ["", "## Топ ошибки недели", ""]
    for item in agg.top_errors[:12]:
        lines.append(f"- ({item['count']}x) {item['error']}")

    if period_report.worst_dialogs:
        lines += ["", "## Худшие диалоги периода", ""]
        for w in period_report.worst_dialogs:
            lines.append(
                f"- **{w['person_name']}** ({w['date']}): needs={w['needs_id']}, cta={w['cta']}"
            )
            if w.get("killer_phrase"):
                lines.append(f"  - Killer: `{w['killer_phrase']}`")

    lines += [
        "",
        "## Рекомендации для планёрки",
        "",
        "1. Разобрать 3 худших диалога по needs + CTA.",
        f"2. Контроль SLA: рабочее время — ответ ≤{int(schedule.sla_work_seconds)} сек.",
        "3. Закрепить CTA с конкретным шагом (время/звонок/визит).",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_crm_period(
    settings: Settings,
    date_from: date,
    date_to: date,
    *,
    skip_existing: bool = True,
    force: bool = False,
    recalc_existing_rt: bool = True,
) -> PeriodRunResult:
    settings.ensure_dirs()
    setup_logging(settings.logs_dir)
    schedule = WorkSchedule.from_settings(settings)

    result = PeriodRunResult(date_from=date_from, date_to=date_to)
    all_dates = daterange(date_from, date_to)
    total = len(all_dates)

    for i, d in enumerate(all_dates, 1):
        path = _daily_report_path(settings.output_dir, d)
        if skip_existing and not force and path.exists():
            logger.info("[%s/%s] Skip %s (report exists)", i, total, d)
            result.days_skipped.append(d.isoformat())
            if recalc_existing_rt:
                report = load_report_from_json(path)
                updated = recalc_response_times_in_report(report, settings, schedule)
                path.write_text(
                    json.dumps(updated.to_json_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                export_crm_excel(updated, settings.output_dir / "crm_excel")
            continue
        try:
            logger.info("[%s/%s] Analyzing %s", i, total, d)
            run_crm_analysis(settings, target_date=d)
            result.days_analyzed.append(d.isoformat())
        except Exception as exc:
            logger.error("Failed %s: %s", d, exc)
            result.days_failed.append(d.isoformat())

    daily_reports = load_daily_reports_in_range(
        settings.output_dir,
        date_from.isoformat(),
        date_to.isoformat(),
    )
    if not daily_reports:
        logger.warning("No daily reports for period")
        return result

    period_report = build_period_report(settings, daily_reports, date_from, date_to)
    period_name = f"{date_from.isoformat()}_{date_to.isoformat()}"
    period_json = settings.output_dir / f"crm_report_period_{period_name}.json"
    period_json.write_text(
        json.dumps(period_report.to_json_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    period_md = settings.project_root / "docs" / "analysis" / f"CRM_REPORT_PERIOD_{period_name}.md"
    write_period_report_md(period_report, daily_reports, period_md, schedule)

    period_xlsx = settings.output_dir / "crm_excel" / f"CRM_PERIOD_{period_name}.xlsx"
    write_period_excel(period_report, daily_reports, period_xlsx)

    try:
        from export_knowledge import export_docs

        export_docs(settings)
    except Exception as exc:
        logger.warning("Knowledge export failed: %s", exc)

    result.period_json = str(period_json)
    result.period_md = str(period_md)
    result.period_excel = str(period_xlsx)
    return result


def run_crm_main_run(
    settings: Settings,
    *,
    skip_existing: bool = True,
    force: bool = False,
) -> PeriodRunResult:
    date_from, date_to = previous_calendar_week()
    logger.info("Main run: %s .. %s", date_from, date_to)
    return run_crm_period(
        settings,
        date_from,
        date_to,
        skip_existing=skip_existing,
        force=force,
        recalc_existing_rt=True,
    )
