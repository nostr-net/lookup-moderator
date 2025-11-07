#!/usr/bin/env python3
"""
Strfry Write Policy Plugin for Moderation

This plugin integrates with strfry to reject events based on kind 1984 moderation
reports tracked by the lookup_moderator daemon.

It reads JSON from stdin (strfry format) and outputs accept/reject decisions.
"""

import sys
import json
import logging
from pathlib import Path
import yaml

from moderation_db import ModerationDB


# Simple logging setup for plugin (goes to stderr, not stdout)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - strfry-plugin - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


class StrfryModerationPlugin:
    """Strfry write policy plugin for content moderation."""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize plugin.

        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        self.config = self._load_config(config_path)

        # Extract config values
        mod_config = self.config.get("moderation", {})
        self.report_threshold = mod_config.get("report_threshold", 3)
        self.time_window_days = mod_config.get("time_window_days", 30)
        self.type_thresholds = mod_config.get("type_thresholds", {})

        event_config = self.config.get("events", {})
        self.monitored_kinds = set(event_config.get("monitored_kinds", [30817, 31990]))

        plugin_config = self.config.get("strfry_plugin", {})
        self.rejection_message = plugin_config.get(
            "rejection_message", "Content has been reported {count} times by trusted network members"
        )
        self.verbose_rejection = plugin_config.get("verbose_rejection", False)

        db_config = self.config.get("database", {})
        db_path = db_config.get("path", "./moderation_reports.db")

        # Initialize database
        self.db = ModerationDB(db_path)

        # Load WoT cache from database
        self.wot_pubkeys = self.db.get_wot_cache()
        logger.info(f"Plugin initialized with {len(self.wot_pubkeys)} WoT pubkeys")

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file."""
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            # Return minimal config
            return {
                "moderation": {"report_threshold": 3, "time_window_days": 30},
                "events": {"monitored_kinds": [30817, 31990]},
                "database": {"path": "./moderation_reports.db"},
            }

    def should_reject_event(self, event: dict) -> tuple[bool, str]:
        """
        Determine if an event should be rejected based on moderation reports.

        Args:
            event: Event dictionary from strfry

        Returns:
            Tuple of (should_reject, rejection_message)
        """
        event_id = event.get("id")
        event_kind = event.get("kind")

        # Only check monitored kinds (thelookup-specific events)
        if event_kind not in self.monitored_kinds:
            return False, ""

        # Query database for reports
        # Get reports by type to check type-specific thresholds
        reports_by_type = self.db.get_reports_by_type(
            event_id,
            wot_pubkeys=self.wot_pubkeys if self.wot_pubkeys else None,
            time_window_days=self.time_window_days,
        )

        # Check type-specific thresholds first
        for report_type, count in reports_by_type.items():
            threshold = self.type_thresholds.get(report_type, self.report_threshold)
            if count >= threshold:
                msg = self.rejection_message.format(count=count)
                if self.verbose_rejection and report_type:
                    msg += f" (type: {report_type})"
                logger.info(
                    f"Rejecting event {event_id[:16]}... "
                    f"(kind {event_kind}): {count} {report_type} reports"
                )
                return True, msg

        # Check overall threshold
        total_count = self.db.get_report_count(
            event_id,
            wot_pubkeys=self.wot_pubkeys if self.wot_pubkeys else None,
            time_window_days=self.time_window_days,
        )

        if total_count >= self.report_threshold:
            msg = self.rejection_message.format(count=total_count)
            logger.info(
                f"Rejecting event {event_id[:16]}... "
                f"(kind {event_kind}): {total_count} total reports"
            )
            return True, msg

        return False, ""

    def process_event(self, input_msg: dict) -> dict:
        """
        Process a strfry input message and return a decision.

        Args:
            input_msg: Input message from strfry

        Returns:
            Decision dictionary for strfry
        """
        msg_type = input_msg.get("type")
        event = input_msg.get("event", {})
        event_id = event.get("id", "unknown")

        # Currently only handle "new" type
        if msg_type != "new":
            logger.warning(f"Unexpected message type: {msg_type}")
            return {"id": event_id, "action": "accept"}

        # Check if event should be rejected
        should_reject, rejection_msg = self.should_reject_event(event)

        if should_reject:
            return {
                "id": event_id,
                "action": "reject",
                "msg": rejection_msg,
            }
        else:
            return {"id": event_id, "action": "accept"}

    def run(self):
        """Main run loop - read from stdin, process, write to stdout."""
        logger.info("Strfry moderation plugin started")
        logger.info(f"Monitoring kinds: {sorted(self.monitored_kinds)}")
        logger.info(f"Report threshold: {self.report_threshold}")
        logger.info(f"Time window: {self.time_window_days} days")

        try:
            # Read line-by-line from stdin
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue

                try:
                    # Parse input JSON
                    input_msg = json.loads(line)

                    # Process event and get decision
                    decision = self.process_event(input_msg)

                    # Output decision as JSON (minified, followed by newline)
                    output = json.dumps(decision, separators=(",", ":"))
                    print(output, flush=True)

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON input: {e}")
                    # Output accept on error to avoid blocking events
                    print(
                        json.dumps({"id": "unknown", "action": "accept"}),
                        flush=True,
                    )
                except Exception as e:
                    logger.error(f"Error processing event: {e}", exc_info=True)
                    # Output accept on error to avoid blocking events
                    try:
                        event_id = json.loads(line).get("event", {}).get("id", "unknown")
                    except:
                        event_id = "unknown"
                    print(
                        json.dumps({"id": event_id, "action": "accept"}),
                        flush=True,
                    )

        except KeyboardInterrupt:
            logger.info("Plugin stopped by user")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Strfry moderation plugin"
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    args = parser.parse_args()

    # Create and run plugin
    plugin = StrfryModerationPlugin(args.config)
    plugin.run()


if __name__ == "__main__":
    main()
