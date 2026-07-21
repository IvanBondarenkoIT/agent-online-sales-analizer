"""Application configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    cursor_api_key: str
    openrouter_api_key: str
    llm_model: str
    input_file: Path
    output_dir: Path
    logs_dir: Path
    max_retries: int
    request_delay_sec: float
    project_root: Path
    crm_timezone: str
    crm_work_start: str
    crm_work_end: str
    crm_work_days: str
    crm_sla_work_seconds: int
    crm_sla_off_seconds: int

    @classmethod
    def from_env(cls) -> Settings:
        provider = os.getenv("LLM_PROVIDER", "cursor").strip().lower()
        return cls(
            llm_provider=provider,
            cursor_api_key=os.getenv("CURSOR_API_KEY", "").strip(),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "composer-2.5").strip(),
            input_file=PROJECT_ROOT / os.getenv("INPUT_FILE", "dav.docx"),
            output_dir=PROJECT_ROOT / os.getenv("OUTPUT_DIR", "output"),
            logs_dir=PROJECT_ROOT / os.getenv("LOGS_DIR", "logs"),
            max_retries=int(os.getenv("MAX_RETRIES", "2")),
            request_delay_sec=float(os.getenv("REQUEST_DELAY_SEC", "1")),
            project_root=PROJECT_ROOT,
            crm_timezone=os.getenv("CRM_TIMEZONE", "Asia/Tbilisi").strip(),
            crm_work_start=os.getenv("CRM_WORK_START", "10:00").strip(),
            crm_work_end=os.getenv("CRM_WORK_END", "18:00").strip(),
            crm_work_days=os.getenv("CRM_WORK_DAYS", "0,1,2,3,4").strip(),
            crm_sla_work_seconds=int(os.getenv("CRM_SLA_WORK_SEC", "120")),
            crm_sla_off_seconds=int(os.getenv("CRM_SLA_OFF_SEC", "900")),
        )

    def validate_for_analysis(self) -> None:
        if self.llm_provider == "cursor" and not self.cursor_api_key:
            raise ValueError(
                "CURSOR_API_KEY is required when LLM_PROVIDER=cursor. "
                "Set the key in .env or use LLM_PROVIDER=mock / --parse-only."
            )
        if self.llm_provider == "openrouter" and not self.openrouter_api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter."
            )
        if not self.input_file.exists():
            raise FileNotFoundError(f"Input file not found: {self.input_file}")

    def validate_llm_only(self) -> None:
        """Validate LLM credentials without requiring DOCX input."""
        if self.llm_provider == "cursor" and not self.cursor_api_key:
            raise ValueError(
                "CURSOR_API_KEY is required when LLM_PROVIDER=cursor."
            )
        if self.llm_provider == "openrouter" and not self.openrouter_api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter."
            )

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings.from_env()


def setup_logging(logs_dir: Path, name: str = "dimkava") -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"analyzer_{datetime.now().strftime('%Y%m%d')}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def load_prompt(filename: str) -> str:
    path = PROJECT_ROOT / "prompts" / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
