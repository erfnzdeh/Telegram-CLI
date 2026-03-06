# tlgr

![GitHub Repo Banner](https://ghrb.waren.build/banner?header=tlgr%F0%9F%A7%AD&subheader=Telegram+in+your+terminal&bg=f3f4f6&color=1f2937&support=true)
<!-- Created with GitHub Repo Banner by Waren Gonzaga: https://ghrb.waren.build -->

Full Telegram account control CLI — agent-friendly, daemon-based, with webhook event push.

```
pip install tlgr
```

## Quickstart

```bash
# 1. Create config files
tlgr config init

# 2. Add a Telegram account
tlgr account add +15551234567

# 3. Start the daemon
tlgr daemon start

# 4. Send a message
tlgr message send @username "Hello from tlgr"

# 5. List your chats
tlgr chat list --limit 20
```

## Architecture

tlgr runs a persistent daemon process that holds Telegram connections and processes background jobs. CLI commands route through the daemon via a Unix domain socket.

```
tlgr CLI ──→ Unix socket ──→ tlgr daemon ──→ Telegram API
                                  │
                                  ├──→ Background jobs (autoforward, autoreply)
                                  └──→ Webhook push (POST events to agent)
```

The daemon auto-starts when you run any command that needs it.

## Output Formats

All commands support three output modes:

```bash
# Human-readable (default) — colored tables
tlgr chat list

# JSON — for scripting and agents
tlgr --json chat list | jq '.chats[] | .name'

# Plain TSV — for piping
tlgr --plain chat list | cut -f2
```

## Commands

```
tlgr account add <phone>              Authenticate a new account
tlgr account list                     List accounts (* = default)
tlgr account switch <alias>           Set default account
tlgr account remove <alias>           Remove account
tlgr account rename <old> <new>       Rename alias
tlgr account info [alias]             Show details

tlgr message send <chat> <text>       Send text (--file, --caption, --reply-to, --silent)
tlgr message list <chat>              List messages (--limit, --sender, --media, --reactions)
tlgr message get <chat> <msg_id>      Get single message with full metadata
tlgr message delete <chat> <ids...>   Delete messages
tlgr message search <chat> <query>    Search (--local for regex, --regex <pattern>)
tlgr message pin <chat> <msg_id>      Pin a message
tlgr message react <chat> <id> <emoji> React to a message

tlgr chat list                        List chats (--type, --search, --limit)
tlgr chat get <chat>                  Chat info
tlgr chat create <name>               Create group/channel (--type, --members)
tlgr chat archive <chat>              Archive
tlgr chat mute <chat> [duration]      Mute (seconds, omit for permanent)
tlgr chat leave <chat>                Leave

tlgr contact list                     List contacts
tlgr contact add <phone> [name]       Add contact
tlgr contact remove <user>            Remove contact
tlgr contact search <query>           Search contacts

tlgr profile get                      Show your profile
tlgr profile update                   Update (--first-name, --last-name, --bio, --photo)

tlgr media download <chat> <msg_id>   Download media (--out-dir)
tlgr media upload <chat> <path>       Upload file (--caption)

tlgr daemon start                     Start daemon (--foreground)
tlgr daemon stop                      Stop daemon
tlgr daemon status                    Show status
tlgr daemon logs                      View logs (--follow)

tlgr job list                         List background jobs
tlgr job add                          Open jobs.toml in $EDITOR
tlgr job remove <name>                Remove job
tlgr job enable <name>                Enable job
tlgr job disable <name>               Disable job

tlgr config init                      Create default config files
tlgr config validate                  Validate configs

tlgr completion bash|zsh|fish         Shell completions
```

## Global Flags

```
--json              Output JSON to stdout
--plain             Output stable TSV for piping
-a, --account TEXT  Account alias to use
--version           Show version
--help              Show help
```

## Configuration

Config files live in `~/.tlgr/`:

### config.toml

```toml
[defaults]
drop_author = false
delete_after = false
output = "human"

[accounts]
default = "main"

[daemon]
auto_start = true
log_level = "info"
```

### jobs.toml — Background Jobs

```toml
[[jobs]]
name = "news-forward"
type = "autoforward"
account = "main"
source = "@news_channel"
destinations = ["@my_archive", "@friend"]
drop_author = true
transforms = ["strip_formatting", "add_prefix:prefix=[NEWS]"]

[jobs.filters]
types = ["text", "photo"]
contains = ["breaking"]

[[jobs]]
name = "away-reply"
type = "autoreply"
account = "main"
chats = ["*"]
reply = "Away until Monday"

[jobs.filters]
after = "2025-03-01"
before = "2025-03-10"
```

### webhook.toml — Event Push

Push Telegram events to an external agent (e.g., OpenClaw):

```toml
[webhook]
enabled = true
url = "http://127.0.0.1:18789/hooks/agent"
token = "shared-secret"
events = ["new_message", "message_edited", "message_deleted", "user_joined", "user_left", "chat_action", "message_read", "reaction"]

[webhook.retry]
enabled = true
max_attempts = 3
backoff_base = 2

[webhook.filters]
chats = ["@important_channel", "-100123456"]
```

Events are POSTed as JSON with `Authorization: Bearer <token>`:

```json
{
  "event_type": "new_message",
  "timestamp": "2025-03-06T12:00:00Z",
  "account": "main",
  "data": { ... }
}
```

## Transforms

Available transforms for autoforward jobs:

| Transform | Description | Config |
|-----------|-------------|--------|
| `replace_mentions` | Replace @mentions | `replacement`, `pattern` |
| `remove_links` | Remove URLs | `replacement` |
| `remove_hashtags` | Remove #hashtags | `replacement` |
| `strip_formatting` | Normalize whitespace | — |
| `add_prefix` | Add text at start | `prefix` |
| `add_suffix` | Add text at end | `suffix` |
| `regex_replace` | Custom regex | `pattern`, `replacement`, `flags` |

Inline TOML regex transforms:

```toml
[[jobs.transforms]]
type = "regex"
pattern = "\\b(secret)\\b"
replacement = "[REDACTED]"
flags = "i"
```

## Error Handling

When `--json` is active, errors are returned as JSON on stdout with a non-zero exit code:

```json
{"error": "Chat not found", "code": "CHAT_NOT_FOUND"}
```

Human-readable errors go to stderr. Rate limits are auto-waited with the duration reported:

```json
{"result": { ... }, "flood_wait": 30}
```

## Multi-Account

```bash
tlgr account add +15551234567 --alias personal
tlgr account add +15559876543 --alias work
tlgr account list
tlgr account switch work
tlgr -a personal message send @friend "Hi"
```

Jobs in jobs.toml can reference different accounts:

```toml
[[jobs]]
name = "work-forward"
account = "work"
...
```

## Agent Integration

tlgr is designed to be controlled by AI agents. The typical flow:

1. Agent receives events via webhook push
2. Agent processes events and decides on actions
3. Agent calls `tlgr` CLI commands to act

```bash
# Agent sends a reply
tlgr --json message send @user "Got it, processing..."

# Agent searches for context
tlgr --json message search @channel "project update" --limit 5

# Agent downloads an attachment
tlgr --json media download @channel 12345
```

## License

MIT
