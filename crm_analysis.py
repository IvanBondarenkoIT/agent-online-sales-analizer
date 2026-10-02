"""CRM chat analysis: fetch, parse, response times, LLM, report."""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from analyzer import extract_json
from config import Settings, load_prompt, setup_logging
from crm_fetch import fetch_calendar_day
from crm_response_time import (
    ResponsePairMetrics,
    WorkSchedule,
    build_response_time_stats,
    classify_client_bucket,
    enrich_dialog_response_time,
    is_on_calendar_day,
    working_seconds_between,
)
from llm.factory import create_llm_client
from llm.base import LLMClient
from models.crm_schemas import (
    ChecklistItem,
    CrmAggregateStats,
    CrmAnalysisReport,
    CrmDialogAnalysis,
    CrmDialogReport,
    CrmReportMeta,
    CrmScores,
    DialogResponseTime,
    PhoneCaptureStats,
    ResponseTimeStats,
)

logger = logging.getLogger("dimkava.crm_analysis")

MANAGER_TYPES = frozenset(
    {"YOUR_MESSAGE", "OUTGOING", "MANAGER", "OPERATOR"}
)
CLIENT_TYPES = frozenset(
    {"FRIEND_MESSAGE", "INCOMING", "CLIENT", "INCOME_MESSAGE", "ACCOUNT_MESSAGE"}
)
SKIP_TYPES = frozenset({"SYSTEM_MESSAGE"})

CHECKLIST_CRITERIA = [
    "greeting_contact",
    "needs_identified",
    "context_segmentation",
    "price_in_context",
    "values_highlighted",
    "objections_handled",
    "concrete_cta",
    "next_step_fixed",
    "no_price_chaos",
    "response_pace_ok",
]


@dataclass
class CrmMessage:
    message_id: str
    text: str
    msg_type: str
    created_at: datetime | None
    channel_id: str
    person_name: str
    platform: str


@dataclass
class CrmChannel:
    channel_id: str
    person_name: str
    platform: str
    messages: list[CrmMessage] = field(default_factory=list)


def parse_api_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_channels_from_jsonl(path: Path) -> dict[str, CrmChannel]:
    channels: dict[str, CrmChannel] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cid = row["channel_id"]
            if cid not in channels:
                channels[cid] = CrmChannel(
                    channel_id=cid,
                    person_name=row.get("person_name") or "Без имени",
                    platform=row.get("platform") or "?",
                )
            ch = channels[cid]
            msg = CrmMessage(
                message_id=row.get("message_id") or "",
                text=row.get("text") or "",
                msg_type=(row.get("type") or "").upper(),
                created_at=parse_api_datetime(row.get("created_at")),
                channel_id=cid,
                person_name=ch.person_name,
                platform=ch.platform,
            )
            ch.messages.append(msg)

    for ch in channels.values():
        ch.messages.sort(
            key=lambda m: m.created_at or datetime.min.replace(tzinfo=timezone.utc)
        )
    return channels


def is_manager(msg_type: str) -> bool:
    return msg_type.upper() in MANAGER_TYPES


def is_client(msg_type: str) -> bool:
    return msg_type.upper() in CLIENT_TYPES


def compute_channel_response_times(
    channel: CrmChannel,
    schedule: WorkSchedule,
    *,
    on_date: date | None = None,
) -> tuple[list[ResponsePairMetrics], DialogResponseTime]:
    """Client message -> next manager reply; overall + working-hours metrics.

    If ``on_date`` is set, only pairs whose **client** message falls on that
    calendar day (schedule TZ) are kept. Work/off bucket and SLA thresholds
    are unchanged: work uses work_seconds vs sla_work; off uses wall vs sla_off.
    """
    pairs: list[ResponsePairMetrics] = []
    msgs = [m for m in channel.messages if m.msg_type not in SKIP_TYPES and m.created_at]

    for i, msg in enumerate(msgs):
        if not is_client(msg.msg_type):
            continue
        if not (msg.text or "").strip():
            continue
        if on_date is not None and msg.created_at is not None:
            if not is_on_calendar_day(msg.created_at, on_date, schedule):
                continue
        for nxt in msgs[i + 1 :]:
            if is_manager(nxt.msg_type) and nxt.created_at and msg.created_at:
                wall = (nxt.created_at - msg.created_at).total_seconds()
                if wall >= 0:
                    work = working_seconds_between(msg.created_at, nxt.created_at, schedule)
                    bucket = classify_client_bucket(msg.created_at, schedule)
                    pairs.append(
                        ResponsePairMetrics(
                            wall_seconds=wall,
                            work_seconds=work,
                            bucket=bucket,
                        )
                    )
                break

    rt = DialogResponseTime(
        channel_id=channel.channel_id,
        person_name=channel.person_name,
    )
    enrich_dialog_response_time(rt, pairs, schedule)
    return pairs, rt


def aggregate_response_times(
    per_channel: dict[str, tuple[list[ResponsePairMetrics], DialogResponseTime]],
    schedule: WorkSchedule,
) -> ResponseTimeStats:
    all_pairs: list[ResponsePairMetrics] = []
    min_info: tuple[float, str] | None = None
    max_info: tuple[float, str] | None = None

    for _cid, (pairs, rt) in per_channel.items():
        all_pairs.extend(pairs)
        if rt.min_seconds is not None:
            if min_info is None or rt.min_seconds < min_info[0]:
                min_info = (rt.min_seconds, rt.person_name)
        if rt.max_seconds is not None:
            if max_info is None or rt.max_seconds > max_info[0]:
                max_info = (rt.max_seconds, rt.person_name)

    stats, _, _, _ = build_response_time_stats(all_pairs, schedule)
    if min_info:
        stats.min_dialog = min_info[1]
    if max_info:
        stats.max_dialog = max_info[1]
    return stats


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} сек"
    if seconds < 3600:
        return f"{seconds / 60:.1f} мин"
    return f"{seconds / 3600:.1f} ч"


def _format_rt_block(rt: DialogResponseTime, schedule: WorkSchedule) -> list[str]:
    lines: list[str] = []
    if rt.responses_count:
        lines.append(
            f"  Общее: avg={_format_duration(rt.avg_seconds or 0)}, "
            f"min={_format_duration(rt.min_seconds or 0)}, "
            f"max={_format_duration(rt.max_seconds or 0)}, n={rt.responses_count}"
        )
    if rt.responses_count_work:
        lines.append(
            f"  Рабочее время (10–18 пн–пт): avg={_format_duration(rt.avg_work_seconds or 0)}, "
            f"нарушений SLA>{int(schedule.sla_work_seconds)}с={rt.over_sla_work}, "
            f"n={rt.responses_count_work}"
        )
    if rt.responses_count_off:
        lines.append(
            f"  Вне смены: avg={_format_duration(rt.avg_off_seconds or 0)}, "
            f"нарушений SLA>{int(schedule.sla_off_seconds)}с={rt.over_sla_off}, "
            f"n={rt.responses_count_off}"
        )
    return lines


def channel_to_user_prompt(
    channel: CrmChannel,
    rt: DialogResponseTime,
    target_date: date,
    schedule: WorkSchedule,
) -> str:
    lines = [
        f"Диалог CRM: {channel.person_name} ({channel.platform})",
        f"channel_id: {channel.channel_id}",
        f"Дата анализа (активность): {target_date.isoformat()}",
        f"Сообщений в полной истории: {len(channel.messages)}",
        "Метки: [ДЕНЬ АНАЛИЗА] = реплика в календарный день анализа (Tbilisi); "
        "[история] = контекст прошлых дней. phone_capture и качество дня — только по [ДЕНЬ АНАЛИЗА].",
        "Скорость в отчёте: только ответы на сообщения клиентов за день анализа; "
        "рабочее время ≤2 мин (рабочие сек), вне смены ≤15 мин (календарные).",
    ]
    if rt.responses_count:
        lines.append("Метрики скорости ответа оператора (день анализа):")
        lines.extend(_format_rt_block(rt, schedule))
    else:
        lines.append("Метрики скорости: нет пар клиент→оператор с текстом за день анализа")
    lines.append("")
    lines.append("Полная история переписки (хронология):")
    for i, msg in enumerate(channel.messages, 1):
        if msg.msg_type in SKIP_TYPES and not (msg.text or "").strip():
            continue
        role = "Менеджер" if is_manager(msg.msg_type) else "Клиент"
        when = msg.created_at.isoformat() if msg.created_at else "?"
        tag = "[история]"
        if msg.created_at is not None and is_on_calendar_day(msg.created_at, target_date, schedule):
            tag = "[ДЕНЬ АНАЛИЗА]"
        text = (msg.text or "").replace("\n", " ").strip() or "(пусто/медиа)"
        lines.append(f"{i}. {tag} [{when}] {role} ({msg.msg_type}): {text}")
    return "\n".join(lines)


def _crm_partial_path(settings: Settings, target_date: date) -> Path:
    return settings.output_dir / f"crm_partial_{target_date.isoformat()}.json"


def _save_crm_partial(
    settings: Settings,
    target_date: date,
    source_jsonl: str,
    reports: list[CrmDialogReport],
) -> None:
    payload = {
        "target_date": target_date.isoformat(),
        "source_jsonl": source_jsonl,
        "dialogs": [r.model_dump(mode="json") for r in reports],
    }
    path = _crm_partial_path(settings, target_date)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_crm_partial(
    settings: Settings,
    target_date: date,
) -> dict[str, CrmDialogReport]:
    path = _crm_partial_path(settings, target_date)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("target_date") != target_date.isoformat():
        return {}
    reports: dict[str, CrmDialogReport] = {}
    for item in data.get("dialogs", []):
        report = CrmDialogReport.model_validate(item)
        reports[report.channel_id] = report
    return reports


def _delete_crm_partial(settings: Settings, target_date: date) -> None:
    path = _crm_partial_path(settings, target_date)
    if path.exists():
        path.unlink()


def analyze_crm_dialog(
    channel: CrmChannel,
    rt: DialogResponseTime,
    target_date: date,
    schedule: WorkSchedule,
    llm: LLMClient,
    system_prompt: str,
    max_retries: int,
) -> CrmDialogAnalysis:
    user_prompt = channel_to_user_prompt(channel, rt, target_date, schedule)
    prompt_chars = len(system_prompt) + len(user_prompt)
    msg_count = len(channel.messages)
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 2):
        try:
            t0 = time.monotonic()
            raw = llm.complete(system=system_prompt, user=user_prompt)
            total_ms = (time.monotonic() - t0) * 1000.0
            create_ms = getattr(llm, "last_create_ms", None)
            poll_ms = getattr(llm, "last_poll_ms", None)
            if not isinstance(create_ms, (int, float)):
                create_ms = None
            if not isinstance(poll_ms, (int, float)):
                poll_ms = None
            logger.info(
                "CRM dialog %s timing: total=%.0fms create=%s poll=%s "
                "prompt_chars=%s msg_count=%s",
                channel.channel_id,
                total_ms,
                f"{create_ms:.0f}ms" if create_ms is not None else "n/a",
                f"{poll_ms:.0f}ms" if poll_ms is not None else "n/a",
                prompt_chars,
                msg_count,
            )
            data = extract_json(raw)
            analysis = CrmDialogAnalysis.model_validate(data)
            return analysis
        except (
            json.JSONDecodeError,
            ValidationError,
            ValueError,
            RuntimeError,
            httpx.HTTPError,
        ) as exc:
            last_error = exc
            logger.warning(
                "CRM dialog %s attempt %s failed: %s",
                channel.channel_id,
                attempt,
                exc,
            )
            if attempt <= max_retries:
                time.sleep(min(2**attempt, 8))

    raise RuntimeError(
        f"Failed CRM analysis for {channel.person_name}: {last_error}"
    )


def _daily_report_path(settings: Settings, target_date: date) -> Path:
    return settings.output_dir / f"crm_report_{target_date.isoformat()}.json"


def _load_daily_report(settings: Settings, target_date: date) -> CrmAnalysisReport | None:
    path = _daily_report_path(settings, target_date)
    if not path.exists():
        return None
    from crm_excel_export import load_report_from_json

    return load_report_from_json(path)


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def aggregate_crm_results(
    reports: list[CrmDialogReport],
    response_stats: ResponseTimeStats,
) -> CrmAggregateStats:
    if not reports:
        return CrmAggregateStats(
            avg_scores={},
            checklist_pass_rate={},
            top_errors=[],
            top_strengths=[],
            response_time=response_stats,
            phone_attempts_total=0,
            phone_successes_total=0,
            phone_success_rate=0.0,
        )

    score_keys = ["needs_id", "objections_handled", "value_presented", "cta", "deal_closed"]
    avg_scores: dict[str, float] = {}
    for key in score_keys:
        vals = [getattr(r.analysis.scores, key) for r in reports]
        avg_scores[key] = round(sum(vals) / len(vals), 2)

    checklist_pass: dict[str, list[bool]] = defaultdict(list)
    for r in reports:
        by_crit = {c.criterion: c.passed for c in r.analysis.checklist}
        for crit in CHECKLIST_CRITERIA:
            if crit in by_crit:
                checklist_pass[crit].append(by_crit[crit])

    checklist_pass_rate = {
        crit: round(sum(vals) / len(vals) * 100, 1) if vals else 0.0
        for crit, vals in checklist_pass.items()
    }

    err_counter: Counter[str] = Counter()
    str_counter: Counter[str] = Counter()
    for r in reports:
        for e in r.analysis.errors_found:
            err_counter[e.strip().lower()] += 1
        for s in r.analysis.strengths_found:
            str_counter[s.strip().lower()] += 1

    n = len(reports)
    top_errors = [
        {"error": e, "count": c, "percent": round(c / n * 100, 1)}
        for e, c in err_counter.most_common(8)
    ]
    top_strengths = [
        {"strength": s, "count": c, "percent": round(c / n * 100, 1)}
        for s, c in str_counter.most_common(8)
    ]

    phone_attempts = sum(max(0, r.analysis.phone_capture.attempts) for r in reports)
    phone_successes = sum(1 for r in reports if r.analysis.phone_capture.success)
    if phone_attempts > 0:
        phone_rate = round(phone_successes / phone_attempts * 100, 1)
    elif phone_successes > 0:
        phone_rate = 100.0  # номер получен без явной попытки менеджера
    else:
        phone_rate = 0.0

    return CrmAggregateStats(
        avg_scores=avg_scores,
        checklist_pass_rate=checklist_pass_rate,
        top_errors=top_errors,
        top_strengths=top_strengths,
        response_time=response_stats,
        phone_attempts_total=phone_attempts,
        phone_successes_total=phone_successes,
        phone_success_rate=phone_rate,
    )


def write_crm_report_md(
    report: CrmAnalysisReport,
    path: Path,
    schedule: WorkSchedule | None = None,
) -> None:
    agg = report.aggregate
    rt = agg.response_time
    if schedule is None:
        schedule = WorkSchedule()
    lines = [
        f"# Отчёт CRM-переписок — {report.meta.target_date}",
        "",
        f"- Источник: `{report.meta.source}`",
        f"- Диалогов: **{report.meta.dialogs_count}**",
        f"- Сообщений: **{report.meta.messages_count}**",
        f"- LLM: {report.meta.llm_provider} / {report.meta.model}",
        "",
        "## Средние оценки (0–5)",
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
        val = agg.avg_scores.get(key, "—")
        lines.append(f"| {label} | {val} |")

    lines += ["", "## Чеклист (% прохождения)", "", "| Критерий | % |", "|----------|---|"]
    for crit, pct in sorted(agg.checklist_pass_rate.items()):
        lines.append(f"| {crit} | {pct}% |")

    lines += [
        "",
        "## Скорость ответа оператора",
        "",
        "_Только пары, где клиент написал **в день анализа** (Tbilisi). "
        "Рабочее время ≤2 мин (рабочие сек); вне смены ≤15 мин (календарные)._",
        "",
        "### Рабочее время (10–18, пн–пт, SLA ≤2 мин)",
        "",
    ]
    if rt.responses_count_work:
        lines += [
            f"- Среднее (рабочие сек): **{_format_duration(rt.avg_work_seconds or 0)}**",
            f"- Медиана (рабочие сек): **{_format_duration(rt.median_work_seconds or 0)}**",
            f"- Ответов в рабочее время: {rt.responses_count_work}",
            f"- Нарушений SLA >{int(schedule.sla_work_seconds)} сек: **{rt.over_sla_work}**",
        ]
    else:
        lines.append("- Нет пар, где клиент написал в рабочее время")

    lines += [
        "",
        "### Вне рабочего времени (SLA ≤15 мин, мягкий)",
        "",
    ]
    if rt.responses_count_off:
        lines += [
            f"- Среднее (календарное): **{_format_duration(rt.avg_off_seconds or 0)}**",
            f"- Медиана (календарное): **{_format_duration(rt.median_off_seconds or 0)}**",
            f"- Ответов вне смены: {rt.responses_count_off}",
            f"- Нарушений SLA >{int(schedule.sla_off_seconds)} сек: **{rt.over_sla_off}**",
        ]
    else:
        lines.append("- Нет пар вне рабочего времени")

    lines += [
        "",
        "### Общее (календарное время)",
        "",
        f"- Среднее: **{_format_duration(rt.avg_seconds or 0)}**" if rt.avg_seconds else "- Среднее: —",
        f"- Медиана: **{_format_duration(rt.median_seconds or 0)}**" if rt.median_seconds else "- Медиана: —",
        f"- Мин: **{_format_duration(rt.min_seconds or 0)}** ({rt.min_dialog or '—'})" if rt.min_seconds else "- Мин: —",
        f"- Макс: **{_format_duration(rt.max_seconds or 0)}** ({rt.max_dialog or '—'})" if rt.max_seconds else "- Макс: —",
        f"- Ответов измерено: {rt.responses_count}",
        f"- Пауз >15 мин: {rt.over_15min}",
        f"- Пауз >1 ч: {rt.over_1hour}",
        "",
        "## Телефон → WhatsApp",
        "",
        f"- Попыток запросить номер: **{agg.phone_attempts_total}**",
        f"- Успехов (номер/контакт получен): **{agg.phone_successes_total}**",
        f"- Конверсия попыток: **{agg.phone_success_rate}%**",
        "",
        "## Топ ошибки",
        "",
    ]
    for item in agg.top_errors[:8]:
        lines.append(f"- ({item['count']}x) {item['error']}")

    lines += ["", "## Сильные стороны", ""]
    for item in agg.top_strengths[:8]:
        lines.append(f"- ({item['count']}x) {item['strength']}")

    lines += ["", "## Диалоги", ""]
    for d in sorted(report.dialogs, key=lambda x: x.person_name):
        sc = d.analysis.scores
        lines += [
            f"### {d.person_name} ({d.platform})",
            "",
            f"**Суть:** {d.analysis.summary}",
            "",
            f"**Оценки:** needs={sc.needs_id}, objections={sc.objections_handled}, "
            f"value={sc.value_presented}, cta={sc.cta}, deal={sc.deal_closed}",
            "",
            f"**Телефон/WA:** attempts={d.analysis.phone_capture.attempts}, "
            f"success={'да' if d.analysis.phone_capture.success else 'нет'}"
            + (f" — {d.analysis.phone_capture.note}" if d.analysis.phone_capture.note else ""),
            "",
        ]
        if d.analysis.strengths_found:
            lines.append("**Плюсы:**")
            for s in d.analysis.strengths_found[:3]:
                lines.append(f"- {s}")
            lines.append("")
        if d.analysis.errors_found:
            lines.append("**Ошибки:**")
            for e in d.analysis.errors_found[:5]:
                lines.append(f"- {e}")
            lines.append("")
        if d.analysis.killer_phrase:
            lines.append(f"**Killer phrase:** `{d.analysis.killer_phrase}`")
            lines.append("")
        if d.response_time.responses_count:
            lines.append(
                f"**Время ответа:** avg {_format_duration(d.response_time.avg_seconds or 0)}, "
                f"min {_format_duration(d.response_time.min_seconds or 0)}, "
                f"max {_format_duration(d.response_time.max_seconds or 0)}"
            )
            lines.append("")

    lines += [
        "## Выводы и рекомендации",
        "",
        _build_recommendations(report, schedule),
        "",
        "## Рекомендуемый сценарий действий для команды",
        "",
        "1. **Утренняя планёрка (15 мин):** разобрать 2–3 худших диалога по needs_id и CTA.",
        "2. **Правило цены:** на «ფასი?» — сначала один вопрос (дом/бизнес), потом цена в контексте.",
        "3. **Правило CTA:** каждый ответ заканчивается конкретным шагом (время, звонок, ссылка, визит).",
        "4. **Скорость:** в рабочее время (10–18) — цель ≤2 мин; вне смены — ≤15 мин; эскалация при паузах >1 ч.",
        "5. **Чеклист:** перед отправкой — [MANAGER_PLAYBOOK_GE.md](../instructions/MANAGER_PLAYBOOK_GE.md).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_recommendations(report: CrmAnalysisReport, schedule: WorkSchedule | None = None) -> str:
    if schedule is None:
        schedule = WorkSchedule()
    agg = report.aggregate
    parts: list[str] = []
    needs = agg.avg_scores.get("needs_id", 0)
    cta = agg.avg_scores.get("cta", 0)
    if needs < 3:
        parts.append(
            f"- **Потребности ({needs}/5):** системно не выявляются — внедрить обязательный "
            "вопрос «სახლისთვის თუ ბიზნესისთვის?» (дом или бизнес?) до цены."
        )
    if cta < 3:
        parts.append(
            f"- **CTA ({cta}/5):** слабое закрытие — запретить «მოგვწერეთ ბიუჯეტი» (напишите бюджет) без рекомендации."
        )
    rt = agg.response_time
    if rt.over_sla_work > 0:
        parts.append(
            f"- **Скорость (рабочее время):** {rt.over_sla_work} ответов дольше "
            f"{int(schedule.sla_work_seconds)} сек — настроить уведомления CRM."
        )
    if rt.over_sla_off > 0:
        parts.append(
            f"- **Скорость (вне смены):** {rt.over_sla_off} ответов дольше "
            f"{int(schedule.sla_off_seconds)} сек."
        )
    elif rt.over_15min > 0:
        parts.append(
            f"- **Скорость (общее):** {rt.over_15min} ответов дольше 15 мин."
        )
    low_checklist = [c for c, p in agg.checklist_pass_rate.items() if p < 50]
    if low_checklist:
        parts.append(
            f"- **Чеклист:** слабые зоны — {', '.join(low_checklist[:5])}."
        )
    if not parts:
        parts.append("- В целом показатели в норме; закрепить лучшие практики из сильных сторон.")
    return "\n".join(parts)


def run_crm_analysis(
    settings: Settings,
    target_date: date | None = None,
    *,
    force: bool = False,
) -> CrmAnalysisReport:
    settings.ensure_dirs()
    setup_logging(settings.logs_dir)
    settings.validate_llm_only()

    if target_date is None:
        target_date = (datetime.now().astimezone() - timedelta(days=1)).date()

    logger.info("CRM analysis for date %s", target_date)

    if not force:
        partial_path = _crm_partial_path(settings, target_date)
        existing = _load_daily_report(settings, target_date)
        if existing is not None and not partial_path.exists():
            logger.info(
                "Skip LLM: report already exists (%s dialogs). "
                "Use --crm-force to recompute.",
                existing.meta.dialogs_count,
            )
            return existing
        if existing is not None and partial_path.exists():
            logger.info(
                "Report exists but partial checkpoint present — resuming failed dialogs"
            )

    schedule = WorkSchedule.from_settings(settings)
    if force:
        _delete_crm_partial(settings, target_date)

    cached_jsonl = find_jsonl_for_date(settings.output_dir, target_date)
    if cached_jsonl and not force:
        jsonl_path = cached_jsonl
        logger.info("Using cached raw JSONL: %s", jsonl_path)
    else:
        raw_dir = settings.output_dir / "crm_raw" / target_date.isoformat()
        fetch_result = fetch_calendar_day(
            day=target_date,
            mode="full_history",
            output_dir=raw_dir,
        )
        jsonl_path = Path(fetch_result["jsonl"])

    channels = load_channels_from_jsonl(jsonl_path)

    per_channel_rt: dict[str, tuple[list[ResponsePairMetrics], DialogResponseTime]] = {}
    for cid, ch in channels.items():
        per_channel_rt[cid] = compute_channel_response_times(ch, schedule, on_date=target_date)
    response_stats = aggregate_response_times(per_channel_rt, schedule)

    system_prompt = load_prompt("crm_analyzer_system.txt")
    llm = create_llm_client(settings)
    concurrency = max(1, settings.crm_llm_concurrency)
    logger.info("CRM LLM concurrency=%s", concurrency)

    done_reports = _load_crm_partial(settings, target_date) if not force else {}
    if done_reports:
        logger.info("Resuming: %s dialogs already in partial", len(done_reports))

    total_messages = sum(len(ch.messages) for ch in channels.values())
    sorted_channels = sorted(channels.items(), key=lambda x: x[1].person_name)
    pending = [
        (i, cid, ch)
        for i, (cid, ch) in enumerate(sorted_channels, 1)
        if cid not in done_reports
    ]
    for i, (cid, ch) in enumerate(sorted_channels, 1):
        if cid in done_reports:
            logger.info("[%s/%s] Skip %s (partial)", i, len(channels), ch.person_name)

    partial_lock = threading.Lock()
    timing_totals: list[float] = []
    timing_lock = threading.Lock()
    failed: list[tuple[str, str]] = []

    def _persist_partial() -> None:
        _save_crm_partial(
            settings,
            target_date,
            str(jsonl_path),
            [done_reports[c] for c, _ in sorted_channels if c in done_reports],
        )

    def _analyze_one(item: tuple[int, str, CrmChannel]) -> tuple[str, CrmDialogReport | None, str | None]:
        i, cid, ch = item
        _, rt = per_channel_rt[cid]
        logger.info("[%s/%s] Analyzing %s", i, len(channels), ch.person_name)
        if settings.request_delay_sec > 0:
            time.sleep(settings.request_delay_sec)
        try:
            t0 = time.monotonic()
            analysis = analyze_crm_dialog(
                ch, rt, target_date, schedule, llm, system_prompt, settings.max_retries
            )
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            with timing_lock:
                timing_totals.append(elapsed_ms)
            report = CrmDialogReport(
                channel_id=cid,
                person_name=ch.person_name,
                platform=ch.platform,
                message_count=len(ch.messages),
                analysis=analysis,
                response_time=rt,
            )
            return cid, report, None
        except Exception as exc:
            logger.error(
                "CRM dialog %s (%s) failed after retries: %s — soft-continue",
                cid,
                ch.person_name,
                exc,
            )
            return cid, None, str(exc)

    try:
        if concurrency == 1:
            for item in pending:
                cid, report, err = _analyze_one(item)
                if report is not None:
                    done_reports[cid] = report
                    _persist_partial()
                elif err is not None:
                    failed.append((cid, err))
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(_analyze_one, item): item for item in pending}
                for fut in as_completed(futures):
                    cid, report, err = fut.result()
                    if report is not None:
                        with partial_lock:
                            done_reports[cid] = report
                            _persist_partial()
                    elif err is not None:
                        with partial_lock:
                            failed.append((cid, err))
    finally:
        close = getattr(llm, "close", None)
        if callable(close):
            close()

    if timing_totals:
        med = _median_or_none(timing_totals)
        mean = statistics.mean(timing_totals)
        logger.info(
            "CRM day timing: n=%s mean=%.0fms p50=%.0fms min=%.0fms max=%.0fms",
            len(timing_totals),
            mean,
            med if med is not None else 0.0,
            min(timing_totals),
            max(timing_totals),
        )
    if failed:
        logger.warning(
            "CRM day soft-continue: %s dialog(s) failed: %s",
            len(failed),
            ", ".join(f"{cid}" for cid, _ in failed),
        )

    reports = [done_reports[cid] for cid, _ in sorted_channels if cid in done_reports]

    meta = CrmReportMeta.create(
        source=str(jsonl_path),
        target_date=target_date.isoformat(),
        dialogs_count=len(reports),
        messages_count=total_messages,
        llm_provider=settings.llm_provider,
        model=settings.llm_model,
    )
    aggregate = aggregate_crm_results(reports, response_stats)
    report = CrmAnalysisReport(meta=meta, aggregate=aggregate, dialogs=reports)

    out_json = _daily_report_path(settings, target_date)
    out_json.write_text(
        json.dumps(report.to_json_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    out_md = settings.project_root / "docs" / "analysis" / f"CRM_REPORT_{target_date.isoformat()}.md"
    write_crm_report_md(report, out_md, schedule)

    from crm_excel_export import export_crm_excel

    excel_paths = export_crm_excel(report, settings.output_dir / "crm_excel")
    logger.info("CRM Excel saved: %s, %s", excel_paths["daily"], excel_paths["master"])

    if not failed:
        _delete_crm_partial(settings, target_date)
    else:
        logger.warning(
            "Keeping partial checkpoint (%s) because %s dialog(s) failed",
            _crm_partial_path(settings, target_date),
            len(failed),
        )
    logger.info("CRM report saved: %s, %s", out_json, out_md)
    return report


def find_jsonl_for_date(output_dir: Path, target_date: date) -> Path | None:
    raw_dir = output_dir / "crm_raw" / target_date.isoformat()
    if not raw_dir.exists():
        return None
    for jsonl in raw_dir.rglob("messages.jsonl"):
        return jsonl
    for jsonl in raw_dir.rglob("*.jsonl"):
        return jsonl
    return None


def compute_response_stats_for_date(
    settings: Settings,
    target_date: date,
    schedule: WorkSchedule | None = None,
) -> ResponseTimeStats:
    if schedule is None:
        schedule = WorkSchedule.from_settings(settings)
    jsonl_path = find_jsonl_for_date(settings.output_dir, target_date)
    if not jsonl_path:
        return ResponseTimeStats()
    channels = load_channels_from_jsonl(jsonl_path)
    per_channel: dict[str, tuple[list[ResponsePairMetrics], DialogResponseTime]] = {}
    for cid, ch in channels.items():
        per_channel[cid] = compute_channel_response_times(ch, schedule, on_date=target_date)
    return aggregate_response_times(per_channel, schedule)


def recalc_response_times_in_report(
    report: CrmAnalysisReport,
    settings: Settings,
    schedule: WorkSchedule | None = None,
) -> CrmAnalysisReport:
    """Recompute response-time fields from raw JSONL without LLM."""
    if schedule is None:
        schedule = WorkSchedule.from_settings(settings)
    target = date.fromisoformat(report.meta.target_date)
    jsonl_path = find_jsonl_for_date(settings.output_dir, target)
    if not jsonl_path:
        return report
    channels = load_channels_from_jsonl(jsonl_path)
    per_channel: dict[str, tuple[list[ResponsePairMetrics], DialogResponseTime]] = {}
    for cid, ch in channels.items():
        per_channel[cid] = compute_channel_response_times(ch, schedule, on_date=target)
    response_stats = aggregate_response_times(per_channel, schedule)
    updated_dialogs: list[CrmDialogReport] = []
    for d in report.dialogs:
        if d.channel_id in per_channel:
            _, rt = per_channel[d.channel_id]
            updated_dialogs.append(d.model_copy(update={"response_time": rt}))
        else:
            updated_dialogs.append(d)
    aggregate = aggregate_crm_results(updated_dialogs, response_stats)
    return report.model_copy(update={"dialogs": updated_dialogs, "aggregate": aggregate})
