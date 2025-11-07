#!/usr/bin/env python3
"""
Nostr Lookup Moderator

This script monitors multiple Nostr relays for kind 1984 (moderation/reporting) events
that pertain to events used in thelookup (https://github.com/nostr-net/thelookup).

It uses Web of Trust (WoT) to only accept reports from trusted pubkeys and stores
them in a database for use by the strfry plugin.

Kind 1984 events are used for reporting content and users on Nostr:
https://nostrbook.dev/kinds/1984
"""

import asyncio
import logging
import sys
from typing import List, Set, Optional
from pathlib import Path
import yaml
import signal

try:
    from nostr_sdk import (
        Client,
        ClientBuilder,
        Filter,
        Kind,
        Event,
        RelayUrl,
        ClientOptions,
        HandleNotification,
    )
except ImportError:
    print("Error: nostr-sdk not installed. Please run: pip install nostr-sdk")
    sys.exit(1)

from moderation_db import ModerationDB
from wot_fetcher import WoTFetcher


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
            # Try to get event from notification
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
    """Monitor Nostr relays for kind 1984 moderation events."""

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
        wot_config = self.config.get("wot", {})
        self.source_pubkey = wot_config.get("source_pubkey", "")
        self.wot_depth = wot_config.get("depth", 2)
        self.wot_cache_hours = wot_config.get("cache_hours", 24)

        mod_config = self.config.get("moderation", {})
        self.report_threshold = mod_config.get("report_threshold", 3)
        self.time_window_days = mod_config.get("time_window_days", 30)
        self.type_thresholds = mod_config.get("type_thresholds", {})

        relay_config = self.config.get("relays", {})
        self.monitor_relays = relay_config.get("monitor", [])

        event_config = self.config.get("events", {})
        self.monitored_kinds = set(event_config.get("monitored_kinds", [30817, 31990]))

        db_config = self.config.get("database", {})
        db_path = db_config.get("path", "./moderation_reports.db")
        self.auto_cleanup = db_config.get("auto_cleanup", True)
        self.cleanup_interval_hours = db_config.get("cleanup_interval_hours", 24)

        # Validate config
        if not self.source_pubkey:
            logger.error("ERROR: source_pubkey not set in config.yaml!")
            logger.error("Please set wot.source_pubkey to your pubkey (hex format)")
            sys.exit(1)

        if not self.monitor_relays:
            logger.warning("No monitor relays configured, using defaults")
            self.monitor_relays = [
                "wss://relay.damus.io",
                "wss://relay.nostr.band",
                "wss://nos.lol",
            ]

        # Initialize components
        self.db = ModerationDB(db_path)
        self.wot_fetcher = WoTFetcher(self.monitor_relays, self.wot_cache_hours)
        self.wot_pubkeys: Set[str] = set()

        self.client: Optional[Client] = None
        self.seen_event_ids: Set[str] = set()
        self.running = False

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

    async def init_wot(self):
        """Initialize Web of Trust network."""
        logger.info("Initializing Web of Trust...")
        logger.info(f"Source pubkey: {self.source_pubkey[:16]}...")
        logger.info(f"WoT depth: {self.wot_depth}")

        # Try to load from database cache first
        cached_wot = self.db.get_wot_cache()
        cache_age = self.db.get_wot_cache_age()

        if cached_wot and cache_age:
            from datetime import datetime, timedelta

            age_hours = (datetime.now() - cache_age).total_seconds() / 3600
            if age_hours < self.wot_cache_hours:
                logger.info(
                    f"Loaded WoT from database cache: {len(cached_wot)} pubkeys "
                    f"(age: {age_hours:.1f}h)"
                )
                self.wot_pubkeys = cached_wot
                return

        # Build fresh WoT
        self.wot_pubkeys = await self.wot_fetcher.get_wot_cached(
            self.source_pubkey, self.wot_depth, force_refresh=True
        )

        # Cache in database
        self.db.update_wot_cache(self.wot_pubkeys)

        logger.info(f"WoT initialized with {len(self.wot_pubkeys)} trusted pubkeys")

    async def connect(self):
        """Connect to all configured relays."""
        logger.info(f"Connecting to {len(self.monitor_relays)} relays...")

        # Create client with options
        opts = ClientOptions()
        self.client = ClientBuilder().opts(opts).build()

        # Add relays
        for relay_url_str in self.monitor_relays:
            try:
                relay_url = RelayUrl.parse(relay_url_str)
                await self.client.add_relay(relay_url)
                logger.info(f"  Added relay: {relay_url_str}")
            except Exception as e:
                logger.warning(f"  Failed to add relay {relay_url_str}: {e}")

        # Connect to relays
        await self.client.connect()
        logger.info("Connected to relays!")

    async def subscribe_to_moderation_events(self):
        """Subscribe to kind 1984 moderation events."""
        logger.info("Subscribing to kind 1984 moderation events...")

        # Create filter for kind 1984 events
        filter_kind = Filter().kind(Kind(1984))

        await self.client.subscribe([filter_kind])
        logger.info("Subscription active. Monitoring for moderation events...")

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

        # Check if reporter is in WoT
        if reporter_pubkey not in self.wot_pubkeys:
            logger.debug(
                f"Ignoring report from non-WoT pubkey: {reporter_pubkey[:8]}..."
            )
            return

        # Extract report details from tags
        reported_event_id = None
        reported_event_kind = None
        report_type = None

        for tag in event.tags():
            tag_list = tag.as_vec()
            if len(tag_list) >= 2:
                tag_name = tag_list[0]

                # Extract event being reported
                if tag_name == "e":
                    reported_event_id = tag_list[1]
                    # Report type may be third parameter
                    if len(tag_list) >= 4:
                        report_type = tag_list[3]

        # If no event ID found, this report is not relevant
        if not reported_event_id:
            logger.debug(f"Report {event_id[:8]}... has no event ID, skipping")
            return

        # Get report content
        report_content = event.content()
        timestamp = event.created_at().as_secs()

        # Try to determine the kind of reported event by querying
        # For now, we'll accept all reports and filter in the plugin
        # In production, you might want to query the event first

        # Store in database
        success = self.db.add_report(
            report_event_id=event_id,
            reported_event_id=reported_event_id,
            reported_event_kind=reported_event_kind,
            reporter_pubkey=reporter_pubkey,
            report_type=report_type,
            report_content=report_content,
            timestamp=timestamp,
        )

        if success:
            # Log the report
            logger.info("=" * 80)
            logger.info(f"NEW MODERATION REPORT (from WoT)")
            logger.info(f"Report ID: {event_id[:16]}...")
            logger.info(f"Reporter: {reporter_pubkey[:16]}... (trusted)")
            logger.info(f"Reported Event: {reported_event_id[:16]}...")
            if report_type:
                logger.info(f"Report Type: {report_type}")
            logger.info(f"Content: {report_content[:100]}")

            # Get current report count
            count = self.db.get_report_count(
                reported_event_id,
                wot_pubkeys=self.wot_pubkeys,
                time_window_days=self.time_window_days,
            )
            logger.info(f"Total reports for this event: {count}")
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

    async def wot_refresh_task(self):
        """Periodic refresh of WoT."""
        while self.running:
            await asyncio.sleep(self.wot_cache_hours * 3600)

            logger.info("Refreshing Web of Trust...")
            try:
                self.wot_pubkeys = await self.wot_fetcher.get_wot_cached(
                    self.source_pubkey, self.wot_depth, force_refresh=True
                )
                self.db.update_wot_cache(self.wot_pubkeys)
                logger.info(f"WoT refreshed: {len(self.wot_pubkeys)} pubkeys")
            except Exception as e:
                logger.error(f"Error refreshing WoT: {e}")

    async def monitor(self):
        """Monitor relays for moderation events."""
        logger.info("Monitoring started. Press Ctrl+C to stop.\n")

        self.running = True

        try:
            # Start background tasks
            cleanup_task = asyncio.create_task(self.cleanup_task())
            wot_refresh_task = asyncio.create_task(self.wot_refresh_task())

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
        logger.info(f"  WoT cache size: {stats['wot_cache_size']}")
        logger.info("")

        try:
            # Initialize WoT
            await self.init_wot()

            # Connect to relays
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
            await self.wot_fetcher.shutdown()
            logger.info("Disconnected from relays.")

            # Show final stats
            stats = self.db.get_stats()
            logger.info("\nFinal statistics:")
            logger.info(f"  Total reports: {stats['total_reports']}")
            logger.info(f"  Unique reported events: {stats['unique_reported_events']}")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Monitor Nostr relays for moderation reports"
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
