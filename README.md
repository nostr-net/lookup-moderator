# Lookup Moderator

A Python-based moderation system for Nostr relays running [strfry](https://github.com/hoytech/strfry/), specifically designed for [thelookup](https://github.com/nostr-net/thelookup) content moderation.

This system monitors **wot.nostr.net** (a Web of Trust filtered relay) for [kind 1984 moderation reports](https://nostrbook.dev/kinds/1984), tracks them in a database, and automatically deletes heavily reported content from your strfry relay.

## How It Works

```
wot.nostr.net → Monitor Daemon → SQLite DB → strfry delete
     ↓              ↓
(kind 1984)   Track reports              Delete reported events
(WoT filtered)  Count threshold           (when threshold met)
```

1. **Monitor**: Connects to wot.nostr.net and listens for kind 1984 (reporting) events
2. **Track**: Stores reports in SQLite database with timestamps and report types
3. **Delete**: When report threshold is met, uses `strfry delete` CLI to remove content
4. **Publish** (optional): Publishes kind 5 delete events to relays

**Why wot.nostr.net?** It already filters events by Web of Trust, so you only see reports from trusted users in your network. No need to build WoT yourself!

## Features

- **Simple**: Single daemon, no plugins needed
- **WoT-filtered**: Only processes reports from wot.nostr.net (pre-filtered by your trust network)
- **Configurable thresholds**: Different limits per report type (illegal=1, spam=5, etc.)
- **Time-windowed**: Only count recent reports (default 30 days)
- **Auto-delete**: Automatically removes content using strfry CLI
- **Delete events**: Optionally publishes kind 5 delete events
- **SQLite database**: Persistent report tracking
- **Systemd ready**: Easy deployment as a service

## Installation

### Prerequisites

- Python 3.8+
- [strfry](https://github.com/hoytech/strfry/) relay (only needed for actual deletion, not for dry run)

### Quick Start

**Using pip:**

```bash
# Clone repository
git clone https://github.com/nostr-net/lookup-moderator.git
cd lookup-moderator

# Install dependencies
pip install -r requirements.txt

# Configure
cp config.yaml.example config.yaml
nano config.yaml  # Edit configuration

# Run
python3 lookup_moderator.py
```

**Using uv (recommended for faster installs):**

```bash
# Clone repository
git clone https://github.com/nostr-net/lookup-moderator.git
cd lookup-moderator

# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv pip install -r requirements.txt

# Or use uv to run directly
uv run lookup_moderator.py

# Configure
cp config.yaml.example config.yaml
nano config.yaml  # Edit configuration
```

## Dry Run Mode - Test Before You Delete!

**Want to see what the tool finds without actually deleting anything?** Use dry run mode!

Dry run mode lets you:
- Monitor what reports are coming in from wot.nostr.net
- See which events would be deleted based on your thresholds
- Test your configuration safely without making any changes
- Understand what content is being reported in your network

### Quick Dry Run Setup

1. **Copy the example config:**
   ```bash
   cp config.yaml.example config.yaml
   ```

2. **Enable dry run mode in config.yaml:**
   ```yaml
   moderation:
     dry_run: true      # Enable dry run mode
     auto_delete: true  # Can be true or false, no deletion happens in dry run
   ```

3. **Run the tool:**
   ```bash
   # Using Python
   python3 lookup_moderator.py

   # Or using uv
   uv run lookup_moderator.py
   ```

### Example Dry Run Configurations

**Example 1: Monitor everything, see what would be deleted**
```yaml
moderation:
  report_threshold: 3
  time_window_days: 30
  auto_delete: true
  dry_run: true  # Nothing will actually be deleted

strfry:
  executable: "/usr/local/bin/strfry"  # Path doesn't need to exist in dry run
  data_dir: "/var/lib/strfry"          # Path doesn't need to exist in dry run
  publish_deletes: true  # Would publish, but won't in dry run mode
```

**Example 2: Test strict illegal content moderation**
```yaml
moderation:
  report_threshold: 3
  time_window_days: 7  # Shorter window for testing

  type_thresholds:
    illegal: 1   # See what gets flagged immediately
    malware: 1
    spam: 5

  auto_delete: true
  dry_run: true  # Safe to test strict settings
```

**Example 3: Monitor without auto-delete intent**
```yaml
moderation:
  report_threshold: 3
  auto_delete: false  # Just monitor, don't even simulate deletion
  dry_run: true       # Extra safety
```

### What You'll See in Dry Run Mode

When a report threshold is reached, you'll see output like:

```
================================================================================
NEW MODERATION REPORT
Report ID: abc123def456...
Reporter: 789pubkey012...
Reported Event: xyz789event...
Report Type: spam
Content: This is spam content reported by user
Total reports: 3 (threshold: 3)
THRESHOLD REACHED - Event should be deleted!
[DRY RUN MODE] Simulating deletion process...
Auto-delete enabled, deleting event...
[DRY RUN] Would execute: /usr/local/bin/strfry delete --dir /var/lib/strfry --id xyz789event...
[DRY RUN] Would delete event xyz789event... from strfry
[DRY RUN] Would publish kind 5 delete event for xyz789event...
[DRY RUN] Would publish to relays: ['wss://wot.nostr.net']
[DRY RUN] Reason: Reported 3 times: spam
Event xyz789event... deleted successfully
================================================================================
```

Notice all the `[DRY RUN]` prefixes - no actual commands are executed!

### Moving from Dry Run to Production

Once you're satisfied with what you see:

1. **Update config.yaml:**
   ```yaml
   moderation:
     dry_run: false  # Disable dry run mode
   ```

2. **Verify strfry paths are correct:**
   ```bash
   which strfry
   ls -la /var/lib/strfry/strfry.conf
   ```

3. **Test strfry delete manually:**
   ```bash
   /usr/local/bin/strfry delete --help
   ```

4. **Restart the moderator:**
   ```bash
   python3 lookup_moderator.py
   # Or with systemd
   sudo systemctl restart lookup-moderator
   ```

## Configuration

Edit `config.yaml`:

```yaml
# WoT Relay (wot.nostr.net already filters by your WoT)
wot_relay:
  url: "wss://wot.nostr.net"

  # Optional: For publishing delete events
  pubkey: "your_pubkey_hex"
  private_key: "nsec_or_hex"  # Keep secure!

# Moderation settings
moderation:
  report_threshold: 3  # Default reports needed
  time_window_days: 30  # Only count recent reports
  auto_delete: true     # Auto-delete when threshold met

  # Type-specific thresholds
  type_thresholds:
    illegal: 1          # Immediate removal
    malware: 1
    spam: 5             # More tolerance
    impersonation: 2

# Strfry configuration
strfry:
  executable: "/usr/local/bin/strfry"
  data_dir: "/var/lib/strfry"  # Directory with strfry.conf

  # Publish kind 5 delete events
  publish_deletes: true
  publish_relays:
    - "wss://wot.nostr.net"

# Event kinds to monitor (thelookup-specific)
events:
  monitored_kinds:
    - 30817  # Custom NIPs
    - 31990  # Application directory
```

### Important Notes

- **wot.nostr.net**: The relay already filters by your Web of Trust, so you only see reports from trusted users
- **private_key**: Only needed if you want to publish kind 5 delete events (optional)
- **strfry paths**: Adjust `executable` and `data_dir` to match your installation

## Usage

### Run Directly

**Using Python:**
```bash
python3 lookup_moderator.py

# With custom config
python3 lookup_moderator.py --config /path/to/config.yaml
```

**Using uv:**
```bash
uv run lookup_moderator.py

# With custom config
uv run lookup_moderator.py --config /path/to/config.yaml

# Or create a virtual environment and run
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
python lookup_moderator.py
```

### Run as Systemd Service (Recommended)

**Using Python:**

Create `/etc/systemd/system/lookup-moderator.service`:

```ini
[Unit]
Description=Lookup Moderator - Nostr Moderation Monitor
After=network.target

[Service]
Type=simple
User=strfry
WorkingDirectory=/path/to/lookup-moderator
ExecStart=/usr/bin/python3 /path/to/lookup-moderator/lookup_moderator.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Using uv:**

Create `/etc/systemd/system/lookup-moderator.service`:

```ini
[Unit]
Description=Lookup Moderator - Nostr Moderation Monitor
After=network.target

[Service]
Type=simple
User=strfry
WorkingDirectory=/path/to/lookup-moderator
ExecStart=/home/user/.cargo/bin/uv run /path/to/lookup-moderator/lookup_moderator.py
Restart=always
RestartSec=10
Environment="PATH=/home/user/.cargo/bin:/usr/local/bin:/usr/bin"

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable lookup-moderator
sudo systemctl start lookup-moderator
sudo systemctl status lookup-moderator
```

### Monitor Logs

```bash
# Real-time logs
tail -f moderator.log

# Systemd logs
sudo journalctl -u lookup-moderator -f
```

## How Deletion Works

When a report threshold is reached:

1. **Strfry CLI Delete**: Executes `strfry delete --dir /path --id <event_id>`
   - Removes event from local strfry database
   - Immediate local deletion

2. **Publish Delete Event** (optional): Creates and publishes kind 5 event
   - Notifies other relays to delete the content
   - Per [NIP-09](https://github.com/nostr-protocol/nips/blob/master/09.md)
   - Requires private key in config

## Report Types (NIP-56)

Per [NIP-56](https://github.com/nostr-protocol/nips/blob/master/56.md):

- `nudity` - Explicit content
- `malware` - Malicious software
- `profanity` - Hateful/offensive speech
- `illegal` - Potentially illegal content
- `spam` - Unsolicited messages
- `impersonation` - False identity
- `other` - Other issues

Set different thresholds per type in config.

## Database

SQLite database stores:
- All kind 1984 reports
- Reporter pubkeys
- Report types and timestamps
- Reported event IDs

**Location**: `./moderation_reports.db` (configurable)

**Auto-cleanup**: Old reports are automatically removed based on `time_window_days × 2`

### Query Database

```bash
# View all reports
sqlite3 moderation_reports.db "SELECT * FROM reports;"

# Count reports per event
sqlite3 moderation_reports.db "
  SELECT reported_event_id, COUNT(*) as count
  FROM reports
  GROUP BY reported_event_id
  ORDER BY count DESC;
"

# Reports by type
sqlite3 moderation_reports.db "
  SELECT report_type, COUNT(*) as count
  FROM reports
  GROUP BY report_type;
"
```

## Example Output

```
================================================================================
Lookup Moderator - Nostr Kind 1984 Event Monitor
================================================================================
Database stats:
  Total reports: 47
  Unique reported events: 12
  Unique reporters: 23

Configuration:
  WoT Relay: wss://wot.nostr.net
  Report threshold: 3
  Time window: 30 days
  Auto-delete: True
  Monitored kinds: [30817, 31990]

Connecting to wss://wot.nostr.net...
  Added relay: wss://wot.nostr.net
Connected to relay!
Subscribing to kind 1984 moderation events...
Monitoring started. Press Ctrl+C to stop.

================================================================================
NEW MODERATION REPORT
Report ID: abc123def456...
Reporter: 789pubkey012...
Reported Event: xyz789event...
Report Type: spam
Content: This is spam content reported by user
Total reports: 3 (threshold: 3)
THRESHOLD REACHED - Event should be deleted!
Auto-delete enabled, deleting event...
Executing: /usr/local/bin/strfry delete --dir /var/lib/strfry --id xyz789event...
Successfully deleted event xyz789event... from strfry
Published delete event for xyz789event... to 1 relays
Event xyz789event... deleted successfully
================================================================================
```

## Troubleshooting

### Strfry delete command fails

**Check paths:**
```bash
which strfry  # Should match config.yaml executable path
ls -la /var/lib/strfry  # Should exist and contain strfry.conf
```

**Check permissions:**
```bash
# Make sure the user running the script can execute strfry
sudo -u strfry /usr/local/bin/strfry delete --help
```

**Test manually:**
```bash
# Try deleting an event manually
/usr/local/bin/strfry delete --dir /var/lib/strfry --id <some_event_id>
```

### Not seeing any reports

- Make sure wot.nostr.net is accessible: `curl -I https://wot.nostr.net`
- Check you're in someone's Web of Trust (wot.nostr.net filters by WoT)
- Verify monitored_kinds includes the events being reported
- Check logs for connection errors

### Delete events not being published

- Make sure `private_key` is set in config
- Verify `publish_deletes: true`
- Check `publish_relays` list is not empty
- Look for errors in logs about key parsing

## Security Considerations

### Private Key Storage

If publishing delete events:
- Store `config.yaml` with restricted permissions: `chmod 600 config.yaml`
- Consider using environment variables for private key
- Or use a dedicated moderation keypair (not your main key)

### Trust Model

- **WoT filtering**: wot.nostr.net only shows reports from your trust network
- **Threshold-based**: Multiple reports required (configurable)
- **Time-bounded**: Old reports expire
- **Transparent**: All reports in local database

### Attack Vectors

1. **Report spam**: Mitigated by WoT filtering (only trusted reporters)
2. **False reports**: Mitigated by threshold requirements
3. **Stale reports**: Mitigated by time windows
4. **Mass deletion**: Set appropriate thresholds per type

## Performance

- **CPU**: Low (event-driven)
- **Memory**: ~50-100 MB
- **Network**: Minimal (single relay connection)
- **Disk**: Database grows ~1 KB per report
- **Latency**: Delete executes within seconds of threshold

## Development

### Project Structure

```
lookup-moderator/
├── lookup_moderator.py        # Main monitoring daemon
├── moderation_db.py           # SQLite database abstraction
├── config.yaml.example        # Configuration template
├── requirements.txt           # Python dependencies (pip)
├── pyproject.toml             # Project metadata (uv/pip)
└── README.md                  # This file
```

### Testing

**Test with Python:**
```bash
# Test database
python3 -c "from moderation_db import ModerationDB; db = ModerationDB(':memory:'); print('OK')"

# Test config loading
python3 -c "import yaml; print(yaml.safe_load(open('config.yaml')))"

# Test in dry run mode (recommended!)
cp config.yaml.example config.yaml
# Edit config.yaml and set dry_run: true
python3 lookup_moderator.py
```

**Test with uv:**
```bash
# Install dependencies
uv pip install -r requirements.txt

# Test database
uv run python -c "from moderation_db import ModerationDB; db = ModerationDB(':memory:'); print('OK')"

# Test config loading
uv run python -c "import yaml; print(yaml.safe_load(open('config.yaml')))"

# Test in dry run mode (recommended!)
cp config.yaml.example config.yaml
# Edit config.yaml and set dry_run: true
uv run lookup_moderator.py
```

**Quick Dry Run Test:**
The easiest way to test the tool is with dry run mode enabled. This lets you:
- Verify your configuration is correct
- See what reports are coming in
- Understand what would be deleted without actually deleting anything
- Test without needing strfry installed

See the "Dry Run Mode" section above for detailed examples.

## FAQ

**Q: How do I test the tool without deleting anything?**
A: Enable dry run mode! Set `dry_run: true` in the moderation section of config.yaml. The tool will show you what it would do without executing any commands. See the "Dry Run Mode" section above for examples.

**Q: Do I need strfry installed to test in dry run mode?**
A: No! Dry run mode doesn't execute any strfry commands, so you can test the monitoring and reporting logic without having strfry installed.

**Q: Do I need to run my own relay?**
A: Yes, you need a strfry relay to delete content from (but not for dry run testing).

**Q: Can I use other relays besides wot.nostr.net?**
A: Technically yes, but you'd lose the WoT filtering. wot.nostr.net is recommended because it already filters by your trust network.

**Q: What if I don't want to auto-delete?**
A: Set `auto_delete: false` in config. The script will log when threshold is met but won't delete.

**Q: Can I moderate kinds other than 30817/31990?**
A: Yes, add them to `events.monitored_kinds` in config.

**Q: How do I know what's in my WoT on wot.nostr.net?**
A: wot.nostr.net uses your follow list (kind 3) and follows-of-follows. If you publish a follow list, you're in the network.

**Q: Can I run this without publishing delete events?**
A: Yes! Just leave `private_key` empty or set `publish_deletes: false`. The local deletion will still work.

**Q: Should I use pip or uv?**
A: Either works! uv is faster for installing dependencies and managing Python versions, but pip is more universally available. Use whichever you prefer.

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
- [wot.nostr.net](https://wot.nostr.net) - Web of Trust filtered relay

### NIP References

- [NIP-01](https://github.com/nostr-protocol/nips/blob/master/01.md) - Basic protocol
- [NIP-09](https://github.com/nostr-protocol/nips/blob/master/09.md) - Event deletion (kind 5)
- [NIP-56](https://github.com/nostr-protocol/nips/blob/master/56.md) - Reporting (kind 1984)

## Support

- GitHub Issues: https://github.com/nostr-net/lookup-moderator/issues

---

Built for the Nostr ecosystem
