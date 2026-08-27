"""Configuration: YAML file + environment overrides.

Nothing about the workflow is hardcoded in the tools themselves - output paths,
which tools are enabled, retry policy and the model all come from here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(os.environ.get("SHEETAGENT_CONFIG", "config.yaml"))


@dataclass
class RetryConfig:
    max_attempts: int = 3
    initial_delay: float = 1.0
    backoff: float = 2.0
    max_delay: float = 15.0


@dataclass
class ExcelConfig:
    #: "auto" -> COM on Windows, openpyxl elsewhere. Also "com" | "openpyxl".
    engine: str = "auto"
    visible: bool = True
    close_after_save: bool = False
    output_dir: str = "output"


@dataclass
class SheetsConfig:
    credentials_file: str = "credentials.json"
    token_file: str = "token.json"
    #: Blank -> create a fresh spreadsheet each run.
    spreadsheet_id: str = ""
    worksheet_title: str = "Employees"
    share_with: list[str] = field(default_factory=list)


@dataclass
class AgentConfig:
    #: gemini | anthropic. Selects the client; the tool registry and its
    #: schemas are shared, so switching providers changes no tool code.
    #: Gemini is the default because it is the verified path.
    provider: str = "gemini"
    model: str = "gemini-3.1-flash-lite"
    max_tokens: int = 4096
    max_iterations: int = 20
    temperature: float = 0.0
    enabled_tools: list[str] = field(
        default_factory=lambda: [
            "generate_employee_csv",
            "import_csv_to_excel",
            "import_csv_to_google_sheets",
            "verify_imports",
        ]
    )


@dataclass
class Config:
    agent: AgentConfig = field(default_factory=AgentConfig)
    excel: ExcelConfig = field(default_factory=ExcelConfig)
    sheets: SheetsConfig = field(default_factory=SheetsConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    output_dir: str = "output"
    log_level: str = "INFO"
    log_dir: str = "logs"
    memory_file: str = "memory/conversation.json"

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        path = Path(path) if path else DEFAULT_CONFIG_PATH
        raw: dict[str, Any] = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cfg = cls(
            agent=AgentConfig(**raw.get("agent", {})),
            excel=ExcelConfig(**raw.get("excel", {})),
            sheets=SheetsConfig(**raw.get("sheets", {})),
            retry=RetryConfig(**raw.get("retry", {})),
            output_dir=raw.get("output_dir", "output"),
            log_level=raw.get("log_level", "INFO"),
            log_dir=raw.get("log_dir", "logs"),
            memory_file=raw.get("memory_file", "memory/conversation.json"),
        )
        # Environment always wins - handy for CI and Docker.
        if v := os.environ.get("SHEETAGENT_PROVIDER"):
            cfg.agent.provider = v
        if v := os.environ.get("SHEETAGENT_MODEL"):
            cfg.agent.model = v
        if v := os.environ.get("SHEETAGENT_EXCEL_ENGINE"):
            cfg.excel.engine = v
        if v := os.environ.get("SHEETAGENT_SPREADSHEET_ID"):
            cfg.sheets.spreadsheet_id = v
        if v := os.environ.get("SHEETAGENT_LOG_LEVEL"):
            cfg.log_level = v
        if v := os.environ.get("GOOGLE_CREDENTIALS_FILE"):
            cfg.sheets.credentials_file = v
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
