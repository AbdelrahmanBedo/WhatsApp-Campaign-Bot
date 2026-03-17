"""CLI entry point for the WhatsApp Campaign Messaging System."""

from __future__ import annotations

import argparse
import sys

from campaign_manager import CampaignManager
from config import CampaignConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WhatsApp Campaign Messaging System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Basic usage
  python main.py contacts.xlsx "Hi {{name}}, check out our new product!"

  # Multiple templates (pipe-separated)
  python main.py contacts.xlsx "Hi {{name}}, we have a deal!|Hello {{name}}, special offer!|Hey {{name}}, check this out!"

  # With media attachment
  python main.py contacts.xlsx "{{name}}, see attached!" --media photo.jpg

  # Resume interrupted campaign
  python main.py contacts.xlsx "Hi {{name}}" --resume

  # Dry run (simulate without sending)
  python main.py contacts.xlsx "Hello {{name}}" --dry-run

  # Persistent Chrome session (skip QR scan)
  python main.py contacts.xlsx "Hi {{name}}" --profile ./chrome_data
""",
    )

    parser.add_argument(
        "contacts",
        help="Path to .xlsx contacts file (must have 'phone_number' column)",
    )
    parser.add_argument(
        "message",
        help=(
            "Message template(s). Use {{name}} for placeholders. "
            "Separate multiple templates with '|' (pipe character)."
        ),
    )
    parser.add_argument(
        "--media",
        help="Path to image or video file to attach",
    )
    parser.add_argument(
        "--config",
        help="Path to JSON config file for advanced settings",
    )
    parser.add_argument(
        "--profile",
        help="Chrome profile directory for persistent WhatsApp session",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last saved campaign state",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome in headless mode (not recommended for WhatsApp Web)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate campaign without sending messages",
    )
    parser.add_argument(
        "--log",
        default="data/campaign_log.csv",
        help="Path for campaign log CSV (default: data/campaign_log.csv)",
    )
    parser.add_argument(
        "--daily-limit",
        type=int,
        help="Override daily message limit",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Build config
    if args.config:
        config = CampaignConfig.from_json(args.config)
    else:
        config = CampaignConfig()

    # CLI args override config file
    config.contacts_file = args.contacts

    # Parse templates (pipe-separated)
    templates = [t.strip() for t in args.message.split("|") if t.strip()]
    if not templates:
        print("Error: At least one message template is required.", file=sys.stderr)
        sys.exit(1)
    config.message_templates = templates

    config.media_path = args.media
    config.log_file = args.log
    config.headless = args.headless
    config.dry_run = args.dry_run
    config.resume = args.resume

    if args.profile:
        config.chrome_profile_dir = args.profile
    if args.daily_limit:
        config.anti_ban.daily_limit_warmed_up = args.daily_limit

    # Print config summary
    print("=" * 50)
    print("  WHATSAPP CAMPAIGN SYSTEM")
    print("=" * 50)
    print(f"  Contacts file  : {config.contacts_file}")
    print(f"  Templates      : {len(config.message_templates)}")
    for i, t in enumerate(config.message_templates, 1):
        print(f"    [{i}] {t[:60]}{'...' if len(t) > 60 else ''}")
    if config.media_path:
        print(f"  Media          : {config.media_path}")
    print(f"  Log file       : {config.log_file}")
    print(f"  Dry run        : {config.dry_run}")
    print(f"  Resume         : {config.resume}")
    print(f"  Headless       : {config.headless}")
    print("=" * 50)

    manager = CampaignManager(config)
    manager.run()


if __name__ == "__main__":
    main()
