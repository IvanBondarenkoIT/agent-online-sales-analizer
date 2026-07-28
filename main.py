"""CLI entry point for DimKava sales dialog analyzer."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

from analyzer import run_analysis, run_parse_only
from config import get_settings
from export_knowledge import export_docs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DimKava: анализ переписок Facebook Messenger"
    )
    parser.add_argument(
        "--export-docs",
        action="store_true",
        help="Экспорт MD из локальных JSON/логов (без API)",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Запустить LLM-анализ (тратит API-лимиты)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Продолжить анализ с report_partial.json (только недостающие диалоги)",
    )
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Только распарсить DOCX без вызова LLM",
    )
    parser.add_argument(
        "--fetch-crm",
        action="store_true",
        help="Скачать переписки из Leeloo.ai CRM (без LLM)",
    )
    parser.add_argument(
        "--crm-days",
        type=int,
        default=7,
        help="Сколько дней назад выгружать при --fetch-crm (по умолчанию 7)",
    )
    parser.add_argument(
        "--analyze-crm-yesterday",
        action="store_true",
        help="Выгрузить и проанализировать CRM-переписки за вчера (LLM)",
    )
    parser.add_argument(
        "--export-crm-excel",
        action="store_true",
        help="Сгенерировать Excel из сохранённого crm_report_*.json (без LLM)",
    )
    parser.add_argument(
        "--crm-date",
        type=str,
        default=None,
        help="Дата CRM-анализа YYYY-MM-DD (с --analyze-crm-yesterday или --export-crm-excel)",
    )
    parser.add_argument(
        "--crm-main-run",
        action="store_true",
        help="Основной прогон: календарная прошлая неделя (пн–вс), LLM по каждому дню",
    )
    parser.add_argument(
        "--crm-from",
        type=str,
        default=None,
        help="Начало периода CRM YYYY-MM-DD (с --crm-to)",
    )
    parser.add_argument(
        "--crm-to",
        type=str,
        default=None,
        help="Конец периода CRM YYYY-MM-DD",
    )
    parser.add_argument(
        "--crm-force",
        action="store_true",
        help="Пересчитать день даже если crm_report_*.json уже есть",
    )
    parser.add_argument(
        "--recalc-crm-rt",
        action="store_true",
        help="Пересчитать метрики скорости из raw JSONL без LLM (--crm-date или все дни)",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Путь к DOCX (переопределяет INPUT_FILE из .env)",
    )
    args = parser.parse_args()

    if not any([
        args.export_docs,
        args.analyze,
        args.parse_only,
        args.fetch_crm,
        args.analyze_crm_yesterday,
        args.crm_date and not args.export_crm_excel,
        args.export_crm_excel,
        args.crm_main_run,
        args.crm_from,
        args.crm_to,
        args.recalc_crm_rt,
    ]):
        parser.print_help()
        print(
            "\nПодсказка: --export-docs — безопасно, без API. "
            "--fetch-crm — переписки из Leeloo CRM. "
            "--analyze-crm-yesterday — ежедневный CRM-анализ за вчера. "
            "--crm-main-run — основной прогон за прошлую неделю. "
            "--analyze — только когда нужен новый LLM-прогон DOCX."
        )
        return 0

    settings = get_settings()
    if args.input:
        from dataclasses import replace

        settings = replace(settings, input_file=settings.project_root / args.input)

    try:
        if args.export_docs:
            docs_path = export_docs(settings)
            print(f"Documentation exported to: {docs_path}")
        elif args.fetch_crm:
            from crm_fetch import fetch_last_n_days

            if args.crm_days < 1:
                print("Error: --crm-days must be >= 1", file=sys.stderr)
                return 1
            out = settings.output_dir / "crm_raw"
            summary = fetch_last_n_days(days=args.crm_days, output_dir=out)
            print(f"CRM export ({args.crm_days} days)")
            print(f"Discovery: {summary['discovery_count']} channels")
            print(f"Dialogs:   {summary['channels']}")
            print(f"Messages:  {summary['messages']}")
            print(f"JSONL:     {summary['jsonl']}")
            print(f"Markdown:  {summary['markdown']}")
            if summary.get("manifest"):
                print(f"Manifest:  {summary['manifest']}")
        elif args.export_crm_excel:
            from crm_excel_export import export_excel_from_existing_json

            paths = export_excel_from_existing_json(
                settings.output_dir,
                target_date=args.crm_date,
            )
            print("Excel exported:")
            for k, v in paths.items():
                print(f"  {k}: {v}")
        elif args.recalc_crm_rt:
            from crm_analysis import recalc_response_times_in_report
            from crm_excel_export import export_crm_excel, load_all_daily_reports, load_report_from_json

            if args.crm_date:
                paths_list = [settings.output_dir / f"crm_report_{args.crm_date}.json"]
            else:
                paths_list = [
                    settings.output_dir / f"crm_report_{r.meta.target_date}.json"
                    for r in load_all_daily_reports(settings.output_dir)
                ]
            for p in paths_list:
                if not p.exists():
                    print(f"Skip (missing): {p}")
                    continue
                report = load_report_from_json(p)
                updated = recalc_response_times_in_report(report, settings)
                p.write_text(
                    __import__("json").dumps(updated.to_json_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                export_crm_excel(updated, settings.output_dir / "crm_excel")
                print(f"Recalc RT: {p.name}")
        elif args.crm_main_run or args.crm_from or args.crm_to:
            from crm_batch import previous_calendar_week, run_crm_main_run, run_crm_period

            force = args.crm_force
            if args.crm_main_run:
                result = run_crm_main_run(settings, skip_existing=not force, force=force)
            else:
                if not args.crm_from or not args.crm_to:
                    print("Error: --crm-from and --crm-to required", file=sys.stderr)
                    return 1
                try:
                    d_from = date.fromisoformat(args.crm_from)
                    d_to = date.fromisoformat(args.crm_to)
                except ValueError:
                    print("Error: dates must be YYYY-MM-DD", file=sys.stderr)
                    return 1
                result = run_crm_period(
                    settings, d_from, d_to, skip_existing=not force, force=force
                )
            print(f"Period: {result.date_from} .. {result.date_to}")
            print(f"Analyzed: {len(result.days_analyzed)} — {', '.join(result.days_analyzed) or '—'}")
            print(f"Skipped:  {len(result.days_skipped)} — {', '.join(result.days_skipped) or '—'}")
            if result.days_failed:
                print(f"Failed:   {', '.join(result.days_failed)}")
            if result.period_json:
                print(f"Period JSON:  {result.period_json}")
            if result.period_md:
                print(f"Period MD:    {result.period_md}")
            if result.period_excel:
                print(f"Period Excel: {result.period_excel}")
        elif args.analyze_crm_yesterday or args.crm_date:
            from crm_analysis import run_crm_analysis

            if args.crm_date:
                try:
                    target = date.fromisoformat(args.crm_date)
                except ValueError:
                    print("Error: --crm-date must be YYYY-MM-DD", file=sys.stderr)
                    return 1
            else:
                target = (datetime.now().astimezone() - timedelta(days=1)).date()

            report = run_crm_analysis(settings, target_date=target)
            agg = report.aggregate
            print(f"CRM analysis for {target.isoformat()}")
            print(f"Dialogs:  {report.meta.dialogs_count}")
            print(f"Messages: {report.meta.messages_count}")
            if agg.avg_scores:
                print("Average scores:")
                for k, v in agg.avg_scores.items():
                    print(f"  {k}: {v}")
            rt = agg.response_time
            if rt.avg_seconds is not None:
                print(
                    f"Response time: avg {rt.avg_seconds:.0f}s, "
                    f"min {rt.min_seconds:.0f}s ({rt.min_dialog}), "
                    f"max {rt.max_seconds:.0f}s ({rt.max_dialog})"
                )
            out_json = settings.output_dir / f"crm_report_{target.isoformat()}.json"
            out_md = settings.project_root / "docs" / "analysis" / f"CRM_REPORT_{target.isoformat()}.md"
            print(f"JSON: {out_json}")
            print(f"MD:   {out_md}")
            excel_daily = settings.output_dir / "crm_excel" / f"CRM_DAILY_{target.isoformat()}.xlsx"
            excel_master = settings.output_dir / "crm_excel" / "CRM_SUMMARY.xlsx"
            if excel_daily.exists():
                print(f"Excel (день):  {excel_daily}")
            if excel_master.exists():
                print(f"Excel (свод):  {excel_master}")
                if excel_daily.exists() and excel_master.stat().st_mtime < excel_daily.stat().st_mtime:
                    print(
                        "WARNING: CRM_SUMMARY.xlsx старше дневного файла — "
                        "свод мог не обновиться (закройте его в Excel и "
                        "запустите: py -3.12 main.py --export-crm-excel)",
                        file=sys.stderr,
                    )
            else:
                print(
                    "WARNING: CRM_SUMMARY.xlsx не найден после анализа — "
                    "запустите: py -3.12 main.py --export-crm-excel",
                    file=sys.stderr,
                )
        elif args.parse_only:
            path = run_parse_only(settings)
            print(f"Parsed dialogs saved to: {path}")
        elif args.analyze:
            report = run_analysis(settings, resume=args.resume)
            print(f"Analysis complete: {report.meta.dialogs_count} dialogs")
            print(
                f"Average scores: needs_id={report.aggregate.avg_scores.needs_id}, "
                f"cta={report.aggregate.avg_scores.cta}"
            )
            if report.aggregate.team_top_errors:
                print("\nTop errors:")
                for err in report.aggregate.team_top_errors:
                    print(f"  - {err.error} ({err.count}x, {err.percent}%)")
            print(f"\nReport: {settings.output_dir / 'report_41.json'}")
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
