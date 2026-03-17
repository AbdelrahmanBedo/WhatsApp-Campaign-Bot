"""Logging system — CSV file persistence + real-time console progress."""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class LogLevel(Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


@dataclass
class MessageRecord:
    phone_number: str
    name: str
    status: str        # sent / failed / skipped / blocked
    timestamp: str
    attempt_number: int
    error_message: str = ""
    message_preview: str = ""


class CampaignLogger:
    CSV_HEADERS = [
        "phone_number", "name", "status", "timestamp",
        "attempt_number", "error_message", "message_preview",
    ]

    def __init__(self, log_path: str, verbose: bool = True):
        self._log_path = Path(log_path)
        self._verbose = verbose
        self._total: int = 0
        self._sent: int = 0
        self._failed: int = 0
        self._skipped: int = 0
        self._csv_file = None
        self._csv_writer = None
        # UI callback hooks (set externally, thread-safe via queue)
        self._on_progress = None   # (sent, failed, skipped, total) -> None
        self._on_event = None      # (level_str, message_str) -> None

    def start(self, total_contacts: int) -> None:
        """Initialize CSV file with headers and set total count."""
        self._total = total_contacts
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        file_exists = self._log_path.exists() and self._log_path.stat().st_size > 0
        self._csv_file = open(self._log_path, "a", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=self.CSV_HEADERS)
        if not file_exists:
            self._csv_writer.writeheader()
            self._csv_file.flush()

        self.log_event(LogLevel.INFO, f"Campaign started — {total_contacts} contacts loaded")

    def log_message(self, record: MessageRecord) -> None:
        """Write one row to CSV immediately and update counters."""
        if self._csv_writer:
            self._csv_writer.writerow({
                "phone_number": record.phone_number,
                "name": record.name,
                "status": record.status,
                "timestamp": record.timestamp,
                "attempt_number": record.attempt_number,
                "error_message": record.error_message,
                "message_preview": record.message_preview[:50],
            })
            self._csv_file.flush()

        if record.status == "sent":
            self._sent += 1
        elif record.status in ("failed", "blocked"):
            self._failed += 1
        elif record.status == "skipped":
            self._skipped += 1

        if self._verbose:
            self._print_progress()

        if self._on_progress:
            self._on_progress(self._sent, self._failed, self._skipped, self._total)

    def log_event(self, level: LogLevel, message: str) -> None:
        """Print a timestamped event to the console."""
        if self._verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{ts}] [{level.value}] {message}", flush=True)

        if self._on_event:
            self._on_event(level.value, message)

    def _print_progress(self) -> None:
        processed = self._sent + self._failed + self._skipped
        line = (
            f"\r[{processed}/{self._total}] "
            f"Sent: {self._sent} | Failed: {self._failed} | Skipped: {self._skipped}"
        )
        sys.stdout.write(line)
        sys.stdout.flush()

    def print_summary(self) -> None:
        """Print final campaign statistics."""
        print("\n")
        print("=" * 50)
        print("  CAMPAIGN SUMMARY")
        print("=" * 50)
        print(f"  Total contacts : {self._total}")
        print(f"  Sent           : {self._sent}")
        print(f"  Failed         : {self._failed}")
        print(f"  Skipped        : {self._skipped}")
        remaining = self._total - (self._sent + self._failed + self._skipped)
        if remaining > 0:
            print(f"  Remaining      : {remaining}")
        print(f"  Log file       : {self._log_path}")
        print("=" * 50)

    def close(self) -> None:
        """Flush and close CSV file handle."""
        if self._csv_file:
            self._csv_file.flush()
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None
