"""Configuration constants for the WhatsApp campaign system."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class DelayConfig:
    """Timing parameters for human-like behavior simulation."""

    # Inter-message delay (Gaussian distribution)
    msg_delay_min: float = 10.0
    msg_delay_max: float = 30.0
    msg_delay_mean: float = 18.0
    msg_delay_std: float = 5.0

    # Batch pauses
    batch_size_min: int = 20
    batch_size_max: int = 30
    batch_pause_min: float = 120.0   # 2 minutes
    batch_pause_max: float = 300.0   # 5 minutes

    # Typing simulation
    typing_char_delay_min: float = 0.03
    typing_char_delay_max: float = 0.12
    typing_pause_probability: float = 0.05
    typing_pause_duration_min: float = 0.5
    typing_pause_duration_max: float = 2.0


@dataclass
class AntiBanConfig:
    """Safety parameters for avoiding WhatsApp account bans."""

    # Volume control
    daily_limit_new_account: int = 100
    daily_limit_warmed_up: int = 300
    warmup_days: int = 7
    warmup_start_volume: int = 30

    # Failure thresholds
    consecutive_failure_threshold: int = 5
    failure_rate_threshold: float = 0.30   # 30% in recent window
    failure_rate_window: int = 20          # last N messages

    # Retry
    max_retries: int = 2

    # Health check interval (randomized between these values)
    health_check_min: int = 7
    health_check_max: int = 15

    # Contact reputation
    skip_blocked_numbers: bool = True
    min_resend_hours: int = 24  # minimum hours before re-sending to same contact


@dataclass
class CampaignConfig:
    """Top-level campaign configuration."""

    contacts_file: str = ""
    message_templates: list[str] = field(default_factory=list)
    media_path: str | None = None
    log_file: str = "data/campaign_log.csv"
    state_file: str = "data/campaign_state.json"
    chrome_profile_dir: str = ""
    headless: bool = False
    dry_run: bool = False
    resume: bool = False
    delay: DelayConfig = field(default_factory=DelayConfig)
    anti_ban: AntiBanConfig = field(default_factory=AntiBanConfig)

    @classmethod
    def from_json(cls, path: str) -> CampaignConfig:
        """Load config from a JSON file, merging with defaults."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        delay_data = data.pop("delay", {})
        anti_ban_data = data.pop("anti_ban", {})

        config = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if delay_data:
            config.delay = DelayConfig(**{k: v for k, v in delay_data.items() if k in DelayConfig.__dataclass_fields__})
        if anti_ban_data:
            config.anti_ban = AntiBanConfig(**{k: v for k, v in anti_ban_data.items() if k in AntiBanConfig.__dataclass_fields__})
        return config

    def to_json(self, path: str) -> None:
        """Persist current config to JSON."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(asdict(self), indent=2, default=str),
            encoding="utf-8",
        )
