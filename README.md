# WhatsApp Campaign Bot

A production-level WhatsApp campaign messaging system built with Python and Selenium. Reads contacts from Excel, sends personalized messages via WhatsApp Web, and prioritizes account safety with a 6-layer anti-ban protection system.

## Features

- **Excel Contact Import** — Read `.xlsx` files with phone validation, deduplication, and custom fields
- **Multi-Template Rotation** — Define 3–5 message variations; one is randomly selected per contact
- **Message Humanization** — Greeting swaps, synonym replacement (~15%), punctuation variation
- **Media Attachments** — Send images and videos with optional captions
- **6-Layer Anti-Ban System** — Template rotation, warm-up volume control, gaussian timing, idle behavior simulation, failure detection, contact reputation tracking
- **Crash-Safe Resume** — State saved after every message; resume with `--resume`
- **Dry-Run Mode** — Simulate the full campaign without sending anything
- **CSV Logging** — Real-time log with status, timestamps, and error details

## Anti-Ban Strategy

| Layer | Protection | Details |
|-------|-----------|---------|
| 1 | **Template Rotation** | Random template per contact — no identical messages |
| 2 | **Volume Control** | Warm-up from 30/day (day 1) to 300/day (day 7+) |
| 3 | **Timing Humanization** | Gaussian delays (10–30s), batch pauses (2–5 min), per-character typing simulation |
| 4 | **Behavior Simulation** | Random idle actions: scrolling chats, opening conversations |
| 5 | **Failure Detection** | Auto-stop on 5 consecutive failures OR >30% failure rate in last 20 messages |
| 6 | **Contact Reputation** | Per-contact tracking: skip blocked numbers, avoid re-sending too frequently |

## Installation

```bash
# Clone the repository
git clone https://github.com/AbdelrahmanBedo/WhatsApp-Campaign-Bot.git
cd WhatsApp-Campaign-Bot

# Install dependencies
pip install -r requirements.txt
```

### Requirements

- Python 3.10+
- Google Chrome browser installed
- ChromeDriver (auto-managed by `webdriver-manager`)

## Usage

### Basic Usage

```bash
python main.py contacts.xlsx "Hi {{name}}, we have an exclusive offer for you!"
```

### Multiple Templates (pipe-separated)

```bash
python main.py contacts.xlsx "Hi {{name}}, check this out!|Hello {{name}}, special offer for you!|Hey {{name}}, don't miss this deal!"
```

### With Media Attachment

```bash
python main.py contacts.xlsx "{{name}}, see the attached image!" --media media/promo.jpg
```

### Dry Run (simulate without sending)

```bash
python main.py contacts.xlsx "Hello {{name}}!" --dry-run
```

### Resume Interrupted Campaign

```bash
python main.py contacts.xlsx "Hi {{name}}!" --resume
```

### Persistent Chrome Session (skip QR scan)

```bash
python main.py contacts.xlsx "Hi {{name}}!" --profile ./chrome_data
```

### All Options

```
positional arguments:
  contacts              Path to .xlsx contacts file (must have 'phone_number' column)
  message               Message template(s), separated by '|' for multiple

optional arguments:
  --media PATH          Path to image or video file to attach
  --config PATH         Path to JSON config file for advanced settings
  --profile DIR         Chrome profile directory for persistent session
  --resume              Resume from last saved campaign state
  --headless            Run Chrome in headless mode (not recommended)
  --dry-run             Simulate campaign without sending messages
  --log PATH            Path for campaign log CSV (default: data/campaign_log.csv)
  --daily-limit N       Override daily message limit
```

## Excel File Format

The contacts file must be `.xlsx` with at least a `phone_number` column:

| phone_number | name | city |
|-------------|------|------|
| +1234567890 | John | NYC |
| +9876543210 | Sara | London |
| +5551234567 | Ahmed | Cairo |

- **phone_number** — Required, with country code
- **name** — Optional, used in `{{name}}` placeholder
- Any additional columns become custom placeholders (e.g., `{{city}}`)

## Project Structure

```
WhatsApp-Campaign-Bot/
├── main.py              # CLI entry point
├── config.py            # Configuration constants (dataclasses)
├── excel_handler.py     # Excel reader with phone validation
├── message_engine.py    # Multi-template rotation & humanization
├── whatsapp_bot.py      # Selenium WhatsApp Web automation
├── anti_ban.py          # 6-layer anti-ban system
├── campaign_manager.py  # Campaign orchestration loop
├── logger.py            # CSV + console logging
├── requirements.txt     # Python dependencies
├── data/                # Campaign logs & state (gitignored)
└── media/               # Media attachments
```

## How It Works

1. **Load** — Reads contacts from Excel, validates phone numbers, removes duplicates
2. **Connect** — Opens WhatsApp Web in Chrome, waits for QR scan (or reuses saved session)
3. **Send Loop** — For each contact:
   - Check daily limit and failure thresholds
   - Check contact reputation (skip blocked/recently sent)
   - Select random template and personalize message
   - Optionally perform idle action (scroll, open chat)
   - Navigate to chat via URL scheme
   - Type message character-by-character with realistic delays
   - Verify delivery (wait for tick/double-tick)
   - Log result to CSV
   - Wait gaussian-distributed delay before next message
   - Pause 2–5 minutes every 20–30 messages
4. **Save** — Campaign state saved after every message for crash recovery

## Configuration

For advanced tuning, create a JSON config file:

```json
{
  "delay": {
    "msg_delay_min": 10.0,
    "msg_delay_max": 30.0,
    "msg_delay_mean": 18.0,
    "msg_delay_std": 5.0,
    "batch_size_min": 20,
    "batch_size_max": 30,
    "batch_pause_min": 120.0,
    "batch_pause_max": 300.0
  },
  "anti_ban": {
    "daily_limit_warmed_up": 300,
    "warmup_days": 7,
    "warmup_start_volume": 30,
    "consecutive_failure_threshold": 5
  }
}
```

Use with: `python main.py contacts.xlsx "Hi {{name}}!" --config my_config.json`

## Safety Tips

- **Start small** — Test with 3–5 contacts first
- **Use `--dry-run`** — Verify everything works before real sends
- **Use `--profile`** — Avoid scanning QR code every time
- **Don't exceed limits** — The warm-up system exists for a reason
- **Monitor logs** — Check `data/campaign_log.csv` for failures
- **Use multiple templates** — Identical messages trigger spam detection

## License

This project is for educational purposes. Use responsibly and in compliance with WhatsApp's Terms of Service.
