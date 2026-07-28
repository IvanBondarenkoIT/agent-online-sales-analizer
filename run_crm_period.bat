@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  Прогон CRM за период (пн–вс или произвольные даты)
REM
REM  Использование:
REM    run_crm_period.bat                         — прошлая календарная неделя
REM    run_crm_period.bat 2026-07-22 2026-07-23   — диапазон
REM    run_crm_period.bat 2026-07-22 2026-07-23 force  — пересчитать даже если JSON есть
REM
REM  Перед запуском закройте CRM_SUMMARY.xlsx и CRM_PERIOD_*.xlsx!
REM ============================================================

set "PY=py -3.12"

if "%~1"=="" (
  echo [CRM] Основной прогон: прошлая календарная неделя
  set "CMD=%PY% main.py --crm-main-run"
) else (
  if "%~2"=="" (
    echo Укажите обе даты: run_crm_period.bat YYYY-MM-DD YYYY-MM-DD
    pause
    exit /b 1
  )
  echo [CRM] Период: %~1 .. %~2
  set "CMD=%PY% main.py --crm-from %~1 --crm-to %~2"
)

if /I "%~3"=="force" (
  set "CMD=%CMD% --crm-force"
  echo [CRM] --crm-force включён
)

echo.
echo === Анализ периода (LLM по дням + period Excel/MD) ===
%CMD%
if errorlevel 1 (
  echo.
  echo [ОШИБКА] Период не завершён. Закройте Excel и повторите, либо:
  echo   %PY% main.py --export-crm-excel
  pause
  exit /b 1
)

echo.
echo === Обновление базы знаний ===
%PY% main.py --export-docs
if errorlevel 1 (
  echo [ОШИБКА] --export-docs
  pause
  exit /b 1
)

echo.
echo [OK] Готово. См. output\crm_excel\ и docs\analysis\CRM_REPORT_PERIOD_*.md
pause
endlocal
