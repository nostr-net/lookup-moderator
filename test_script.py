#!/usr/bin/env python3
"""
Test script to verify the lookup_moderator script can initialize correctly.
"""

import asyncio
import sys
import os


def test_parse_env_list():
    """Test the parse_env_list function."""
    print("Testing parse_env_list...")
    
    # Import here to avoid early import error
    from lookup_moderator import parse_env_list
    
    # Test with single value
    os.environ["TEST_VAR"] = "value1"
    result = parse_env_list("TEST_VAR")
    assert result == ["value1"], f"Expected ['value1'], got {result}"
    print("  ✓ Single value parsing works")
    
    # Test with multiple values
    os.environ["TEST_VAR"] = "value1, value2, value3"
    result = parse_env_list("TEST_VAR")
    assert result == ["value1", "value2", "value3"], f"Expected ['value1', 'value2', 'value3'], got {result}"
    print("  ✓ Multiple value parsing works")
    
    # Test with empty value
    os.environ["TEST_VAR"] = ""
    result = parse_env_list("TEST_VAR")
    assert result == [], f"Expected [], got {result}"
    print("  ✓ Empty value parsing works")
    
    # Test with non-existent var
    result = parse_env_list("NON_EXISTENT_VAR")
    assert result == [], f"Expected [], got {result}"
    print("  ✓ Non-existent variable handling works")
    
    # Clean up
    if "TEST_VAR" in os.environ:
        del os.environ["TEST_VAR"]
    
    print()


def test_moderator_initialization():
    """Test that LookupModerator can be initialized."""
    print("Testing LookupModerator initialization...")
    
    from lookup_moderator import LookupModerator
    
    relays = ["wss://relay.damus.io", "wss://relay.nostr.band"]
    moderator = LookupModerator(relays)
    
    assert moderator.relays == relays, "Relays not set correctly"
    assert moderator.client is None, "Client should be None before connection"
    assert len(moderator.lookup_event_ids) == 0, "Event IDs should be empty"
    assert len(moderator.lookup_pubkeys) == 0, "Pubkeys should be empty"
    
    print("  ✓ Basic initialization works")
    
    # Test with filters
    event_ids = ["id1", "id2"]
    pubkeys = ["pk1", "pk2"]
    moderator2 = LookupModerator(relays, event_ids, pubkeys)
    
    assert moderator2.lookup_event_ids == set(event_ids), "Event IDs not set correctly"
    assert moderator2.lookup_pubkeys == set(pubkeys), "Pubkeys not set correctly"
    
    print("  ✓ Initialization with filters works")
    print()


async def test_moderator_methods():
    """Test that moderator methods exist and have correct signatures."""
    print("Testing LookupModerator methods...")
    
    from lookup_moderator import LookupModerator
    
    moderator = LookupModerator(["wss://relay.damus.io"])
    
    # Check that methods exist
    assert hasattr(moderator, "connect"), "connect method missing"
    assert hasattr(moderator, "subscribe_to_moderation_events"), "subscribe_to_moderation_events method missing"
    assert hasattr(moderator, "is_relevant_event"), "is_relevant_event method missing"
    assert hasattr(moderator, "print_moderation_event"), "print_moderation_event method missing"
    assert hasattr(moderator, "monitor"), "monitor method missing"
    assert hasattr(moderator, "run"), "run method missing"
    
    print("  ✓ All required methods exist")
    print()


def main():
    """Run all tests."""
    print("Running lookup_moderator tests...\n")
    
    try:
        test_parse_env_list()
        test_moderator_initialization()
        asyncio.run(test_moderator_methods())
        
        print("✓ All tests passed!")
        return 0
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
