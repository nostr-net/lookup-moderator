# Lookup Moderator

A comprehensive moderation system for Nostr relays running [strfry](https://github.com/hoytech/strfry/), specifically designed for [thelookup](https://github.com/nostr-net/thelookup) content moderation.

This system monitors multiple Nostr relays for [kind 1984 moderation reports](https://nostrbook.dev/kinds/1984), tracks them using Web of Trust (WoT) filtering, and integrates with strfry to automatically reject heavily reported content.

## Features

### Core Features
- **Multi-relay monitoring**: Connect to multiple Nostr relays to gather kind 1984 moderation reports
- **Web of Trust filtering**: Only accept reports from pubkeys in your WoT network (prevents spam/abuse)
- **Persistent storage**: SQLite database tracks all reports with timestamps
- **Configurable thresholds**: Set different thresholds per report type (illegal, spam, etc.)
- **Time-windowed reports**: Only count reports within a configurable time window
- **Strfry integration**: Write policy plugin for automatic content rejection

### Security & Trust
- Reports only counted from pubkeys in your Web of Trust (WoT)
- WoT built by querying follow lists (kind 3 events) with configurable depth
- Unique reporter counting (one report per pubkey)
- Configurable report thresholds per type

## Architecture

The system consists of two components:

1. **Monitoring Daemon** (`lookup_moderator.py`): Continuously monitors Nostr relays for kind 1984 events, validates reporters against WoT, and stores reports in database
2. **Strfry Plugin** (`strfry_moderation_plugin.py`): Integrates with strfry to reject events based on report counts from database

```
┌─────────────────┐
│  Nostr Relays   │
│   (External)    │
└────────┬────────┘
         │ kind 1984 events
         ▼
┌─────────────────┐      ┌──────────────┐
│ Lookup Monitor  │─────▶│   SQLite DB  │
│   (Daemon)      │      │   (Reports)  │
└─────────────────┘      └──────┬───────┘
                                │
                                │ Query reports
                                ▼
                         ┌──────────────┐
                         │    Strfry    │
                         │    Plugin    │
                         └──────┬───────┘
                                │
                                ▼
                         ┌──────────────┐
                         │Your Relay    │
                         │  (strfry)    │
                         └──────────────┘
```

## Installation

### Prerequisites

- Python 3.8 or higher
- [strfry](https://github.com/hoytech/strfry/) relay (for plugin integration)

### Step 1: Clone Repository

```bash
git clone https://github.com/nostr-net/lookup-moderator.git
cd lookup-moderator
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

Or with a virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Configure

Copy the example configuration and edit it:

```bash
cp config.yaml.example config.yaml
nano config.yaml  # or your preferred editor
```

**Important**: You MUST set `wot.source_pubkey` to your pubkey (hex format). This is the pubkey whose Web of Trust network will be used to validate reporters.

### Key Configuration Options

```yaml
# Set your pubkey here (REQUIRED)
wot:
  source_pubkey: "YOUR_PUBKEY_HEX"
  depth: 2  # 1=direct follows, 2=follows-of-follows

# Moderation settings
moderation:
  report_threshold: 3  # Reports needed to reject content
  time_window_days: 30  # Only count recent reports

  # Type-specific thresholds
  type_thresholds:
    illegal: 1    # Immediate action
    malware: 1
    spam: 5       # More tolerance

# Relays to monitor for reports
relays:
  monitor:
    - "wss://relay.damus.io"
    - "wss://relay.nostr.band"
    # Add more relays...

# Event kinds to protect (thelookup-specific)
events:
  monitored_kinds:
    - 30817  # Custom NIPs
    - 31990  # Application directory
```

## Usage

### Running the Monitor Daemon

The daemon should run continuously to collect reports:

```bash
# Run directly
python3 lookup_moderator.py

# Or with custom config
python3 lookup_moderator.py --config /path/to/config.yaml

# Run in background
nohup python3 lookup_moderator.py > monitor.log 2>&1 &
```

**As a systemd service** (recommended for production):

Create `/etc/systemd/system/lookup-moderator.service`:

```ini
[Unit]
Description=Lookup Moderator - Nostr Moderation Monitor
After=network.target

[Service]
Type=simple
User=nostr
WorkingDirectory=/path/to/lookup-moderator
ExecStart=/path/to/venv/bin/python3 lookup_moderator.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl enable lookup-moderator
sudo systemctl start lookup-moderator
sudo systemctl status lookup-moderator
```

### Integrating with Strfry

Edit your strfry configuration file (usually `/etc/strfry/strfry.conf` or `strfry.conf`):

```conf
writePolicy {
    # Path to the moderation plugin
    plugin = "/path/to/lookup-moderator/strfry_moderation_plugin.py"
}
```

Make sure the plugin is executable:

```bash
chmod +x strfry_moderation_plugin.py
```

Restart strfry:

```bash
sudo systemctl restart strfry
```

### Testing the Plugin

Test the plugin manually with sample input:

```bash
echo '{"type":"new","event":{"id":"test123","kind":30817,"pubkey":"...","created_at":1234567890,"content":"test","tags":[],"sig":"..."},"receivedAt":1234567890,"sourceType":"IP4","sourceInfo":"127.0.0.1"}' | python3 strfry_moderation_plugin.py
```

Expected output:
```json
{"id":"test123","action":"accept"}
```

## Understanding Web of Trust (WoT)

This system uses Web of Trust to prevent abuse:

1. You configure a source pubkey (usually your own)
2. The system queries that pubkey's follow list (kind 3 events)
3. With depth=2, it also queries follows-of-follows
4. Only reports from pubkeys in this network are counted

**Example**:
- You follow 200 people (depth 1)
- They follow 10,000 people combined (depth 2)
- Your WoT contains ~10,200 pubkeys
- Only reports from these 10,200 pubkeys count toward thresholds

This prevents random attackers from spamming fake reports.

## Report Types

Per [NIP-56](https://github.com/nostr-protocol/nips/blob/master/56.md), these report types are supported:

- `nudity` - Explicit content
- `malware` - Malicious software
- `profanity` - Hateful/offensive speech
- `illegal` - Potentially illegal content
- `spam` - Unsolicited messages
- `impersonation` - False identity
- `other` - Other issues

You can set different thresholds per type in `config.yaml`.

## Database

The system uses SQLite to store:

- **reports**: All kind 1984 reports with timestamps, types, and reporter pubkeys
- **wot_cache**: Cached Web of Trust pubkeys

Database location is configurable (default: `./moderation_reports.db`).

### Database Cleanup

Old reports are automatically cleaned up based on configuration:

```yaml
database:
  auto_cleanup: true
  cleanup_interval_hours: 24
```

Reports older than `2 × time_window_days` are removed.

## Monitoring & Logs

### Monitor Daemon Logs

```bash
# View real-time logs
tail -f moderator.log

# Check systemd logs
sudo journalctl -u lookup-moderator -f
```

### Plugin Logs

Strfry plugin logs to stderr, which strfry captures. Check your strfry logs:

```bash
sudo journalctl -u strfry -f
```

### Database Statistics

The monitor daemon shows statistics on startup and shutdown:

```
Database stats:
  Total reports: 47
  Unique reported events: 12
  Unique reporters: 23
  WoT cache size: 8,432
```

## Troubleshooting

### "source_pubkey not set" error

You must configure `wot.source_pubkey` in `config.yaml`:

```yaml
wot:
  source_pubkey: "YOUR_PUBKEY_IN_HEX"  # Not npub1..., use hex format
```

To convert npub to hex, use a tool like: https://nostrtool.com/

### WoT is empty or very small

- Make sure your source pubkey has a follow list (kind 3 event) published
- Increase `wot.depth` (but this increases build time)
- Check that relays in config have your follow list

### Events not being rejected

1. Make sure monitor daemon is running and collecting reports
2. Check database has reports: `sqlite3 moderation_reports.db "SELECT COUNT(*) FROM reports;"`
3. Verify event kind is in `events.monitored_kinds`
4. Check report count meets threshold
5. Ensure reports are within time window
6. Verify strfry plugin is configured correctly

### Plugin not working with strfry

- Make sure plugin is executable: `chmod +x strfry_moderation_plugin.py`
- Check Python shebang is correct: `#!/usr/bin/env python3`
- Verify config.yaml path is accessible from strfry's working directory
- Test plugin manually (see "Testing the Plugin" section)

## Development

### Project Structure

```
lookup-moderator/
├── lookup_moderator.py        # Main monitoring daemon
├── strfry_moderation_plugin.py  # Strfry write policy plugin
├── moderation_db.py           # Database abstraction layer
├── wot_fetcher.py             # Web of Trust builder
├── config.yaml                # Configuration file
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

### Running Tests

```bash
# Test database module
python3 -c "from moderation_db import ModerationDB; db = ModerationDB(':memory:'); print('DB OK')"

# Test WoT fetcher (requires config)
python3 -c "import asyncio; from wot_fetcher import WoTFetcher; asyncio.run(WoTFetcher([]).get_follows('test'))"
```

## Security Considerations

### Trust Model

- **WoT-based trust**: Only reports from your trust network count
- **Threshold-based**: Multiple reports required (configurable)
- **Time-bounded**: Old reports expire
- **Transparent**: All reports stored in local database

### Attack Vectors & Mitigations

1. **Report spam from single actor**: Mitigated by unique reporter counting
2. **Sybil attack**: Mitigated by WoT filtering (attacker needs to be in your network)
3. **Coordinated false reports**: Mitigated by threshold requirements
4. **Stale reports**: Mitigated by time windows

### Privacy

- The system queries public Nostr data only
- No private keys are required
- WoT is built from public follow lists
- All data stored locally

## Performance

### Monitor Daemon

- CPU: Low (event-driven)
- Memory: ~50-100 MB
- Network: Depends on relay count and activity
- Disk: Database grows ~1 KB per report

### Strfry Plugin

- Latency: <10ms per event (database query)
- CPU: Minimal (only queries monitored kinds)
- No network requests

## FAQ

**Q: Do I need to run my own relay?**
A: Not for the monitor, but the strfry plugin requires a strfry relay.

**Q: Can I use this without strfry?**
A: Yes! The monitor daemon works standalone. You can query the database manually or build your own integration.

**Q: How often is WoT refreshed?**
A: Configurable via `wot.cache_hours` (default: 24 hours).

**Q: Can I moderate kinds other than 30817/31990?**
A: Yes, just add them to `events.monitored_kinds` in config.

**Q: What if someone in my WoT submits false reports?**
A: You can remove them from your follow list, which will update your WoT on next refresh. Consider using a dedicated moderation pubkey with carefully curated follows.

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

See LICENSE file for details.

## About

### Related Projects

- [thelookup](https://github.com/nostr-net/thelookup) - Nostr ecosystem directory
- [strfry](https://github.com/hoytech/strfry/) - High-performance Nostr relay
- [nostr-sdk](https://github.com/rust-nostr/nostr) - Rust Nostr SDK with Python bindings

### NIP References

- [NIP-01](https://github.com/nostr-protocol/nips/blob/master/01.md) - Basic protocol
- [NIP-56](https://github.com/nostr-protocol/nips/blob/master/56.md) - Reporting (kind 1984)
- [Kind 30817](https://github.com/nostr-protocol/nips/blob/master/01.md#kinds) - Parameterized replaceable events

## Support

- GitHub Issues: https://github.com/nostr-net/lookup-moderator/issues
- Nostr: Contact via the maintainer's pubkey in config

---

**Built with ⚡ for the Nostr ecosystem**
