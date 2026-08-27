import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sheetagent.config import Config  # noqa: E402
from sheetagent.events import EventBus  # noqa: E402
from sheetagent.registry import REGISTRY, ToolContext  # noqa: E402
import sheetagent.tools  # noqa: E402,F401


@pytest.fixture
def config(tmp_path):
    cfg = Config()
    cfg.output_dir = str(tmp_path / "output")
    cfg.excel.output_dir = cfg.output_dir
    cfg.excel.engine = "openpyxl"
    cfg.memory_file = str(tmp_path / "memory.json")
    cfg.log_dir = str(tmp_path / "logs")
    cfg.retry.initial_delay = 0.0
    return cfg


@pytest.fixture
def ctx(config):
    return ToolContext(config=config, events=EventBus())


@pytest.fixture
def registry():
    return REGISTRY
