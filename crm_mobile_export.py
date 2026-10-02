"""Mobile-friendly CRM coaching digest: short Markdown + HTML charts (Chart.js CDN)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from models.crm_schemas import CrmAnalysisReport

SCORE_KEYS: tuple[str, ...] = (
    "needs_id",
    "objections_handled",
    "value_presented",
    "cta",
    "deal_closed",
)
SCORE_LABELS: dict[str, str] = {
    "needs_id": "Needs",
    "objections_handled": "Возражения",
    "value_presented": "Ценности",
    "cta": "CTA",
    "deal_closed": "Deal",
}
TREND_WINDOW = 14
SPARK = "▁▂▃▄▅▆▇█"


def _sla_pct(over: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (1.0 - over / total))), 1)


def _sparkline(values: list[float]) -> str:
    if not values:
        return "—"
    lo, hi = min(values), max(values)
    if hi <= lo:
        return SPARK[0] * len(values)
    out: list[str] = []
    for v in values:
        idx = int(round((v - lo) / (hi - lo) * (len(SPARK) - 1)))
        out.append(SPARK[max(0, min(len(SPARK) - 1, idx))])
    return "".join(out)


def _arrow(cur: float, prev: float | None, *, higher_is_better: bool = True) -> str:
    if prev is None:
        return "—"
    diff = cur - prev
    if abs(diff) < 0.05:
        return "→"
    if higher_is_better:
        return "↑" if diff > 0 else "↓"
    return "↓" if diff > 0 else "↑"


def _window(reports: list[CrmAnalysisReport], focus_date: str) -> list[CrmAnalysisReport]:
    ordered = sorted(reports, key=lambda r: r.meta.target_date)
    if not ordered:
        return []
    idx = next((i for i, r in enumerate(ordered) if r.meta.target_date == focus_date), len(ordered) - 1)
    start = max(0, idx - TREND_WINDOW + 1)
    return ordered[start : idx + 1]


def _focus_pair(
    reports: list[CrmAnalysisReport], focus_date: str
) -> tuple[CrmAnalysisReport, CrmAnalysisReport | None]:
    ordered = sorted(reports, key=lambda r: r.meta.target_date)
    by_date = {r.meta.target_date: r for r in ordered}
    focus = by_date.get(focus_date) or ordered[-1]
    prev: CrmAnalysisReport | None = None
    for r in ordered:
        if r.meta.target_date >= focus.meta.target_date:
            break
        prev = r
    return focus, prev


def _actions(report: CrmAnalysisReport) -> list[str]:
    agg = report.aggregate
    rt = agg.response_time
    actions: list[str] = []
    needs = float(agg.avg_scores.get("needs_id", 0) or 0)
    cta = float(agg.avg_scores.get("cta", 0) or 0)
    value = float(agg.avg_scores.get("value_presented", 0) or 0)
    obj = float(agg.avg_scores.get("objections_handled", 0) or 0)
    if needs < 3:
        actions.append("До цены — один вопрос (дом/бизнес). Фокус: Needs.")
    if cta < 3:
        actions.append("Каждый ответ → конкретный шаг (время / ссылка / визит). Фокус: CTA.")
    if value < 2.5:
        actions.append("После цены — одна ценность продукта (не скидка). Фокус: Ценности.")
    if obj < 2.5:
        actions.append("На «дорого/подумаю» — уточнить стоп-фактор + вариант. Фокус: Возражения.")
    sla = _sla_pct(rt.over_sla_work, rt.responses_count_work)
    if sla < 70 and rt.responses_count_work:
        actions.append(f"SLA раб. {sla}% — цель ≤2 мин в 10–18. Проверить уведомления CRM.")
    if not actions:
        actions.append("Закрепить вчерашние удачные формулировки; разобрать 2 диалога на планёрке.")
    return actions[:4]


def _series_payload(window: list[CrmAnalysisReport]) -> dict[str, Any]:
    labels = [r.meta.target_date[5:] for r in window]  # MM-DD for mobile
    scores = {k: [float(r.aggregate.avg_scores.get(k, 0) or 0) for r in window] for k in SCORE_KEYS}
    dialogs = [r.meta.dialogs_count for r in window]
    sla_work = [
        _sla_pct(r.aggregate.response_time.over_sla_work, r.aggregate.response_time.responses_count_work)
        for r in window
    ]
    med_work = [
        round((r.aggregate.response_time.median_work_seconds or 0) / 60, 1) for r in window
    ]
    return {
        "labels": labels,
        "needs": scores["needs_id"],
        "cta": scores["cta"],
        "deal": scores["deal_closed"],
        "objections": scores["objections_handled"],
        "value": scores["value_presented"],
        "dialogs": dialogs,
        "sla_work": sla_work,
        "med_work": med_work,
    }


def build_mobile_md(reports: list[CrmAnalysisReport], focus_date: str) -> str:
    focus, prev = _focus_pair(reports, focus_date)
    window = _window(reports, focus.meta.target_date)
    agg = focus.aggregate
    rt = agg.response_time
    prev_agg = prev.aggregate if prev else None
    sla = _sla_pct(rt.over_sla_work, rt.responses_count_work)
    prev_sla = (
        _sla_pct(prev.aggregate.response_time.over_sla_work, prev.aggregate.response_time.responses_count_work)
        if prev
        else None
    )
    lines = [
        f"# CRM mobile — {focus.meta.target_date}",
        "",
        f"Диалогов: **{focus.meta.dialogs_count}** · "
        f"SLA раб.: **{sla}%** {_arrow(sla, prev_sla)} · "
        f"мед. раб.: **{round((rt.median_work_seconds or 0) / 60, 1)} мин** · "
        f"тел.: **{agg.phone_attempts_total}→{agg.phone_successes_total}** ({agg.phone_success_rate}%)",
        "",
        "## Оценки vs вчера (0–5)",
        "",
        "| | Сегодня | Δ |",
        "|--|--:|:--:|",
    ]
    for key in SCORE_KEYS:
        cur = float(agg.avg_scores.get(key, 0) or 0)
        p = float(prev_agg.avg_scores.get(key, 0) or 0) if prev_agg else None
        lines.append(f"| {SCORE_LABELS[key]} | {cur} | {_arrow(cur, p)} |")

    lines += ["", "## Тренд (до 14 дн.)", ""]
    for key in ("needs_id", "cta", "value_presented", "objections_handled"):
        vals = [float(r.aggregate.avg_scores.get(key, 0) or 0) for r in window]
        lines.append(f"- {SCORE_LABELS[key]}: `{_sparkline(vals)}`")
    dialogs = [r.meta.dialogs_count for r in window]
    lines.append(f"- Диалоги/день: `{_sparkline([float(d) for d in dialogs])}`")
    sla_series = [
        _sla_pct(r.aggregate.response_time.over_sla_work, r.aggregate.response_time.responses_count_work)
        for r in window
    ]
    lines.append(f"- SLA раб.%: `{_sparkline(sla_series)}`")

    lines += [
        "",
        "## Телефон → WhatsApp",
        "",
        f"- Попыток: **{agg.phone_attempts_total}** · успехов: **{agg.phone_successes_total}** · "
        f"конверсия: **{agg.phone_success_rate}%**",
        "",
        "## Топ ошибки",
        "",
    ]
    for item in agg.top_errors[:3]:
        err = item.get("error", "—")
        cnt = item.get("count", 0)
        pct = item.get("percent", 0)
        lines.append(f"- ({cnt}, {pct}%) {err}")
    if not agg.top_errors:
        lines.append("- нет данных")

    lines += ["", "## Что делать завтра", ""]
    for i, a in enumerate(_actions(focus), 1):
        lines.append(f"{i}. {a}")

    lines += [
        "",
        "---",
        f"Полный отчёт: [CRM_REPORT_{focus.meta.target_date}.md](CRM_REPORT_{focus.meta.target_date}.md) · "
        "графики на телефоне: "
        f"[CRM_MOBILE_{focus.meta.target_date}.html](CRM_MOBILE_{focus.meta.target_date}.html)",
        "",
    ]
    return "\n".join(lines)


def build_mobile_html(reports: list[CrmAnalysisReport], focus_date: str) -> str:
    focus, prev = _focus_pair(reports, focus_date)
    window = _window(reports, focus.meta.target_date)
    payload = _series_payload(window)
    agg = focus.aggregate
    rt = agg.response_time
    sla = _sla_pct(rt.over_sla_work, rt.responses_count_work)
    actions = _actions(focus)
    score_rows = "".join(
        f"<tr><td>{SCORE_LABELS[k]}</td><td>{float(agg.avg_scores.get(k, 0) or 0)}</td></tr>"
        for k in SCORE_KEYS
    )
    err_items = "".join(
        f"<li>({item.get('count', 0)}) {item.get('error', '—')}</li>"
        for item in agg.top_errors[:3]
    ) or "<li>нет данных</li>"
    action_items = "".join(f"<li>{a}</li>" for a in actions)
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>CRM mobile — {focus.meta.target_date}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #f6f3ee; --ink: #1c1917; --muted: #78716c; --line: #e7e5e4;
    --card: #fffcf8; --accent: #0f766e;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
    background: linear-gradient(165deg, #efe8df 0%, var(--bg) 40%, #e8eef0 100%);
    color: var(--ink); padding: 16px 14px 40px; line-height: 1.35;
  }}
  h1 {{ font-size: 1.35rem; margin: 0 0 6px; letter-spacing: -0.02em; }}
  .meta {{ color: var(--muted); font-size: 0.92rem; margin-bottom: 16px; }}
  .kpi {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }}
  .kpi span {{
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 8px 12px; font-size: 0.9rem;
  }}
  .kpi b {{ color: var(--accent); }}
  section {{
    background: var(--card); border: 1px solid var(--line); border-radius: 14px;
    padding: 12px 12px 8px; margin-bottom: 12px;
  }}
  section h2 {{ font-size: 0.95rem; margin: 0 0 8px; color: var(--muted); font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
  td {{ padding: 6px 0; border-bottom: 1px solid var(--line); }}
  td:last-child {{ text-align: right; font-variant-numeric: tabular-nums; }}
  canvas {{ width: 100% !important; max-height: 220px; }}
  ul {{ margin: 0; padding-left: 1.1rem; }}
  li {{ margin-bottom: 6px; }}
  .foot {{ font-size: 0.8rem; color: var(--muted); margin-top: 8px; }}
</style>
</head>
<body>
  <h1>CRM — {focus.meta.target_date}</h1>
  <p class="meta">Мобильный дайджест · тренд {len(window)} дн. · без Excel</p>
  <div class="kpi">
    <span>Диалогов <b>{focus.meta.dialogs_count}</b></span>
    <span>SLA раб. <b>{sla}%</b></span>
    <span>Мед. раб. <b>{round((rt.median_work_seconds or 0) / 60, 1)} мин</b></span>
    <span>Тел. <b>{agg.phone_attempts_total}→{agg.phone_successes_total}</b> ({agg.phone_success_rate}%)</span>
  </div>

  <section>
    <h2>Оценки сегодня (0–5)</h2>
    <table>{score_rows}</table>
  </section>

  <section>
    <h2>Needs + CTA + Deal</h2>
    <canvas id="c1"></canvas>
  </section>
  <section>
    <h2>Возражения + Ценности</h2>
    <canvas id="c2"></canvas>
  </section>
  <section>
    <h2>SLA раб.% и медиана раб. (мин)</h2>
    <canvas id="c3"></canvas>
  </section>
  <section>
    <h2>Диалогов в день</h2>
    <canvas id="c4"></canvas>
  </section>

  <section>
    <h2>Топ ошибки</h2>
    <ul>{err_items}</ul>
  </section>
  <section>
    <h2>Что делать завтра</h2>
    <ul>{action_items}</ul>
  </section>
  <p class="foot">↑ scores / SLA% лучше · ↓ медиана минут лучше · данные из crm_report_*.json</p>

<script>
const D = {data_json};
const common = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }} }},
  scales: {{
    x: {{ ticks: {{ maxRotation: 45, minRotation: 45, font: {{ size: 10 }} }} }},
    y: {{ beginAtZero: true, ticks: {{ font: {{ size: 10 }} }} }}
  }}
}};
function line(id, datasets, yMax) {{
  const opts = JSON.parse(JSON.stringify(common));
  if (yMax) opts.scales.y.suggestedMax = yMax;
  new Chart(document.getElementById(id), {{
    type: 'line',
    data: {{ labels: D.labels, datasets }},
    options: opts
  }});
}}
line('c1', [
  {{ label: 'Needs', data: D.needs, borderColor: '#0f766e', tension: 0.25, pointRadius: 2 }},
  {{ label: 'CTA', data: D.cta, borderColor: '#b45309', tension: 0.25, pointRadius: 2 }},
  {{ label: 'Deal', data: D.deal, borderColor: '#57534e', tension: 0.25, pointRadius: 2 }}
], 5);
line('c2', [
  {{ label: 'Возражения', data: D.objections, borderColor: '#9f1239', tension: 0.25, pointRadius: 2 }},
  {{ label: 'Ценности', data: D.value, borderColor: '#1d4ed8', tension: 0.25, pointRadius: 2 }}
], 5);
line('c3', [
  {{ label: 'SLA раб.%', data: D.sla_work, borderColor: '#0f766e', tension: 0.25, pointRadius: 2 }},
  {{ label: 'Мед. раб. мин', data: D.med_work, borderColor: '#b45309', tension: 0.25, pointRadius: 2 }}
], null);
line('c4', [
  {{ label: 'Диалоги', data: D.dialogs, borderColor: '#44403c', backgroundColor: 'rgba(68,64,60,0.12)', fill: true, tension: 0.25, pointRadius: 2 }}
], null);
</script>
</body>
</html>
"""


def export_crm_mobile(
    reports: list[CrmAnalysisReport],
    docs_dir: Path,
    focus_date: str | None = None,
) -> dict[str, str]:
    """Write CRM_MOBILE_{date}.md/.html and LATEST copies."""
    if not reports:
        raise FileNotFoundError("No daily CRM reports for mobile export")
    ordered = sorted(reports, key=lambda r: r.meta.target_date)
    date_str = focus_date or ordered[-1].meta.target_date
    if focus_date and not any(r.meta.target_date == focus_date for r in ordered):
        raise FileNotFoundError(f"No report for {focus_date}")

    docs_dir.mkdir(parents=True, exist_ok=True)
    md_path = docs_dir / f"CRM_MOBILE_{date_str}.md"
    html_path = docs_dir / f"CRM_MOBILE_{date_str}.html"
    md_path.write_text(build_mobile_md(ordered, date_str), encoding="utf-8")
    html_path.write_text(build_mobile_html(ordered, date_str), encoding="utf-8")

    latest_md = docs_dir / "CRM_MOBILE_LATEST.md"
    latest_html = docs_dir / "CRM_MOBILE_LATEST.html"
    shutil.copyfile(md_path, latest_md)
    shutil.copyfile(html_path, latest_html)

    return {
        "md": str(md_path),
        "html": str(html_path),
        "latest_md": str(latest_md),
        "latest_html": str(latest_html),
    }


def export_mobile_from_output(
    output_dir: Path,
    docs_dir: Path,
    target_date: str | None = None,
) -> dict[str, str]:
    from crm_excel_export import load_all_daily_reports, load_report_from_json

    reports = load_all_daily_reports(output_dir)
    if target_date:
        json_path = output_dir / f"crm_report_{target_date}.json"
        if not json_path.exists():
            raise FileNotFoundError(json_path)
        focus = load_report_from_json(json_path)
        by_date = {r.meta.target_date: r for r in reports}
        by_date[focus.meta.target_date] = focus
        reports = sorted(by_date.values(), key=lambda r: r.meta.target_date)
        return export_crm_mobile(reports, docs_dir, focus_date=target_date)
    return export_crm_mobile(reports, docs_dir, focus_date=None)
