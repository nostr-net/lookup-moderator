#!/usr/bin/env python3
"""
Test script to verify dependencies are installed correctly.
"""

import sys

def test_imports():
    """Test that required packages can be imported."""
    print("Testing imports...")
    
    try:
        import dotenv
        print("  ✓ python-dotenv imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import python-dotenv: {e}")
        return False
    
    try:
        import nostr_sdk
        print("  ✓ nostr-sdk imported successfully")
        
        # Test some basic imports
        from nostr_sdk import Client, Filter, Kind
        print("  ✓ Core nostr-sdk classes available")
        
    except ImportError as e:
        print(f"  ✗ Failed to import nostr-sdk: {e}")
        return False
    
    print("\n✓ All dependencies installed correctly!")
    return True

if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
