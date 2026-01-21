# Telegram CLI Forwarder

A command-line tool for automating Telegram message forwarding using Telethon.

## Features

- **Batch Forwarding**: Forward up to 100 messages per API call (10-100x more efficient)
- **Multiple Destinations**: Forward to multiple chats at once
- **Drop Author**: Remove "Forwarded from" header (appears as original message)
- **Delete After Forward**: Delete messages from source after forwarding (requires admin)
- **Real-time Forwarding**: Forward new messages as they arrive
- **Resume Capability**: Continue interrupted batch operations
- **Fault Tolerant**: Automatic checkpointing, graceful shutdown, flood wait handling
- **Progress Tracking**: Visual progress bars and job status

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/Telegram-CLI.git
cd Telegram-CLI

# Install dependencies
pip install -r requirements.txt
```

## Setup

1. Get your API credentials from [my.telegram.org](https://my.telegram.org):
   - Log in with your phone number
   - Go to "API development tools"
   - Create an application to get `api_id` and `api_hash`

2. Login to Telegram:

```bash
python -m telegram_forwarder login
```

You'll be prompted to enter your API credentials, phone number, and verification code.

## Usage

### List Available Chats

```bash
python -m telegram_forwarder list-chats
```

Output:
```
     -100123456  [  Channel  ]  My Source Channel
     -100789012  [  Channel  ]  Backup Channel
       12345678  [ Private  ]  John Doe (@johndoe)
```

### Test Permissions

```bash
python -m telegram_forwarder test -s -100123456 -d -100789012 --delete
```

### Forward Last N Messages

```bash
# Basic forward (with "Forwarded from" header)
python -m telegram_forwarder forward-last -s -100123456 -d -100789012 --count 50

# Without "Forwarded from" header
python -m telegram_forwarder forward-last -s -100123456 -d -100789012 --count 50 --drop-author

# Forward to multiple destinations
python -m telegram_forwarder forward-last \
    -s -100123456 \
    -d -100789012 \
    -d -100789013 \
    --count 50 \
    --drop-author

# Forward and delete from source
python -m telegram_forwarder forward-last -s -100123456 -d -100789012 --count 50 --delete
```

### Forward All Messages

```bash
python -m telegram_forwarder forward-all \
    -s -100123456 \
    -d -100789012 \
    --drop-author
```

Output:
```
Source: -100123456 (My Source Channel)
Destinations: -100789012
Estimated: ~12.5K messages
Mode: forward (drop author)
Batch size: 100 messages per API call

Proceed? [y/N]: y
Job ID: abc12345
[==============================] 12500/12500 (100.0%)
Complete: 12500 forwarded, 150 skipped, 0 failed
```

### Real-time Forwarding

```bash
python -m telegram_forwarder forward-live \
    -s -100123456 \
    -d -100789012 \
    --drop-author
```

Press `Ctrl+C` to stop.

### Resume Interrupted Jobs

```bash
# List resumable jobs
python -m telegram_forwarder resume

# Resume specific job
python -m telegram_forwarder resume abc12345
```

### Check Job Status

```bash
python -m telegram_forwarder status
```

## Command Reference

| Command | Description |
|---------|-------------|
| `login` | Authenticate with Telegram |
| `logout` | Clear session and log out |
| `list-chats` | List available chats with IDs |
| `test` | Verify permissions for source/destination |
| `forward-last` | Forward last X messages |
| `forward-live` | Start real-time forwarding |
| `forward-all` | Forward all messages in batches |
| `resume` | Resume an interrupted operation |
| `status` | Show job history and progress |

### Global Flags

| Flag | Description |
|------|-------------|
| `-v, --verbose` | Increase verbosity (stack: -vv, -vvv) |
| `-q, --quiet` | Suppress all output except errors |
| `-y, --yes` | Skip confirmation prompts |

### Forward Flags

| Flag | Description |
|------|-------------|
| `-s, --source` | Source chat ID or @username |
| `-d, --dest` | Destination chat ID (repeatable) |
| `--drop-author` | Remove "Forwarded from" header |
| `--delete` | Delete from source after forwarding |
| `--dry-run` | Preview without executing |
| `--count` | Number of messages (forward-last) |
| `--batch-size` | Messages per batch (max 100) |

## Configuration

Configuration is stored in `~/.telegram-forwarder/`:

- `config.json` - API credentials and settings
- `session.session` - Telegram session file
- `jobs.json` - Job history and progress
- `logs/` - Log files (one per day)

### Environment Variables

You can also set credentials via environment variables:

```bash
export TELEGRAM_API_ID=12345678
export TELEGRAM_API_HASH=0123456789abcdef
```

## Fault Tolerance

- **Automatic Checkpointing**: Progress saved after every batch (100 messages)
- **FloodWait Handling**: Auto-sleep for rate limits up to 2 minutes
- **Connection Recovery**: Auto-reconnect and retry on failures
- **Graceful Shutdown**: `Ctrl+C` saves progress and shows resume command
- **Resume Capability**: Continue from last processed message

## Error Handling

| Error | Handling |
|-------|----------|
| FloodWaitError (<120s) | Automatic sleep and retry |
| FloodWaitError (>120s) | Sleep with countdown, retry |
| PeerFloodError | **STOP** - Account may be limited |
| ChannelPrivateError | Skip with error message |
| ChatWriteForbiddenError | Skip destination, continue |
| MessageIdInvalidError | Skip message, continue |

## License

MIT

## Disclaimer

This tool is for personal use only. Please respect Telegram's Terms of Service and don't use it for spam or abuse. You are responsible for how you use this tool.
