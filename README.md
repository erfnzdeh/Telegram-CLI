# tlgr

Full Telegram account control from the terminal -- agent-friendly, daemon-based, with an extensible event pipeline.

```
pip install tlgr
```

## Architecture

tlgr has three layers, each serving a different purpose:

```
                    ┌────────────────────────────────────┐
                    │              tlgr                   │
                    │                                     │
  You / Agent ─────┤  Layer 1: CLI                       │
                    │  One-shot commands                  │
                    │  send, list, download, manage       │
                    │                                     │
                    ├────────────────────────────────────-─┤
                    │                                     │
  Telegram ◄───────┤  Layer 2: Gateway                   │
                    │  Event-driven pipeline              │
                    │  event → filters → processors →     │
                    │  actions                            │
                    │                                     │
                    ├─────────────────────────────────────┤
                    │                                     │
  HTTP endpoints ◄─┤  Layer 3: Webhook                   │
                    │  Outbound push                      │
                    │  events → HTTP POST                 │
                    │                                     │
                    └────────────────────────────────────-┘
```

**CLI** -- direct commands that connect to Telegram, do their thing, and exit.
Send messages, list chats, download media, manage accounts.

**Gateway** -- the always-on event pipeline running inside the daemon. Receives
Telegram events, runs them through filters, optionally processes text, then
executes actions (reply, forward, and more). All three subsystems (filters,
processors, actions) are registry-based and extensible.

**Webhook** -- pushes Telegram events to external HTTP endpoints for agent
integration.

### How it connects

```
                              ┌──────────────────────┐
  tlgr CLI ──────────────────►│                      │
                              │    tlgr daemon       │
  tlgr CLI ──── IPC socket ──►│                      │──── Telegram API
                              │  ┌── Gateway jobs    │
                              │  └── Webhook push ───┼──── HTTP endpoints
                              └──────────────────────┘
```

The daemon auto-starts when you run any command that needs it.

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

## Gateway -- Event Pipeline

The Gateway is the core of tlgr's automation. Each job is a declarative
pipeline defined in `~/.tlgr/jobs.yaml`:

```
  Telegram event
       │
       ▼
  ┌─────────┐
  │ Filters  │  chat_type, contains, regex, time_of_day, ...
  │ (AND/OR/ │  Composable with any_of / none_of
  │  NOT)    │
  └────┬─────┘
       │ passed
       ▼
  ┌────────────┐
  │ Processors │  strip_formatting, add_prefix, regex_replace, ...
  │ (optional) │  Text modification chain
  └────┬───────┘
       │
       ▼
  ┌─────────┐
  │ Actions  │  reply, forward, ...
  │ (1..N)   │  Each can have its own filters & processors
  └──────────┘
```

### Example: auto-reply to private messages

```yaml
jobs:
  - name: private-bot
    account: main
    filters:
      chat_type: private
    actions:
      - reply: "shut up i'm just a bot!"
```

### Example: forward with text processing

```yaml
jobs:
  - name: news-forward
    account: main
    filters:
      chat_id: "@raw_feed"
      types: [text, photo]
      contains: [breaking]
    actions:
      - forward:
          to: ["@clean_feed"]
          processors: [strip_formatting]
      - forward:
          to: ["@archive"]
```

### Example: complex filter composition

```yaml
jobs:
  - name: smart-reply
    account: main
    filters:
      chat_type: private
      any_of:
        - contains: [hello, hi]
        - from_users: [12345]
      none_of:
        - contains: [spam, ad]
    actions:
      - reply: "Thanks for reaching out!"
```

See [tlgr/gateway/README.md](tlgr/gateway/README.md) for the full pipeline reference.

## Filters

Registry-based, composable filters. Top-level keys are AND'd. Use `any_of`
for OR, `none_of` for NOT.

| Filter | Description | Value |
|--------|-------------|-------|
| `chat_type` | private, group, supergroup, channel | `str` or `list` |
| `chat_id` | Match by chat ID or @username | `int/str` or `list` |
| `chat_title` | Regex match on chat title | `str` (pattern) |
| `is_incoming` | Incoming vs outgoing | `bool` |
| `sender_is_bot` | Sender is a bot | `bool` |
| `sender_is_self` | Sent by yourself | `bool` |
| `contains` | All keywords must appear | `list[str]` |
| `contains_any` | At least one keyword | `list[str]` |
| `excludes` | No keyword may appear | `list[str]` |
| `regex` | Text must match pattern | `str` (pattern) |
| `has_links` | Has URL entities | `bool` |
| `types` | Message type whitelist | `list[str]` |
| `exclude_types` | Message type blacklist | `list[str]` |
| `has_media` | Has media attachment | `bool` |
| `is_reply` | Is a reply | `bool` |
| `is_forward` | Is forwarded | `bool` |
| `after` | After date/time | `str` (date) |
| `before` | Before date/time | `str` (date) |
| `time_of_day` | Within time range | `str` (`"HH:MM-HH:MM"`) |
| `from_users` | Sender in list | `list[int]` |
| `exclude_users` | Sender not in list | `list[int]` |

See [tlgr/filters/README.md](tlgr/filters/README.md) for composition examples and how to add custom filters.

## Processors

Text modification functions applied in sequence:

| Processor | Description | Config |
|-----------|-------------|--------|
| `replace_mentions` | Replace @mentions | `replacement`, `pattern` |
| `remove_links` | Remove URLs | `replacement` |
| `remove_hashtags` | Remove #hashtags | `replacement` |
| `strip_formatting` | Normalize whitespace | -- |
| `add_prefix` | Add text at start | `prefix` |
| `add_suffix` | Add text at end | `suffix` |
| `regex_replace` | Custom regex | `pattern`, `replacement`, `flags` |

Inline regex in YAML:

```yaml
processors:
  - strip_formatting
  - type: regex
    pattern: "\\b(secret)\\b"
    replacement: "[REDACTED]"
    flags: i
```

See [tlgr/processors/README.md](tlgr/processors/README.md) for the full reference.

## Actions

| Action | Description | Config |
|--------|-------------|--------|
| `reply` | Reply to the message | `str` (reply text) |
| `forward` | Forward to destinations | `{to: [...], drop_author: bool, processors: [...]}` |

Each action in a job's action list can have its own `filters` and `processors`
overrides. See [tlgr/actions/README.md](tlgr/actions/README.md).

## CLI Commands

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
tlgr job add                          Open jobs.yaml in $EDITOR
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

| File | Format | Purpose |
|------|--------|---------|
| `config.toml` | TOML | App defaults, daemon, accounts |
| `jobs.yaml` | YAML | Gateway job definitions |
| `webhook.toml` | TOML | Outbound webhook push |

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

### webhook.toml

```toml
[webhook]
enabled = true
url = "http://127.0.0.1:18789/hooks/agent"
token = "shared-secret"
events = ["new_message", "message_edited", "message_deleted"]

[webhook.retry]
enabled = true
max_attempts = 3
backoff_base = 2

[webhook.filters]
chats = ["@important_channel"]
```

Events are POSTed as JSON with `Authorization: Bearer <token>`:

```json
{
  "event_type": "new_message",
  "timestamp": "2025-03-06T12:00:00Z",
  "account": "main",
  "data": { "..." }
}
```

## Output Formats

```bash
# Human-readable (default) -- colored tables
tlgr chat list

# JSON -- for scripting and agents
tlgr --json chat list | jq '.chats[] | .name'

# Plain TSV -- for piping
tlgr --plain chat list | cut -f2
```

## Multi-Account

```bash
tlgr account add +15551234567 --alias personal
tlgr account add +15559876543 --alias work
tlgr -a personal message send @friend "Hi"
```

Jobs can reference different accounts:

```yaml
jobs:
  - name: work-forward
    account: work
    # ...
```

## Extending tlgr

All three pipeline components use the same registry pattern. Add a custom
filter, processor, or action by writing a decorated function:

```python
from tlgr.filters import register_filter

@register_filter("my_filter")
def my_filter(event, value):
    # your logic here
    return True, "matched"
```

See the package READMEs for details:
- [Filters](tlgr/filters/README.md)
- [Processors](tlgr/processors/README.md)
- [Actions](tlgr/actions/README.md)
- [Gateway](tlgr/gateway/README.md)

## Error Handling

When `--json` is active, errors are returned as JSON on stdout with a non-zero exit code:

```json
{"error": "Chat not found", "code": "CHAT_NOT_FOUND"}
```

Human-readable errors go to stderr. Rate limits are auto-waited with the duration reported.

## License

MIT
