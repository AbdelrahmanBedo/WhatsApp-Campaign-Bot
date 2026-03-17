"""Tkinter desktop UI for the WhatsApp Campaign Messaging System."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from campaign_manager import CampaignManager
from config import CampaignConfig


class CampaignApp:
    """Simple launcher GUI for the WhatsApp campaign bot."""

    def __init__(self, root: tk.Tk):
        self._root = root
        self._root.title("WhatsApp Campaign Launcher")
        self._root.geometry("720x620")
        self._root.resizable(False, False)

        # State
        self._queue: queue.Queue = queue.Queue()
        self._manager: CampaignManager | None = None
        self._campaign_thread: threading.Thread | None = None

        # Variables
        self._contacts_var = tk.StringVar()
        self._media_var = tk.StringVar()
        self._chrome_var = tk.StringVar()
        self._daily_limit_var = tk.IntVar(value=100)
        self._dry_run_var = tk.BooleanVar(value=False)
        self._resume_var = tk.BooleanVar(value=False)
        self._status_var = tk.StringVar(value="Idle")
        self._sent_var = tk.IntVar(value=0)
        self._failed_var = tk.IntVar(value=0)
        self._skipped_var = tk.IntVar(value=0)

        # Build UI
        main = ttk.Frame(root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        self._build_file_section(main)
        self._build_templates_section(main)
        self._build_settings_section(main)
        self._build_buttons_section(main)
        self._build_progress_section(main)
        self._build_log_section(main)

        # Handle window close
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI Construction ──────────────────────────────────────────

    def _build_file_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Contacts & Media", padding=8)
        frame.pack(fill=tk.X, pady=(0, 6))

        # Contacts file
        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Contacts file:", width=15).pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self._contacts_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(row1, text="Browse", width=8, command=self._browse_contacts).pack(side=tk.RIGHT)

        # Media
        row2 = ttk.Frame(frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Media (opt):", width=15).pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self._media_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(row2, text="Browse", width=8, command=self._browse_media).pack(side=tk.RIGHT)

        # Chrome profile
        row3 = ttk.Frame(frame)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Chrome profile:", width=15).pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=self._chrome_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(row3, text="Browse", width=8, command=self._browse_chrome_profile).pack(side=tk.RIGHT)

    def _build_templates_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Message Templates (one per line, use {{name}} for placeholders)", padding=8)
        frame.pack(fill=tk.X, pady=(0, 6))

        self._templates_text = tk.Text(frame, height=4, wrap=tk.WORD, font=("Consolas", 10))
        self._templates_text.pack(fill=tk.X)
        self._templates_text.insert("1.0", "Hi {{name}}, we have an exclusive offer for you!")

    def _build_settings_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Settings", padding=8)
        frame.pack(fill=tk.X, pady=(0, 6))

        row = ttk.Frame(frame)
        row.pack(fill=tk.X)

        ttk.Label(row, text="Daily limit:").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=10, to=500, textvariable=self._daily_limit_var, width=6).pack(side=tk.LEFT, padx=(5, 20))
        ttk.Checkbutton(row, text="Dry run", variable=self._dry_run_var).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(row, text="Resume from last state", variable=self._resume_var).pack(side=tk.LEFT)

    def _build_buttons_section(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, 6))

        self._start_btn = ttk.Button(frame, text="Start Campaign", command=self._start_campaign)
        self._start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self._stop_btn = ttk.Button(frame, text="Stop", command=self._stop_campaign, state=tk.DISABLED)
        self._stop_btn.pack(side=tk.RIGHT, ipadx=15)

    def _build_progress_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Progress", padding=8)
        frame.pack(fill=tk.X, pady=(0, 6))

        # Status
        status_row = ttk.Frame(frame)
        status_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self._status_var, font=("", 10, "bold")).pack(side=tk.LEFT, padx=5)

        # Counters
        counter_row = ttk.Frame(frame)
        counter_row.pack(fill=tk.X, pady=(0, 4))
        for label, var in [("Sent:", self._sent_var), ("Failed:", self._failed_var), ("Skipped:", self._skipped_var)]:
            ttk.Label(counter_row, text=label).pack(side=tk.LEFT, padx=(0, 2))
            ttk.Label(counter_row, textvariable=var, width=5, font=("", 10, "bold")).pack(side=tk.LEFT, padx=(0, 15))

        # Progress bar
        self._progress_bar = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self._progress_bar.pack(fill=tk.X)

    def _build_log_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Log", padding=8)
        frame.pack(fill=tk.BOTH, expand=True)

        self._log_text = tk.Text(frame, height=8, wrap=tk.WORD, font=("Consolas", 9), state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.pack(fill=tk.BOTH, expand=True)

    # ── File Dialogs ─────────────────────────────────────────────

    def _browse_contacts(self) -> None:
        path = filedialog.askopenfilename(
            title="Select contacts file",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if path:
            self._contacts_var.set(path)

    def _browse_media(self) -> None:
        path = filedialog.askopenfilename(
            title="Select media file",
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.gif"),
                ("Videos", "*.mp4 *.3gp *.mov"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._media_var.set(path)

    def _browse_chrome_profile(self) -> None:
        path = filedialog.askdirectory(title="Select Chrome profile directory")
        if path:
            self._chrome_var.set(path)

    # ── Campaign Control ─────────────────────────────────────────

    def _start_campaign(self) -> None:
        # Validate contacts
        contacts = self._contacts_var.get().strip()
        if not contacts or not Path(contacts).exists():
            messagebox.showerror("Error", "Please select a valid contacts .xlsx file.")
            return

        # Validate templates
        raw = self._templates_text.get("1.0", tk.END).strip()
        templates = [t.strip() for t in raw.splitlines() if t.strip()]
        if not templates:
            messagebox.showerror("Error", "Enter at least one message template.")
            return

        # Build config
        config = CampaignConfig()
        config.contacts_file = contacts
        config.message_templates = templates
        config.media_path = self._media_var.get().strip() or None
        config.chrome_profile_dir = self._chrome_var.get().strip()
        config.dry_run = self._dry_run_var.get()
        config.resume = self._resume_var.get()
        config.anti_ban.daily_limit_warmed_up = self._daily_limit_var.get()

        # Create manager and attach callbacks
        self._manager = CampaignManager(config)
        self._manager.set_progress_callback(
            lambda s, f, sk, t: self._queue.put(("progress", (s, f, sk, t)))
        )
        self._manager.set_event_callback(
            lambda lvl, msg: self._queue.put(("event", (lvl, msg)))
        )

        # Reset UI
        self._sent_var.set(0)
        self._failed_var.set(0)
        self._skipped_var.set(0)
        self._progress_bar["value"] = 0
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)
        self._status_var.set("Running")
        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)

        # Launch worker thread
        self._campaign_thread = threading.Thread(
            target=self._campaign_worker, daemon=True
        )
        self._campaign_thread.start()
        self._poll_queue()

    def _stop_campaign(self) -> None:
        if self._manager:
            self._manager.request_stop()
        self._stop_btn.configure(state=tk.DISABLED)
        self._status_var.set("Stopping...")

    def _campaign_worker(self) -> None:
        """Run the campaign in a background thread."""
        try:
            self._manager.run()
        except Exception as exc:
            self._queue.put(("event", ("ERROR", f"Campaign crashed: {exc}")))
        finally:
            status = self._manager._state.status if self._manager else "unknown"
            self._queue.put(("status", status))
            self._queue.put(("finished", None))

    # ── Queue Polling ────────────────────────────────────────────

    def _poll_queue(self) -> None:
        for _ in range(20):
            try:
                msg_type, data = self._queue.get_nowait()
            except queue.Empty:
                break

            if msg_type == "progress":
                sent, failed, skipped, total = data
                self._sent_var.set(sent)
                self._failed_var.set(failed)
                self._skipped_var.set(skipped)
                processed = sent + failed + skipped
                if total > 0:
                    self._progress_bar["value"] = (processed / total) * 100

            elif msg_type == "event":
                level, message = data
                ts = datetime.now().strftime("%H:%M:%S")
                self._log_text.configure(state=tk.NORMAL)
                self._log_text.insert(tk.END, f"[{ts}] [{level}] {message}\n")
                self._log_text.see(tk.END)
                self._log_text.configure(state=tk.DISABLED)

            elif msg_type == "status":
                self._status_var.set(str(data).capitalize())

            elif msg_type == "finished":
                self._start_btn.configure(state=tk.NORMAL)
                self._stop_btn.configure(state=tk.DISABLED)

        # Re-schedule while thread is alive
        if self._campaign_thread and self._campaign_thread.is_alive():
            self._root.after(100, self._poll_queue)
        else:
            # Final drain
            self._root.after(200, self._poll_queue_final)

    def _poll_queue_final(self) -> None:
        """Drain any remaining messages after thread exits."""
        while not self._queue.empty():
            try:
                msg_type, data = self._queue.get_nowait()
                if msg_type == "progress":
                    sent, failed, skipped, total = data
                    self._sent_var.set(sent)
                    self._failed_var.set(failed)
                    self._skipped_var.set(skipped)
                    if total > 0:
                        self._progress_bar["value"] = ((sent + failed + skipped) / total) * 100
                elif msg_type == "event":
                    ts = datetime.now().strftime("%H:%M:%S")
                    self._log_text.configure(state=tk.NORMAL)
                    self._log_text.insert(tk.END, f"[{ts}] [{data[0]}] {data[1]}\n")
                    self._log_text.see(tk.END)
                    self._log_text.configure(state=tk.DISABLED)
                elif msg_type == "status":
                    self._status_var.set(str(data).capitalize())
                elif msg_type == "finished":
                    self._start_btn.configure(state=tk.NORMAL)
                    self._stop_btn.configure(state=tk.DISABLED)
            except queue.Empty:
                break

    # ── Window Close ─────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._campaign_thread and self._campaign_thread.is_alive():
            if self._manager:
                self._manager.request_stop()
            self._campaign_thread.join(timeout=2)
        self._root.destroy()


def main() -> None:
    root = tk.Tk()
    CampaignApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
