# lookup-moderator

A Python script that monitors multiple Nostr relays for kind 1984 (moderation/reporting) events pertaining to events used in [thelookup](https://github.com/nostr-net/thelookup).

## What is Kind 1984?

Kind 1984 events are used for reporting and moderation on Nostr. They allow users to report content or other users for various reasons like spam, illegal content, impersonation, etc. See [NIP-56](https://github.com/nostr-protocol/nips/blob/master/56.md) and [Nostr Book - Kind 1984](https://nostrbook.dev/kinds/1984) for more details.

## Features

- Connect to multiple Nostr relays simultaneously
- Monitor for kind 1984 moderation events in real-time
- Filter events by specific event IDs or pubkeys (optional)
- Built using Rust-based Nostr Python bindings (nostr-sdk)

## Installation

1. Clone this repository:
```bash
git clone https://github.com/nostr-net/lookup-moderator.git
cd lookup-moderator
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

You can configure the script using environment variables. Copy the example file:

```bash
cp .env.example .env
```

Then edit `.env` to configure:

- `RELAYS`: Comma-separated list of relay URLs to connect to
- `LOOKUP_EVENT_IDS`: (Optional) Comma-separated list of event IDs to filter for
- `LOOKUP_PUBKEYS`: (Optional) Comma-separated list of pubkeys to filter for

Example `.env`:
```
RELAYS=wss://relay.damus.io,wss://relay.nostr.band,wss://nos.lol
LOOKUP_EVENT_IDS=event_id_1,event_id_2
LOOKUP_PUBKEYS=pubkey_1,pubkey_2
```

If no `.env` file is present, the script will use default relays.

## Usage

Run the script:

```bash
python3 lookup_moderator.py
```

Or make it executable and run directly:

```bash
chmod +x lookup_moderator.py
./lookup_moderator.py
```

The script will:
1. Connect to all configured relays
2. Subscribe to kind 1984 events
3. Monitor and display relevant moderation events in real-time
4. Continue running until interrupted with Ctrl+C

## Output

When a relevant moderation event is detected, the script will display:
- Event ID
- Author (pubkey)
- Timestamp
- Content (the report details)
- Tags (including referenced events and pubkeys)

## Requirements

- Python 3.8+
- nostr-sdk (Rust-based Nostr Python bindings)
- python-dotenv

## About thelookup

[thelookup](https://github.com/nostr-net/thelookup) is a Nostr-based lookup service. This moderator script helps monitor moderation reports related to events and users in that system.

## License

See LICENSE file for details.