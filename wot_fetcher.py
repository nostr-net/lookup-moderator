#!/usr/bin/env python3
"""
Web of Trust (WoT) fetcher module.

Builds a Web of Trust network by querying Nostr relays for follow lists (kind 3 events).
"""

import asyncio
import logging
from typing import Set, Optional
from datetime import datetime, timedelta

try:
    from nostr_sdk import (
        Client,
        ClientBuilder,
        Filter,
        Kind,
        PublicKey,
        RelayUrl,
        ClientOptions,
        Timestamp,
    )
except ImportError:
    raise ImportError("nostr-sdk not installed. Please run: pip install nostr-sdk")


logger = logging.getLogger(__name__)


class WoTFetcher:
    """Fetch and build Web of Trust network from Nostr relays."""

    def __init__(self, relays: list[str], cache_hours: int = 24):
        """
        Initialize WoT fetcher.

        Args:
            relays: List of relay URLs to query
            cache_hours: Hours to cache WoT before refreshing
        """
        self.relays = relays
        self.cache_hours = cache_hours
        self.client: Optional[Client] = None
        self._wot_cache: Set[str] = set()
        self._cache_timestamp: Optional[datetime] = None

    async def _init_client(self):
        """Initialize Nostr client if not already initialized."""
        if self.client is None:
            opts = ClientOptions()
            self.client = ClientBuilder().opts(opts).build()

            # Add relays
            for relay_url_str in self.relays:
                try:
                    relay_url = RelayUrl.parse(relay_url_str)
                    await self.client.add_relay(relay_url)
                    logger.debug(f"Added relay for WoT fetch: {relay_url_str}")
                except Exception as e:
                    logger.warning(f"Failed to add relay {relay_url_str}: {e}")

            # Connect to relays
            await self.client.connect()

    async def get_follows(self, pubkey: str) -> Set[str]:
        """
        Get the follow list (kind 3) for a specific pubkey.

        Args:
            pubkey: Hex pubkey to get follows for

        Returns:
            Set of pubkeys that this user follows
        """
        await self._init_client()

        follows = set()

        try:
            # Create filter for kind 3 (contact list / follows)
            pub_key = PublicKey.parse(pubkey)
            filter_follows = Filter().author(pub_key).kind(Kind(3)).limit(1)

            # Query relays with timeout
            logger.debug(f"Fetching follows for {pubkey[:8]}...")
            events = await self.client.get_events_of([filter_follows], timedelta(seconds=10))

            if not events:
                logger.debug(f"No follow list found for {pubkey[:8]}...")
                return follows

            # Get most recent follow list
            # Events are already sorted by timestamp
            latest_event = events[0]

            # Extract followed pubkeys from 'p' tags
            for tag in latest_event.tags():
                tag_list = tag.as_vec()
                if len(tag_list) >= 2 and tag_list[0] == "p":
                    followed_pubkey = tag_list[1]
                    follows.add(followed_pubkey)

            logger.debug(
                f"Found {len(follows)} follows for {pubkey[:8]}..."
            )

        except Exception as e:
            logger.error(f"Error fetching follows for {pubkey}: {e}")

        return follows

    async def build_wot(
        self, source_pubkey: str, depth: int = 2, max_pubkeys: int = 10000
    ) -> Set[str]:
        """
        Build Web of Trust network starting from a source pubkey.

        Args:
            source_pubkey: Starting pubkey (your pubkey)
            depth: How many hops to follow (1 = direct follows, 2 = follows of follows)
            max_pubkeys: Maximum number of pubkeys to include (safety limit)

        Returns:
            Set of all pubkeys in the WoT network
        """
        logger.info(f"Building WoT for {source_pubkey[:8]}... with depth={depth}")

        wot = set()
        wot.add(source_pubkey)  # Include source in WoT

        current_level = {source_pubkey}

        for level in range(depth):
            logger.info(
                f"WoT level {level + 1}/{depth}: Processing {len(current_level)} pubkeys"
            )

            next_level = set()

            # Fetch follows for all pubkeys in current level
            # Process in batches to avoid overwhelming relays
            batch_size = 10
            current_list = list(current_level)

            for i in range(0, len(current_list), batch_size):
                batch = current_list[i : i + batch_size]

                # Fetch follows concurrently for batch
                tasks = [self.get_follows(pk) for pk in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for follows in results:
                    if isinstance(follows, set):
                        next_level.update(follows)

                # Safety check
                if len(wot) + len(next_level) > max_pubkeys:
                    logger.warning(
                        f"WoT size limit reached ({max_pubkeys}), stopping at level {level + 1}"
                    )
                    break

            # Add next level to WoT (but don't process them again if we're at max depth)
            new_pubkeys = next_level - wot
            wot.update(new_pubkeys)

            logger.info(f"Added {len(new_pubkeys)} new pubkeys to WoT")

            # Safety check
            if len(wot) >= max_pubkeys:
                logger.warning(f"WoT size limit reached: {len(wot)} pubkeys")
                break

            # Prepare for next level
            current_level = new_pubkeys

            # If no new pubkeys, we're done
            if not current_level:
                logger.info("No new pubkeys found, WoT complete")
                break

        logger.info(f"WoT built successfully: {len(wot)} total pubkeys")
        return wot

    async def get_wot_cached(
        self, source_pubkey: str, depth: int = 2, force_refresh: bool = False
    ) -> Set[str]:
        """
        Get WoT with caching.

        Args:
            source_pubkey: Starting pubkey
            depth: WoT depth
            force_refresh: Force refresh even if cache is valid

        Returns:
            Set of pubkeys in WoT
        """
        # Check if cache is valid
        if not force_refresh and self._wot_cache and self._cache_timestamp:
            cache_age = datetime.now() - self._cache_timestamp
            if cache_age < timedelta(hours=self.cache_hours):
                logger.info(
                    f"Using cached WoT ({len(self._wot_cache)} pubkeys, "
                    f"age: {cache_age.total_seconds() / 3600:.1f}h)"
                )
                return self._wot_cache

        # Build fresh WoT
        logger.info("Building fresh WoT...")
        wot = await self.build_wot(source_pubkey, depth)

        # Update cache
        self._wot_cache = wot
        self._cache_timestamp = datetime.now()

        return wot

    async def shutdown(self):
        """Shutdown the client."""
        if self.client:
            await self.client.shutdown()
            logger.debug("WoT fetcher client shutdown")
