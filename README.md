# Telegram CLI Forwarder

A command-line tool for automating Telegram message forwarding using Telethon.

## Features

- **Batch Forwarding**: Forward up to 100 messages per API call (10-100x more efficient)
- **Multiple Destinations**: Forward to multiple chats at once
- **Drop Author**: Remove "Forwarded from" header (appears as original message)
- **Delete After Forward**: Delete messages from source after forwarding (requires admin)
- **Real-time Forwarding**: Forward new messages as they arrive
- **Daemon Mode**: Run multiple forwarding jobs in background with `--daemon`
- **Resume Capability**: Continue interrupted batch operations
- **Fault Tolerant**: Automatic checkpointing, graceful shutdown, flood wait handling
- **Progress Tracking**: Visual progress bars and job status

## Architecture

```mermaid
flowchart TD
    CLI[CLI Interface] --> Auth[Authentication]
    CLI --> Config[Config Management]
    CLI --> Forward[Forwarding Engine]
    CLI --> State[State Manager]
    CLI --> Logger[Logger]
    
    Auth --> TelegramClient[Telethon Client]
    Config --> SessionFile[Session Storage]
    State --> ProgressDB[Progress JSON]
    Logger --> LogFile[Log Files]
    
    Forward --> BatchForward[Batch Forward]
    Forward --> RealtimeForward[Real-time Forward]
    Forward --> MultiDest[Multi-Destination]
    Forward --> DeleteAfter[Delete After Forward]
    Forward --> DropAuthor[--drop-author Flag]
    
    BatchForward --> iter_messages[iter_messages]
    RealtimeForward --> NewMessageEvent[events.NewMessage]
    DeleteAfter --> AdminCheck[Check Admin/Private]
    
    Forward --> ErrorHandler[Error Handler]
    Forward --> Utils[Utils]
    Utils --> CountEstimate[Count Estimation]
    Utils --> ChatValidation[Chat Validation]
    ErrorHandler --> RetryLogic[Retry with Backoff]
    ErrorHandler --> FloodWait[FloodWait Handler]
    ErrorHandler --> Checkpointing[Auto Checkpoint]
```

## Installation

### Via pip (Recommended)

```bash
pip install telegram-cli
```

### Via pipx (Isolated Environment)

```bash
pipx install telegram-cli
```

### From Source

```bash
git clone https://github.com/erfnzdeh/Telegram-CLI.git
cd Telegram-CLI
pip install -e .
```

## Setup

1. Get your API credentials from [my.telegram.org](https://my.telegram.org):
   - Log in with your phone number
   - Go to "API development tools"
   - Create an application to get `api_id` and `api_hash`

2. Login to Telegram:

```bash
telegram-cli login
```

You'll be prompted to enter your API credentials, phone number, and verification code.

## Usage

### List Available Chats

```bash
telegram-cli list-chats
```

Output:
```
     -100123456  [  Channel  ]  My Source Channel
     -100789012  [  Channel  ]  Backup Channel
       12345678  [ Private  ]  John Doe (@johndoe)
```

### Test Permissions

```bash
telegram-cli test -s -100123456 -d -100789012 --delete
```

### Forward Last N Messages

```bash
# Basic forward (with "Forwarded from" header)
telegram-cli forward-last -s -100123456 -d -100789012 --count 50

# Without "Forwarded from" header
telegram-cli forward-last -s -100123456 -d -100789012 --count 50 --drop-author

# Forward to multiple destinations
telegram-cli forward-last \
    -s -100123456 \
    -d -100789012 \
    -d -100789013 \
    --count 50 \
    --drop-author

# Forward and delete from source
telegram-cli forward-last -s -100123456 -d -100789012 --count 50 --delete
```

### Forward All Messages

```bash
telegram-cli forward-all \
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
telegram-cli forward-live \
    -s -100123456 \
    -d -100789012 \
    --drop-author
```

Press `Ctrl+C` to stop.

### Resume Interrupted Jobs

```bash
# List resumable jobs
telegram-cli resume

# Resume specific job
telegram-cli resume abc12345
```

### Check Job Status

```bash
telegram-cli status
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
| `list` | List running background daemons |
| `kill` | Kill a background daemon by PID |
| `logs` | View daemon logs |

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
| `--daemon` | Run in background (daemon mode) |

## Daemon Mode (Background Processing)

Run forwarding operations in the background. You can run multiple daemons simultaneously.

### Start a Daemon

```bash
# Run any forward command with --daemon
telegram-cli forward-all -s -100123456 -d -100789012 --daemon
telegram-cli forward-live -s -100123456 -d -100789012 --daemon
```

Output:
```
Starting daemon...
PID: 12345
Logs: telegram-cli logs 12345
Kill: telegram-cli kill 12345
List: telegram-cli list
```

### List Running Daemons

```bash
telegram-cli list
```

Output:
```
Running daemons (2):
----------------------------------------------------------------------
     PID  Command               Source        Started
----------------------------------------------------------------------
   12345  forward-all         -100123456  2026-02-02T14:30:00
   12346  forward-live        -100789012  2026-02-02T15:00:00
----------------------------------------------------------------------
Kill with: telegram-cli kill <PID>
View logs: telegram-cli logs <PID>
```

### Kill a Daemon

```bash
# Kill specific daemon by PID
telegram-cli kill 12345

# Force kill (SIGKILL)
telegram-cli kill 12345 -f

# Kill all running daemons
telegram-cli kill --all
```

### View Daemon Logs

```bash
# View logs for specific PID
telegram-cli logs 12345

# View most recent daemon logs
telegram-cli logs

# Follow logs in real-time (like tail -f)
telegram-cli logs 12345 -f

# Show last 100 lines
telegram-cli logs -n 100
```

## Configuration

Configuration is stored in `~/.telegram-cli/`:

- `config.json` - API credentials and settings
- `session.session` - Telegram session file
- `jobs.json` - Job history and progress
- `daemons.json` - Running daemon processes
- `logs/` - Log files (per daemon and daily)

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
