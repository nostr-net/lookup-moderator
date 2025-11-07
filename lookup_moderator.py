#!/usr/bin/env python3
"""
Nostr Lookup Moderator

This script monitors multiple Nostr relays for kind 1984 (moderation/reporting) events
that pertain to events used in thelookup (https://github.com/nostr-net/thelookup).

Kind 1984 events are used for reporting content and users on Nostr:
https://nostrbook.dev/kinds/1984
"""

import asyncio
import os
import sys
from typing import List, Set
from dotenv import load_dotenv

try:
    from nostr_sdk import (
        Client,
        ClientBuilder,
        Filter,
        Kind,
        Event,
        EventId,
        PublicKey,
        RelayOptions,
        ClientOptions,
        RelayUrl,
        HandleNotification,
        Timestamp,
    )
except ImportError:
    print("Error: nostr-sdk not installed. Please run: pip install nostr-sdk")
    sys.exit(1)


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
            # The notification object varies, so we need to check its type
            notification_str = str(type(notification))
            
            # Try to access the event if available
            if hasattr(notification, 'event'):
                event = notification.event()
                if self.moderator.is_relevant_event(event):
                    self.moderator.print_moderation_event(event)
        except Exception as e:
            # Silently ignore errors to avoid breaking the handler
            pass
    
    def handle_msg(self, relay_url, msg):
        """Handle incoming relay message."""
        # We'll use handle() instead
        pass


class LookupModerator:
    """Monitor Nostr relays for kind 1984 moderation events."""

    def __init__(self, relays: List[str], lookup_event_ids: List[str] = None, lookup_pubkeys: List[str] = None):
        """
        Initialize the moderator.

        Args:
            relays: List of relay URLs to connect to
            lookup_event_ids: Optional list of event IDs from thelookup to filter for
            lookup_pubkeys: Optional list of pubkeys from thelookup to filter for
        """
        self.relays = relays
        self.lookup_event_ids: Set[str] = set(lookup_event_ids or [])
        self.lookup_pubkeys: Set[str] = set(lookup_pubkeys or [])
        self.client = None
        self.seen_event_ids: Set[str] = set()  # Track seen events to avoid duplicates

    async def connect(self):
        """Connect to all configured relays."""
        print(f"Connecting to {len(self.relays)} relays...")
        
        # Create client with options
        opts = ClientOptions()
        self.client = ClientBuilder().opts(opts).build()
        
        # Add relays
        for relay_url_str in self.relays:
            try:
                relay_url = RelayUrl.parse(relay_url_str)
                await self.client.add_relay(relay_url)
                print(f"  Added relay: {relay_url_str}")
            except Exception as e:
                print(f"  Failed to add relay {relay_url_str}: {e}")
        
        # Connect to relays
        await self.client.connect()
        print("Connected to relays!\n")

    async def subscribe_to_moderation_events(self):
        """Subscribe to kind 1984 moderation events."""
        print("Subscribing to kind 1984 moderation events...")
        
        # Create filter for kind 1984 events
        # Kind 1984 is used for reporting/moderation
        filter_kind = Filter().kind(Kind(1984))
        
        await self.client.subscribe(filter_kind)
        print("Subscription active. Monitoring for moderation events...\n")

    def is_relevant_event(self, event: Event) -> bool:
        """
        Check if a moderation event is relevant to thelookup.

        A moderation event is relevant if:
        - It references an event ID from thelookup
        - It references a pubkey from thelookup
        - Or if no filters are set, all events are considered relevant

        Args:
            event: The moderation event to check

        Returns:
            True if the event is relevant, False otherwise
        """
        # If no filters are set, consider all events relevant
        if not self.lookup_event_ids and not self.lookup_pubkeys:
            return True

        # Check if event references any lookup event IDs
        for tag in event.tags():
            tag_list = tag.as_vec()
            if len(tag_list) >= 2:
                tag_name = tag_list[0]
                tag_value = tag_list[1]
                
                # Check 'e' tags (event references)
                if tag_name == "e" and tag_value in self.lookup_event_ids:
                    return True
                
                # Check 'p' tags (pubkey references)
                if tag_name == "p" and tag_value in self.lookup_pubkeys:
                    return True

        return False

    def print_moderation_event(self, event: Event):
        """
        Print details of a moderation event.

        Args:
            event: The moderation event to print
        """
        event_id = event.id().to_hex()
        
        # Check if we've already seen this event
        if event_id in self.seen_event_ids:
            return
        
        self.seen_event_ids.add(event_id)
        
        print("=" * 80)
        print(f"MODERATION EVENT DETECTED")
        print("=" * 80)
        print(f"Event ID: {event_id}")
        print(f"Author: {event.author().to_hex()}")
        print(f"Created: {event.created_at().as_secs()}")
        print(f"Content: {event.content()}")
        print("\nTags:")
        
        for tag in event.tags():
            tag_list = tag.as_vec()
            print(f"  {tag_list}")
        
        print("=" * 80)
        print()

    async def monitor(self):
        """Monitor relays for moderation events and process them."""
        print("Monitoring started. Press Ctrl+C to stop.\n")
        
        try:
            # Create notification handler
            handler = NotificationHandler(self)
            
            # Start handling notifications in the background
            # Note: handle_notifications is blocking, so we run it as the main loop
            await self.client.handle_notifications(handler)
                
        except KeyboardInterrupt:
            print("\nStopping monitor...")
        except Exception as e:
            print(f"Error in monitor loop: {e}")

    async def run(self):
        """Main run loop."""
        try:
            await self.connect()
            await self.subscribe_to_moderation_events()
            await self.monitor()
        except Exception as e:
            print(f"Error: {e}")
        finally:
            if self.client:
                await self.client.shutdown()
                print("Disconnected from relays.")


def parse_env_list(env_var: str) -> List[str]:
    """Parse a comma-separated environment variable into a list."""
    value = os.getenv(env_var, "")
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


async def main():
    """Main entry point."""
    # Load environment variables
    load_dotenv()

    # Get relay list from environment
    relays = parse_env_list("RELAYS")
    
    if not relays:
        # Default relays if none specified
        relays = [
            "wss://relay.damus.io",
            "wss://relay.nostr.band",
            "wss://nos.lol",
        ]
        print("No relays configured, using defaults:")
        for relay in relays:
            print(f"  - {relay}")
        print()

    # Get optional filters
    lookup_event_ids = parse_env_list("LOOKUP_EVENT_IDS")
    lookup_pubkeys = parse_env_list("LOOKUP_PUBKEYS")

    if lookup_event_ids:
        print(f"Filtering for {len(lookup_event_ids)} event ID(s)")
    if lookup_pubkeys:
        print(f"Filtering for {len(lookup_pubkeys)} pubkey(s)")
    if not lookup_event_ids and not lookup_pubkeys:
        print("No filters set - monitoring all kind 1984 events")
    print()

    # Create and run moderator
    moderator = LookupModerator(relays, lookup_event_ids, lookup_pubkeys)
    await moderator.run()


if __name__ == "__main__":
    asyncio.run(main())
