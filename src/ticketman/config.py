"""Configuration and coordination-state persistence.

Config priority: environment variables > YAML file > defaults. The only secret
is the Discovery API key, read from TM_API_KEY.

Four coordination stores live in their own gitignored YAML files, because they
link real people to events (PII) but hold no passwords:
  roster.yaml         the buying group (people)
  watchlist.yaml      events under coordination (the portfolio)
  registrations.yaml  each person's lottery registration and outcome
  outcomes.yaml       labeled past events, for calibration
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from ticketman.models import (
    AppConfig,
    OutcomeLog,
    RegistrationLog,
    Roster,
    Watchlist,
)

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/config.yaml")
DEFAULT_ROSTER_PATH = Path("config/roster.yaml")
DEFAULT_WATCHLIST_PATH = Path("config/watchlist.yaml")
DEFAULT_REGISTRATIONS_PATH = Path("config/registrations.yaml")
DEFAULT_OUTCOMES_PATH = Path("config/outcomes.yaml")


def load_config(path: Path | None = None) -> AppConfig:
    """Load config from YAML, then overlay environment variables."""
    config_path = path or DEFAULT_CONFIG_PATH
    data: dict = {}

    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    config = AppConfig.model_validate(data)

    if key := os.environ.get("TM_API_KEY"):
        config.ticketmaster.api_key = key

    return config


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_yaml(model, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(model.model_dump(mode="json"), f, sort_keys=False)
    return path


def load_roster(path: Path | None = None) -> Roster:
    """Load the buying group. Warns on shared emails (the farming signature)."""
    roster = Roster.model_validate(_load_yaml(path or DEFAULT_ROSTER_PATH))
    dupes = roster.duplicate_emails()
    if dupes:
        log.warning(
            "These emails are shared by more than one participant: %s. "
            "Each account must belong to a distinct real person.",
            ", ".join(dupes),
        )
    return roster


def save_roster(roster: Roster, path: Path | None = None) -> Path:
    return _save_yaml(roster, path or DEFAULT_ROSTER_PATH)


def load_watchlist(path: Path | None = None) -> Watchlist:
    return Watchlist.model_validate(_load_yaml(path or DEFAULT_WATCHLIST_PATH))


def save_watchlist(watchlist: Watchlist, path: Path | None = None) -> Path:
    return _save_yaml(watchlist, path or DEFAULT_WATCHLIST_PATH)


def load_registrations(path: Path | None = None) -> RegistrationLog:
    return RegistrationLog.model_validate(_load_yaml(path or DEFAULT_REGISTRATIONS_PATH))


def save_registrations(reg_log: RegistrationLog, path: Path | None = None) -> Path:
    return _save_yaml(reg_log, path or DEFAULT_REGISTRATIONS_PATH)


def load_outcomes(path: Path | None = None) -> OutcomeLog:
    return OutcomeLog.model_validate(_load_yaml(path or DEFAULT_OUTCOMES_PATH))


def save_outcomes(outcome_log: OutcomeLog, path: Path | None = None) -> Path:
    return _save_yaml(outcome_log, path or DEFAULT_OUTCOMES_PATH)
