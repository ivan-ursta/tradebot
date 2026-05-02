"""
utils/logger.py
===============
Logging setup: structured logging with file rotation.
Call setup_logging() once at startup.
"""

from __future__ import annotations

import logging
import logging.config
import logging.handlers
import os
from pathlib import Path

import yaml


def setup_logging(
    config_path: str = "config/logging.yaml",
    log_dir: str = "logs",
    level: str = "INFO",
) -> None:
    """
    Initialise logging from YAML config file.
    Falls back to basic config if YAML is not found.
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    yaml_path = Path(config_path)
    if yaml_path.exists():
        try:
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)
            logging.config.dictConfig(cfg)
            logging.getLogger(__name__).info("Logging initialised from %s", config_path)
            return
        except Exception as exc:
            print(f"Warning: could not load logging config from {config_path}: {exc}")

    # Fallback
    log_level = getattr(logging, level.upper(), logging.INFO)
    log_file = Path(log_dir) / "trading_bot.log"
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.handlers.RotatingFileHandler(
                str(log_file), maxBytes=50 * 1024 * 1024, backupCount=5
            ),
        ],
    )
