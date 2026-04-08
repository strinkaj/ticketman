"""Configuration loader — merges YAML config with environment variables."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from ticketman.models import AppConfig

DEFAULT_CONFIG_PATH = Path("config/config.yaml")


def load_config(path: Path | None = None) -> AppConfig:
    """Load config from YAML file, then overlay environment variables.

    Priority: env vars > YAML file > defaults.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    data: dict = {}

    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    config = AppConfig.model_validate(data)

    # Overlay environment variables for secrets
    if pw := os.environ.get("TM_PASSWORD"):
        config.ticketmaster.password = pw

    if key := os.environ.get("CAPTCHA_API_KEY"):
        config.captcha.api_key = key

    if sid := os.environ.get("TWILIO_SID"):
        config.notifications.twilio_sid = sid
    if token := os.environ.get("TWILIO_TOKEN"):
        config.notifications.twilio_token = token
    if from_ := os.environ.get("TWILIO_FROM"):
        config.notifications.twilio_from = from_
    if to := os.environ.get("TWILIO_TO"):
        config.notifications.phone_to = to

    return config
