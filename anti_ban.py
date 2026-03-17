"""Anti-ban system — 6-layer protection for WhatsApp account safety."""

from __future__ import annotations

import json
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from config import AntiBanConfig, DelayConfig


@dataclass
class ContactReputation:
    """Per-contact tracking for reputation system."""
    last_sent_time: str = ""     # ISO timestamp
    failure_count: int = 0
    is_blocked: bool = False


@dataclass
class SessionStats:
    """Mutable session state tracked across messages."""
    messages_sent_today: int = 0
    consecutive_failures: int = 0
    batch_count: int = 0
    current_batch_target: int = 0   # randomized batch size for this cycle
    campaign_start_date: str = ""   # ISO date
    day_number: int = 1
    last_send_time: float = 0.0
    next_health_check_at: int = 0   # message count for next check
    recent_results: list[bool] = field(default_factory=list)  # True=success, rolling window
    contact_reputation: dict[str, dict] = field(default_factory=dict)


class AntiBanGuard:
    """Central anti-ban controller.

    Layers:
    1. Message uniqueness (handled by MessageEngine via template rotation)
    2. Volume control with warm-up
    3. Timing humanization (gaussian delays, batch pauses, typing sim)
    4. Behavior simulation (idle actions — triggered by campaign_manager)
    5. Failure detection (consecutive + rate-based)
    6. Contact reputation system
    """

    def __init__(self, delay_cfg: DelayConfig, ban_cfg: AntiBanConfig):
        self._delay = delay_cfg
        self._ban = ban_cfg
        self.stats = SessionStats()
        self._recent_results: deque[bool] = deque(maxlen=ban_cfg.failure_rate_window)
        self._randomize_batch_target()
        self._randomize_health_check()

    # ── Volume Control ──────────────────────────────────────────

    def get_daily_limit(self) -> int:
        """Calculate today's allowed volume based on warm-up schedule."""
        if self.stats.day_number >= self._ban.warmup_days:
            return self._ban.daily_limit_warmed_up
        progress = self.stats.day_number / self._ban.warmup_days
        return int(
            self._ban.warmup_start_volume
            + progress * (self._ban.daily_limit_warmed_up - self._ban.warmup_start_volume)
        )

    def can_send(self) -> tuple[bool, str]:
        """Pre-flight check before each message.

        Returns ``(allowed, reason)``."""
        if self.stats.messages_sent_today >= self.get_daily_limit():
            return False, f"Daily volume limit reached ({self.get_daily_limit()})"

        if self.stats.consecutive_failures >= self._ban.consecutive_failure_threshold:
            return False, f"Too many consecutive failures ({self.stats.consecutive_failures})"

        # Rolling failure rate check
        if len(self._recent_results) >= self._ban.failure_rate_window:
            failures = sum(1 for r in self._recent_results if not r)
            rate = failures / len(self._recent_results)
            if rate > self._ban.failure_rate_threshold:
                return False, f"Failure rate too high ({rate:.0%} in last {len(self._recent_results)} messages)"

        return True, ""

    # ── Contact Reputation ──────────────────────────────────────

    def should_skip(self, phone: str) -> tuple[bool, str]:
        """Check if a contact should be skipped.

        Returns ``(skip, reason)``."""
        rep = self._get_reputation(phone)

        if rep.is_blocked and self._ban.skip_blocked_numbers:
            return True, "Previously blocked"

        if rep.failure_count >= self._ban.max_retries + 1:
            return True, "Max retries exceeded"

        if rep.last_sent_time:
            last = datetime.fromisoformat(rep.last_sent_time)
            hours_since = (datetime.now() - last).total_seconds() / 3600
            if hours_since < self._ban.min_resend_hours:
                return True, f"Sent recently ({hours_since:.1f}h ago)"

        return False, ""

    def _get_reputation(self, phone: str) -> ContactReputation:
        data = self.stats.contact_reputation.get(phone, {})
        return ContactReputation(**data) if data else ContactReputation()

    def _set_reputation(self, phone: str, rep: ContactReputation) -> None:
        self.stats.contact_reputation[phone] = {
            "last_sent_time": rep.last_sent_time,
            "failure_count": rep.failure_count,
            "is_blocked": rep.is_blocked,
        }

    # ── Timing Humanization ─────────────────────────────────────

    def get_message_delay(self) -> float:
        """Gaussian-distributed delay clamped to [min, max]."""
        delay = random.gauss(self._delay.msg_delay_mean, self._delay.msg_delay_std)
        return max(self._delay.msg_delay_min, min(self._delay.msg_delay_max, delay))

    def get_batch_pause(self) -> float | None:
        """Return a pause duration if batch boundary reached, else ``None``."""
        if self.stats.batch_count >= self.stats.current_batch_target:
            pause = random.uniform(self._delay.batch_pause_min, self._delay.batch_pause_max)
            self.stats.batch_count = 0
            self._randomize_batch_target()
            return pause
        return None

    def get_typing_delay(self, char: str) -> float:
        """Per-character typing delay that varies by character type."""
        base = random.uniform(
            self._delay.typing_char_delay_min,
            self._delay.typing_char_delay_max,
        )

        if char == " ":
            base *= 1.5
        elif char in ".,!?:;":
            base *= 2.0
        elif char == "\n":
            base *= 3.0

        # Random mid-typing pause (simulates thinking)
        if random.random() < self._delay.typing_pause_probability:
            base += random.uniform(
                self._delay.typing_pause_duration_min,
                self._delay.typing_pause_duration_max,
            )

        return base

    # ── Failure Detection ───────────────────────────────────────

    def record_success(self, phone: str) -> None:
        """Update stats after a successful send."""
        self.stats.messages_sent_today += 1
        self.stats.consecutive_failures = 0
        self.stats.batch_count += 1
        self.stats.last_send_time = time.time()
        self._recent_results.append(True)
        self.stats.recent_results = list(self._recent_results)

        rep = self._get_reputation(phone)
        rep.last_sent_time = datetime.now().isoformat()
        self._set_reputation(phone, rep)

    def record_failure(self, phone: str, is_block: bool = False) -> None:
        """Update stats after a failure."""
        self.stats.consecutive_failures += 1
        self._recent_results.append(False)
        self.stats.recent_results = list(self._recent_results)

        rep = self._get_reputation(phone)
        rep.failure_count += 1
        if is_block:
            rep.is_blocked = True
        self._set_reputation(phone, rep)

    # ── Health Checks ───────────────────────────────────────────

    def should_health_check(self) -> bool:
        """True if it's time to verify session connectivity."""
        total = self.stats.messages_sent_today
        if total >= self.stats.next_health_check_at:
            self._randomize_health_check()
            return True
        return False

    def should_idle_action(self) -> bool:
        """Randomly decide whether to perform an idle action (~20% chance)."""
        return random.random() < 0.20

    # ── Utilities ───────────────────────────────────────────────

    def sleep_with_jitter(self, base_seconds: float) -> None:
        """Sleep for *base_seconds* +/- 10% random jitter."""
        jitter = base_seconds * 0.1 * (2 * random.random() - 1)
        time.sleep(max(0.1, base_seconds + jitter))

    def update_day_number(self) -> None:
        """Recalculate day_number from campaign_start_date."""
        if not self.stats.campaign_start_date:
            self.stats.campaign_start_date = date.today().isoformat()
            self.stats.day_number = 1
        else:
            start = date.fromisoformat(self.stats.campaign_start_date)
            self.stats.day_number = max(1, (date.today() - start).days + 1)

        # Reset daily counter if day changed
        # (simplistic: relies on process restart or manual check)

    def _randomize_batch_target(self) -> None:
        self.stats.current_batch_target = random.randint(
            self._delay.batch_size_min,
            self._delay.batch_size_max,
        )

    def _randomize_health_check(self) -> None:
        self.stats.next_health_check_at = self.stats.messages_sent_today + random.randint(
            self._ban.health_check_min,
            self._ban.health_check_max,
        )

    # ── State Persistence ───────────────────────────────────────

    def save_state(self, path: str) -> None:
        """Serialize stats to JSON for resume capability."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "messages_sent_today": self.stats.messages_sent_today,
            "consecutive_failures": self.stats.consecutive_failures,
            "batch_count": self.stats.batch_count,
            "current_batch_target": self.stats.current_batch_target,
            "campaign_start_date": self.stats.campaign_start_date,
            "day_number": self.stats.day_number,
            "last_send_time": self.stats.last_send_time,
            "next_health_check_at": self.stats.next_health_check_at,
            "recent_results": self.stats.recent_results,
            "contact_reputation": self.stats.contact_reputation,
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_state(self, path: str) -> bool:
        """Restore stats from JSON. Returns True if state was loaded."""
        p = Path(path)
        if not p.exists():
            return False

        data = json.loads(p.read_text(encoding="utf-8"))

        self.stats.messages_sent_today = data.get("messages_sent_today", 0)
        self.stats.consecutive_failures = data.get("consecutive_failures", 0)
        self.stats.batch_count = data.get("batch_count", 0)
        self.stats.current_batch_target = data.get("current_batch_target", 25)
        self.stats.campaign_start_date = data.get("campaign_start_date", "")
        self.stats.day_number = data.get("day_number", 1)
        self.stats.last_send_time = data.get("last_send_time", 0.0)
        self.stats.next_health_check_at = data.get("next_health_check_at", 0)
        self.stats.recent_results = data.get("recent_results", [])
        self.stats.contact_reputation = data.get("contact_reputation", {})

        self._recent_results = deque(self.stats.recent_results, maxlen=self._ban.failure_rate_window)
        self.update_day_number()
        return True
