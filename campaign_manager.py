"""Campaign orchestrator — ties all modules together."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from anti_ban import AntiBanGuard
from config import CampaignConfig
from excel_handler import Contact, ExcelHandler
from logger import CampaignLogger, LogLevel, MessageRecord
from message_engine import MessageEngine
from whatsapp_bot import SendStatus, WhatsAppBot


class CampaignState:
    """Tracks campaign progress for resume capability."""

    def __init__(self) -> None:
        self.last_processed_index: int = 0
        self.contacts_file: str = ""
        self.started_at: str = ""
        self.status: str = "pending"  # pending | running | paused | completed | aborted

    def to_dict(self) -> dict:
        return {
            "last_processed_index": self.last_processed_index,
            "contacts_file": self.contacts_file,
            "started_at": self.started_at,
            "status": self.status,
        }

    def from_dict(self, data: dict) -> None:
        self.last_processed_index = data.get("last_processed_index", 0)
        self.contacts_file = data.get("contacts_file", "")
        self.started_at = data.get("started_at", "")
        self.status = data.get("status", "pending")


class CampaignManager:
    """Orchestrates the full campaign lifecycle."""

    def __init__(self, config: CampaignConfig):
        self._config = config
        self._stop_event = threading.Event()
        self._excel = ExcelHandler(config.contacts_file)
        self._engine = MessageEngine(config.message_templates)
        self._bot = WhatsAppBot(
            chrome_profile=config.chrome_profile_dir,
            headless=config.headless,
            delay_config=config.delay,
        )
        self._guard = AntiBanGuard(config.delay, config.anti_ban, self._stop_event)
        self._logger = CampaignLogger(config.log_file)
        self._state = CampaignState()
        self._contacts: list[Contact] = []

    # ── UI Integration ───────────────────────────────────────────

    def request_stop(self) -> None:
        """Signal the campaign to stop gracefully (thread-safe)."""
        self._stop_event.set()

    def set_progress_callback(self, cb) -> None:
        """Attach a progress callback: cb(sent, failed, skipped, total)."""
        self._logger._on_progress = cb

    def set_event_callback(self, cb) -> None:
        """Attach an event callback: cb(level_str, message_str)."""
        self._logger._on_event = cb

    def run(self) -> None:
        """Full campaign lifecycle."""
        # Load contacts
        self._contacts = self._excel.read_contacts()
        if not self._contacts:
            self._logger.log_event(LogLevel.ERROR, "No valid contacts found")
            return

        self._logger.log_event(
            LogLevel.INFO,
            f"Loaded {len(self._contacts)} contacts from {self._config.contacts_file}",
        )

        # Restore state if resuming
        if self._config.resume:
            self._try_restore_state()

        # Initialize day tracking
        self._guard.update_day_number()
        daily_limit = self._guard.get_daily_limit()
        self._logger.log_event(
            LogLevel.INFO,
            f"Day {self._guard.stats.day_number} — daily limit: {daily_limit} messages",
        )

        # Dry-run mode
        if self._config.dry_run:
            self._dry_run()
            return

        # Start WhatsApp session
        if not self._bot.start_session():
            self._logger.log_event(LogLevel.ERROR, "Failed to start WhatsApp session")
            return

        self._logger.start(len(self._contacts))
        self._state.status = "running"
        self._state.started_at = datetime.now().isoformat()
        self._state.contacts_file = self._config.contacts_file

        try:
            self._send_loop()
        except KeyboardInterrupt:
            self._logger.log_event(LogLevel.WARN, "Campaign interrupted by user (Ctrl+C)")
            self._state.status = "paused"
        finally:
            self._save_state()
            self._logger.print_summary()
            self._logger.close()
            self._bot.close()

    # ── Core Send Loop ──────────────────────────────────────────

    def _send_loop(self) -> None:
        start_idx = self._state.last_processed_index

        for i, contact in enumerate(self._contacts[start_idx:], start=start_idx):
            # Stop signal from UI or external caller
            if self._stop_event.is_set():
                self._logger.log_event(LogLevel.WARN, "Campaign stopped by user")
                self._state.status = "paused"
                break

            # Pre-flight: can we send?
            allowed, reason = self._guard.can_send()
            if not allowed:
                self._logger.log_event(LogLevel.WARN, f"Stopping: {reason}")
                self._state.status = "paused"
                break

            # Should we skip this contact?
            skip, skip_reason = self._guard.should_skip(contact.phone_number)
            if skip:
                self._log_skip(contact, skip_reason)
                self._state.last_processed_index = i + 1
                continue

            # Batch pause check
            pause = self._guard.get_batch_pause()
            if pause is not None:
                self._logger.log_event(
                    LogLevel.INFO, f"Batch pause: {pause:.0f}s"
                )
                self._guard.sleep_with_jitter(pause)

            # Random idle action (~20% chance)
            if self._guard.should_idle_action():
                self._logger.log_event(LogLevel.INFO, "Performing idle action...")
                self._bot.perform_idle_action()

            # Render and send
            message = self._engine.render(contact)
            status = self._send_with_retry(contact, message)

            # Update progress
            self._state.last_processed_index = i + 1
            self._save_state()

            # Inter-message delay (only after success or non-fatal failure)
            if status not in (SendStatus.DISCONNECTED,):
                delay = self._guard.get_message_delay()
                self._logger.log_event(
                    LogLevel.INFO, f"Waiting {delay:.1f}s before next message"
                )
                self._guard.sleep_with_jitter(delay)

            # Session disconnected — stop
            if status == SendStatus.DISCONNECTED:
                self._logger.log_event(LogLevel.ERROR, "Session disconnected — stopping")
                self._state.status = "paused"
                break

            # Periodic health check
            if self._guard.should_health_check():
                self._logger.log_event(LogLevel.INFO, "Running health check...")
                if not self._bot.is_connected():
                    self._logger.log_event(LogLevel.ERROR, "Health check failed — session lost")
                    self._state.status = "paused"
                    break
                self._logger.log_event(LogLevel.SUCCESS, "Health check passed")

        else:
            self._state.status = "completed"
            self._logger.log_event(LogLevel.SUCCESS, "Campaign completed successfully")

    # ── Retry Logic ─────────────────────────────────────────────

    def _send_with_retry(self, contact: Contact, message: str) -> SendStatus:
        """Try sending up to max_retries + 1 times."""
        for attempt in range(self._config.anti_ban.max_retries + 1):
            if self._config.media_path:
                status = self._bot.send_media(
                    contact.phone_number,
                    self._config.media_path,
                    caption=message,
                )
            else:
                status = self._bot.send_message(contact.phone_number, message)

            self._log_result(contact, status, attempt + 1, message)

            if status == SendStatus.SUCCESS:
                self._guard.record_success(contact.phone_number)
                return status

            if status in (SendStatus.BLOCKED, SendStatus.NUMBER_INVALID):
                self._guard.record_failure(
                    contact.phone_number,
                    is_block=(status == SendStatus.BLOCKED),
                )
                return status

            if status == SendStatus.DISCONNECTED:
                self._guard.record_failure(contact.phone_number)
                return status

            # Retriable failure — short pause then retry
            if self._stop_event.is_set():
                self._guard.record_failure(contact.phone_number)
                return SendStatus.FAILED
            if attempt < self._config.anti_ban.max_retries:
                self._logger.log_event(
                    LogLevel.WARN,
                    f"Retrying {contact.phone_number} (attempt {attempt + 2})",
                )
                self._guard.sleep_with_jitter(5.0)

        self._guard.record_failure(contact.phone_number)
        return SendStatus.FAILED

    # ── Dry Run ─────────────────────────────────────────────────

    def _dry_run(self) -> None:
        """Simulate the campaign without sending any messages."""
        self._logger.log_event(LogLevel.INFO, "=== DRY RUN MODE ===")
        self._logger.start(len(self._contacts))

        start_idx = self._state.last_processed_index
        for i, contact in enumerate(self._contacts[start_idx:], start=start_idx):
            allowed, reason = self._guard.can_send()
            if not allowed:
                self._logger.log_event(LogLevel.WARN, f"Would stop: {reason}")
                break

            skip, skip_reason = self._guard.should_skip(contact.phone_number)
            if skip:
                self._log_skip(contact, skip_reason)
                continue

            message = self._engine.render(contact)
            self._logger.log_event(
                LogLevel.INFO,
                f"[DRY] Would send to {contact.phone_number} ({contact.name}): "
                f"{message[:60]}...",
            )

            record = MessageRecord(
                phone_number=contact.phone_number,
                name=contact.name,
                status="dry_run",
                timestamp=datetime.now().isoformat(),
                attempt_number=1,
                message_preview=message[:50],
            )
            self._logger.log_message(record)

            # Simulate volume counting
            self._guard.stats.messages_sent_today += 1

        self._logger.print_summary()
        self._logger.close()

    # ── State Persistence ───────────────────────────────────────

    def _try_restore_state(self) -> None:
        """Load state from JSON if it matches the current contacts file."""
        state_path = Path(self._config.state_file)
        if not state_path.exists():
            self._logger.log_event(LogLevel.WARN, "No saved state found — starting fresh")
            return

        data = json.loads(state_path.read_text(encoding="utf-8"))
        campaign_data = data.get("campaign", {})

        if campaign_data.get("contacts_file") != self._config.contacts_file:
            self._logger.log_event(
                LogLevel.WARN,
                "Saved state is for a different contacts file — starting fresh",
            )
            return

        self._state.from_dict(campaign_data)
        self._guard.load_state(self._config.state_file)

        self._logger.log_event(
            LogLevel.INFO,
            f"Resumed from index {self._state.last_processed_index} "
            f"({self._guard.stats.messages_sent_today} sent today)",
        )

    def _save_state(self) -> None:
        """Persist campaign state + anti-ban stats."""
        state_path = Path(self._config.state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        # Build combined state
        data = {"campaign": self._state.to_dict()}
        # Anti-ban guard saves its own state to the same path
        self._guard.save_state(self._config.state_file)

        # Merge: read what guard wrote and add campaign data
        existing = json.loads(state_path.read_text(encoding="utf-8"))
        existing["campaign"] = self._state.to_dict()
        state_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    # ── Logging Helpers ─────────────────────────────────────────

    def _log_result(
        self, contact: Contact, status: SendStatus, attempt: int, message: str
    ) -> None:
        status_map = {
            SendStatus.SUCCESS: "sent",
            SendStatus.FAILED: "failed",
            SendStatus.NUMBER_INVALID: "skipped",
            SendStatus.BLOCKED: "blocked",
            SendStatus.DISCONNECTED: "failed",
            SendStatus.TIMEOUT: "failed",
        }
        error_map = {
            SendStatus.FAILED: "Send failed",
            SendStatus.NUMBER_INVALID: "Invalid phone number",
            SendStatus.BLOCKED: "Number blocked or restricted",
            SendStatus.DISCONNECTED: "Session disconnected",
            SendStatus.TIMEOUT: "Send timed out",
        }

        record = MessageRecord(
            phone_number=contact.phone_number,
            name=contact.name,
            status=status_map.get(status, "failed"),
            timestamp=datetime.now().isoformat(),
            attempt_number=attempt,
            error_message=error_map.get(status, ""),
            message_preview=message[:50],
        )
        self._logger.log_message(record)

    def _log_skip(self, contact: Contact, reason: str) -> None:
        record = MessageRecord(
            phone_number=contact.phone_number,
            name=contact.name,
            status="skipped",
            timestamp=datetime.now().isoformat(),
            attempt_number=0,
            error_message=reason,
        )
        self._logger.log_message(record)
