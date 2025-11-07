#!/usr/bin/env python3
"""
Nostr Lookup Moderator

Monitors wot.nostr.net for kind 1984 (moderation/reporting) events
pertaining to thelookup content. When enough reports are received,
deletes the reported content from strfry relay.

wot.nostr.net already filters events by Web of Trust, so we don't
need to build WoT ourselves.
"""

import asyncio
import logging
import sys
import subprocess
from typing import Set, Optional
import yaml
import signal

try:
    from nostr_sdk import (
        Client,
        ClientBuilder,
        Filter,
        Kind,
        Event,
        Keys,
        EventBuilder,
        RelayUrl,
        ClientOptions,
        HandleNotification,
        Timestamp,
    )
except ImportError:
    print("Error: nostr-sdk not installed. Please run: pip install nostr-sdk")
    sys.exit(1)

from moderation_db import ModerationDB


# Configure logging
def setup_logging(config: dict):
    """Setup logging based on configuration."""
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO"))
    format_str = log_config.get(
        "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    handlers = [logging.StreamHandler()]

    log_file = log_config.get("file")
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(level=level, format=format_str, handlers=handlers)


logger = logging.getLogger(__name__)


class NotificationHandler(HandleNotification):
    """Handle notifications from Nostr relays."""

    def __init__(self, moderator):
        """Initialize with reference to moderator."""
        super().__init__()
        self.moderator = moderator

    def handle(self, relay_url, notification):
        """Handle incoming notification."""
        try:
            if hasattr(notification, "event"):
                event = notification.event()
                if event.kind().as_u16() == 1984:
                    asyncio.create_task(
                        self.moderator.process_moderation_event(event)
                    )
        except Exception as e:
            logger.debug(f"Error in notification handler: {e}")

    def handle_msg(self, relay_url, msg):
        """Handle incoming relay message."""
        pass


class LookupModerator:
    """Monitor wot.nostr.net for kind 1984 moderation events and delete reported content."""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize the moderator.

        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        self.config = self._load_config(config_path)
        setup_logging(self.config)

        # Extract config values
        wot_config = self.config.get("wot_relay", {})
        self.wot_relay_url = wot_config.get("url", "wss://wot.nostr.net")
        self.pubkey = wot_config.get("pubkey", "")
        self.private_key = wot_config.get("private_key", "")

        mod_config = self.config.get("moderation", {})
        self.report_threshold = mod_config.get("report_threshold", 3)
        self.time_window_days = mod_config.get("time_window_days", 30)
        self.type_thresholds = mod_config.get("type_thresholds", {})
        self.auto_delete = mod_config.get("auto_delete", True)
        self.dry_run = mod_config.get("dry_run", False)

        strfry_config = self.config.get("strfry", {})
        self.strfry_executable = strfry_config.get("executable", "/usr/local/bin/strfry")
        self.strfry_data_dir = strfry_config.get("data_dir", "/var/lib/strfry")
        self.publish_deletes = strfry_config.get("publish_deletes", True)
        self.publish_relays = strfry_config.get("publish_relays", [])

        event_config = self.config.get("events", {})
        self.monitored_kinds = set(event_config.get("monitored_kinds", [30817, 31990]))

        db_config = self.config.get("database", {})
        db_path = db_config.get("path", "./moderation_reports.db")
        self.auto_cleanup = db_config.get("auto_cleanup", True)
        self.cleanup_interval_hours = db_config.get("cleanup_interval_hours", 24)

        # Initialize components
        self.db = ModerationDB(db_path)
        self.client: Optional[Client] = None
        self.keys: Optional[Keys] = None
        self.seen_event_ids: Set[str] = set()
        self.running = False

        # Initialize keys if private key provided
        if self.private_key and self.publish_deletes:
            try:
                self.keys = Keys.parse(self.private_key)
                logger.info(f"Loaded keys for pubkey: {self.keys.public_key().to_hex()[:16]}...")
            except Exception as e:
                logger.warning(f"Failed to parse private key: {e}")
                logger.warning("Delete events will not be published")

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file."""
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Config file not found: {config_path}")
            logger.error("Please copy config.yaml.example to config.yaml and configure it")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            sys.exit(1)

    async def connect(self):
        """Connect to wot.nostr.net relay."""
        logger.info(f"Connecting to {self.wot_relay_url}...")

        # Create client
        opts = ClientOptions()
        self.client = ClientBuilder().opts(opts).build()

        # Add relay
        try:
            relay_url = RelayUrl.parse(self.wot_relay_url)
            await self.client.add_relay(relay_url)
            logger.info(f"  Added relay: {self.wot_relay_url}")
        except Exception as e:
            logger.error(f"  Failed to add relay {self.wot_relay_url}: {e}")
            raise

        # Connect to relay
        await self.client.connect()
        logger.info("Connected to relay!")

    async def subscribe_to_moderation_events(self):
        """Subscribe to kind 1984 moderation events."""
        logger.info("Subscribing to kind 1984 moderation events...")

        # Create filter for kind 1984 events
        filter_kind = Filter().kind(Kind(1984))

        await self.client.subscribe([filter_kind])
        logger.info("Subscription active. Monitoring for moderation events...")

    async def delete_event_from_strfry(self, event_id: str) -> bool:
        """
        Delete an event from strfry database using CLI.

        Args:
            event_id: Event ID to delete

        Returns:
            True if successful, False otherwise
        """
        try:
            # Run strfry delete command
            # strfry delete --id <event_id>
            cmd = [
                self.strfry_executable,
                "delete",
                "--dir", self.strfry_data_dir,
                "--id", event_id
            ]

            # Dry run mode - just log what would be executed
            if self.dry_run:
                logger.info(f"[DRY RUN] Would execute: {' '.join(cmd)}")
                logger.info(f"[DRY RUN] Would delete event {event_id[:16]}... from strfry")
                return True  # Simulate success

            logger.info(f"Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info(f"Successfully deleted event {event_id[:16]}... from strfry")
                return True
            else:
                logger.error(f"Failed to delete event: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout deleting event {event_id[:16]}...")
            return False
        except Exception as e:
            logger.error(f"Error deleting event from strfry: {e}")
            return False

    async def publish_delete_event(self, event_id: str, reason: str = "Moderation"):
        """
        Publish a kind 5 delete event.

        Args:
            event_id: Event ID to delete
            reason: Reason for deletion
        """
        if not self.keys or not self.publish_deletes:
            return

        # Dry run mode - just log what would be published
        if self.dry_run:
            logger.info(f"[DRY RUN] Would publish kind 5 delete event for {event_id[:16]}...")
            logger.info(f"[DRY RUN] Would publish to relays: {self.publish_relays}")
            logger.info(f"[DRY RUN] Reason: {reason}")
            return

        try:
            # Create kind 5 delete event
            # According to NIP-09, kind 5 events have "e" tags for events to delete
            event_builder = EventBuilder.delete([event_id], reason)

            event = await event_builder.to_event(self.keys)

            # Publish to configured relays
            for relay_url_str in self.publish_relays:
                try:
                    relay_url = RelayUrl.parse(relay_url_str)
                    # Add relay if not already added
                    await self.client.add_relay(relay_url)
                except Exception as e:
                    logger.warning(f"Failed to add relay {relay_url_str}: {e}")

            # Send event
            output = await self.client.send_event(event)
            logger.info(f"Published delete event for {event_id[:16]}... to {len(self.publish_relays)} relays")

        except Exception as e:
            logger.error(f"Error publishing delete event: {e}")

    async def process_moderation_event(self, event: Event):
        """
        Process a kind 1984 moderation event.

        Args:
            event: The moderation event to process
        """
        event_id = event.id().to_hex()

        # Check if already seen
        if event_id in self.seen_event_ids:
            return
        self.seen_event_ids.add(event_id)

        reporter_pubkey = event.author().to_hex()

        # Extract report details from tags
        reported_event_id = None
        report_type = None

        for tag in event.tags():
            tag_list = tag.as_vec()
            if len(tag_list) >= 2:
                tag_name = tag_list[0]

                # Extract event being reported
                if tag_name == "e":
                    reported_event_id = tag_list[1]
                    # Report type may be third parameter (per NIP-56)
                    if len(tag_list) >= 4:
                        report_type = tag_list[3]

        # If no event ID found, this report is not relevant
        if not reported_event_id:
            logger.debug(f"Report {event_id[:8]}... has no event ID, skipping")
            return

        # Get report content
        report_content = event.content()
        timestamp = event.created_at().as_secs()

        # Store in database
        success = self.db.add_report(
            report_event_id=event_id,
            reported_event_id=reported_event_id,
            reported_event_kind=None,  # We don't know the kind yet
            reporter_pubkey=reporter_pubkey,
            report_type=report_type,
            report_content=report_content,
            timestamp=timestamp,
        )

        if success:
            # Log the report
            logger.info("=" * 80)
            logger.info(f"NEW MODERATION REPORT")
            logger.info(f"Report ID: {event_id[:16]}...")
            logger.info(f"Reporter: {reporter_pubkey[:16]}...")
            logger.info(f"Reported Event: {reported_event_id[:16]}...")
            if report_type:
                logger.info(f"Report Type: {report_type}")
            logger.info(f"Content: {report_content[:100]}")

            # Get current report count
            count = self.db.get_report_count(
                reported_event_id,
                wot_pubkeys=None,  # wot.nostr.net already filters
                time_window_days=self.time_window_days,
            )

            # Check if we should delete this event
            should_delete = False
            threshold = self.report_threshold

            # Check type-specific threshold
            if report_type and report_type in self.type_thresholds:
                threshold = self.type_thresholds[report_type]

            if count >= threshold:
                should_delete = True

            logger.info(f"Total reports: {count} (threshold: {threshold})")

            if should_delete:
                logger.warning(f"THRESHOLD REACHED - Event should be deleted!")

                if self.dry_run:
                    logger.warning(f"[DRY RUN MODE] Simulating deletion process...")

                if self.auto_delete:
                    logger.info(f"Auto-delete enabled, deleting event...")

                    # Delete from strfry
                    deleted = await self.delete_event_from_strfry(reported_event_id)

                    if deleted:
                        # Publish delete event if configured
                        if self.publish_deletes:
                            await self.publish_delete_event(
                                reported_event_id,
                                f"Reported {count} times: {report_type or 'various reasons'}"
                            )
                        logger.info(f"Event {reported_event_id[:16]}... deleted successfully")
                    else:
                        logger.error(f"Failed to delete event {reported_event_id[:16]}...")
                else:
                    logger.info("Auto-delete disabled. Manual action required.")

            logger.info("=" * 80)

    async def cleanup_task(self):
        """Periodic cleanup of old reports."""
        while self.running:
            await asyncio.sleep(self.cleanup_interval_hours * 3600)

            if self.auto_cleanup:
                # Cleanup reports older than 2x time window
                cleanup_days = self.time_window_days * 2
                logger.info(f"Running cleanup of reports older than {cleanup_days} days")
                self.db.cleanup_old_reports(cleanup_days)

    async def monitor(self):
        """Monitor relay for moderation events."""
        logger.info("Monitoring started. Press Ctrl+C to stop.\n")

        self.running = True

        try:
            # Start background tasks
            cleanup_task = asyncio.create_task(self.cleanup_task())

            # Create notification handler
            handler = NotificationHandler(self)

            # Main monitoring loop
            await self.client.handle_notifications(handler)

        except asyncio.CancelledError:
            logger.info("Monitor task cancelled")
        finally:
            self.running = False

    async def run(self):
        """Main run loop."""
        # Print startup banner
        logger.info("=" * 80)
        logger.info("Lookup Moderator - Nostr Kind 1984 Event Monitor")
        logger.info("=" * 80)

        # Show stats
        stats = self.db.get_stats()
        logger.info(f"Database stats:")
        logger.info(f"  Total reports: {stats['total_reports']}")
        logger.info(f"  Unique reported events: {stats['unique_reported_events']}")
        logger.info(f"  Unique reporters: {stats['unique_reporters']}")
        logger.info("")

        # Show config
        logger.info(f"Configuration:")
        logger.info(f"  WoT Relay: {self.wot_relay_url}")
        logger.info(f"  Report threshold: {self.report_threshold}")
        logger.info(f"  Time window: {self.time_window_days} days")
        logger.info(f"  Auto-delete: {self.auto_delete}")
        logger.info(f"  Dry run: {self.dry_run}")
        if self.dry_run:
            logger.warning("  DRY RUN MODE ENABLED - No actions will be executed!")
        logger.info(f"  Monitored kinds: {sorted(self.monitored_kinds)}")
        logger.info("")

        try:
            # Connect to relay
            await self.connect()

            # Subscribe to moderation events
            await self.subscribe_to_moderation_events()

            # Start monitoring
            await self.monitor()

        except KeyboardInterrupt:
            logger.info("\nShutdown requested...")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
        finally:
            # Cleanup
            if self.client:
                await self.client.shutdown()
            logger.info("Disconnected from relay.")

            # Show final stats
            stats = self.db.get_stats()
            logger.info("\nFinal statistics:")
            logger.info(f"  Total reports: {stats['total_reports']}")
            logger.info(f"  Unique reported events: {stats['unique_reported_events']}")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Monitor wot.nostr.net for moderation reports and delete content from strfry"
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    args = parser.parse_args()

    # Create and run moderator
    moderator = LookupModerator(args.config)

    # Handle shutdown gracefully
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)

    await moderator.run()


if __name__ == "__main__":
    asyncio.run(main())
