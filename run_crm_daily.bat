@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  Ежедневный полный цикл CRM (за вчера)
REM  1) fetch Leeloo за вчера
REM  2) LLM-анализ диалогов
REM  3) JSON + MD + CRM_DAILY + обновление CRM_SUMMARY.xlsx
REM  4) обновление KNOWLEDGE_BASE / docs (без LLM)
REM
REM  Использование:
REM    run_crm_daily.bat              — вчера
REM    run_crm_daily.bat 2026-07-22   — конкретная дата
REM
REM  Перед запуском закройте CRM_SUMMARY.xlsx в Excel!
REM ============================================================

set "PY=py -3.12"
set "DATE_ARG="

if not "%~1"=="" (
  set "DATE_ARG=--crm-date %~1"
  echo [CRM] Прогон за дату: %~1
) else (
  echo [CRM] Прогон за вчера (--analyze-crm-yesterday)
)

echo.
echo === 1/2 Анализ CRM (LLM) ===
%PY% main.py --analyze-crm-yesterday %DATE_ARG%
if errorlevel 1 (
  echo.
  echo [ОШИБКА] Анализ или Excel не завершились.
  echo Если Permission denied на CRM_SUMMARY.xlsx — закройте файл в Excel и выполните:
  echo   %PY% main.py --export-crm-excel %DATE_ARG%
  echo   %PY% main.py --export-docs
  pause
  exit /b 1
)

echo.
echo === 2/2 Обновление базы знаний (без LLM) ===
%PY% main.py --export-docs
if errorlevel 1 (
  echo [ОШИБКА] --export-docs
  pause
  exit /b 1
)

echo.
echo [OK] Готово.
echo   JSON:   output\crm_report_*.json
echo   MD:     docs\analysis\CRM_REPORT_*.md
echo   Excel:  output\crm_excel\
echo   KB:     docs\analysis\KNOWLEDGE_BASE.md
echo.
pause
endlocal
