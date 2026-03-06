# tlgr

![GitHub Repo Banner](https://ghrb.waren.build/banner?header=tlgr%F0%9F%A7%AD&subheader=Telegram+in+your+terminal&bg=f3f4f6&color=1f2937&support=true)
<!-- Created with GitHub Repo Banner by Waren Gonzaga: https://ghrb.waren.build -->

Full Telegram account control from the terminal. Agent-friendly, daemon-based, with webhook event push.

```
pip install tlgr
```

## Quickstart

```bash
tlgr config init                              # create config files
tlgr account add +15551234567                  # authenticate
tlgr daemon start                             # start background daemon
tlgr message send @username "Hello from tlgr" # send a message
tlgr chat list --limit 20                     # list your chats
```

## CLI

Every Telegram operation available as a single command. Three output modes: human-readable tables (default), JSON (`--json`) for agents, and plain TSV (`--plain`) for piping.

```mermaid
flowchart LR
    USER["You / Agent"] --> CLI["tlgr CLI"]
    CLI -->|"direct"| TG["Telegram API"]
    CLI -->|"IPC socket"| DAEMON["tlgr daemon"]
    DAEMON --> TG
```

### Messages

```bash
tlgr message send <chat> <text>        # --file, --caption, --reply-to, --silent
tlgr message list <chat>               # --limit, --sender, --media, --reactions
tlgr message get <chat> <msg_id>       # full metadata
tlgr message delete <chat> <ids...>
tlgr message search <chat> <query>     # --local for regex, --regex <pattern>
tlgr message pin <chat> <msg_id>
tlgr message react <chat> <id> <emoji>
```

### Chats

```bash
tlgr chat list                         # --type, --search, --limit
tlgr chat get <chat>
tlgr chat create <name>                # --type group|channel, --members
tlgr chat archive <chat>
tlgr chat mute <chat> [duration]
tlgr chat leave <chat>
```

### Contacts

```bash
tlgr contact list
tlgr contact add <phone> [name]
tlgr contact remove <user>
tlgr contact search <query>
```

### Media

```bash
tlgr media download <chat> <msg_id>    # --out-dir
tlgr media upload <chat> <path>        # --caption
```

### Profile

```bash
tlgr profile get
tlgr profile update                    # --first-name, --last-name, --bio, --photo
```

### Accounts

```bash
tlgr account add <phone>              # authenticate a new account
tlgr account list                     # (* = default)
tlgr account switch <alias>
tlgr account remove <alias>
tlgr account rename <old> <new>
tlgr account info [alias]
```

### Daemon

```bash
tlgr daemon start                     # --foreground
tlgr daemon stop
tlgr daemon status
tlgr daemon logs                      # --follow
```

### Global Flags

```
--json              JSON to stdout (for scripting and agents)
--plain             Stable TSV for piping
-a, --account TEXT  Account alias to use
--version / --help
```

## Webhook -- Event Push

tlgr pushes Telegram events to an external HTTP endpoint in real time. Designed for agentic interfaces like [OpenClaw](https://github.com/openclaw) where an agent receives events and calls `tlgr` CLI commands to act.

```mermaid
flowchart LR
    TG["Telegram"] --> DAEMON["tlgr daemon"]
    DAEMON -->|"POST /hooks/agent"| AGENT["Your Agent"]
    AGENT -->|"tlgr --json message send ..."| CLI["tlgr CLI"]
    CLI --> TG
```

Configure in `~/.tlgr/webhook.toml`:

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

Events arrive as JSON with `Authorization: Bearer <token>`:

```json
{
  "event_type": "new_message",
  "timestamp": "2025-03-06T12:00:00Z",
  "account": "main",
  "data": { "..." }
}
```

## Gateway -- Background Jobs

tlgr also ships with a deterministic, always-on Gateway that runs background jobs on your Telegram account. Define declarative pipelines in `~/.tlgr/jobs.yaml` that automatically react to incoming messages -- auto-reply, auto-forward, filter by chat type, time of day, content, and more.

```mermaid
flowchart LR
    TG["Telegram event"] --> F["Filters"]
    F -->|"passed"| P["Processors"]
    P --> A["Actions"]
    A --> R["reply / forward / ..."]
```

A few examples of what you can do:

```yaml
jobs:
  # Auto-reply to all private messages
  - name: private-bot
    account: main
    filters:
      chat_type: private
    actions:
      - reply: "shut up i'm just a bot!"

  # Forward breaking news to your archive
  - name: news-forward
    account: main
    filters:
      chat_id: "@raw_feed"
      types: [text, photo]
      contains: [breaking]
    actions:
      - forward:
          to: ["@clean_feed", "@archive"]
          processors: [strip_formatting]

  # Night-mode auto-reply
  - name: night-mode
    account: main
    filters:
      chat_type: private
      time_of_day: "23:00-07:00"
    actions:
      - reply: "I'm sleeping. Will reply tomorrow."
```

Filters support full AND / OR / NOT composition, 20+ built-in filter types, 7 text processors, and a registry pattern for adding your own.

For the full Gateway reference -- filters, processors, actions, composition, extensibility -- see **[Gateway documentation](tlgr/gateway/README.md)**.

## Configuration

Config files live in `~/.tlgr/`:

| File | Format | Purpose |
|------|--------|---------|
| `config.toml` | TOML | App defaults, daemon, accounts |
| `jobs.yaml` | YAML | Gateway job definitions |
| `webhook.toml` | TOML | Outbound webhook push |

```bash
tlgr config init       # create defaults
tlgr config validate   # check syntax + validate filter/action names
tlgr job add           # open jobs.yaml in $EDITOR
tlgr job list          # show running jobs
```

### config.toml

```toml
[defaults]
output = "human"

[accounts]
default = "main"

[daemon]
auto_start = true
log_level = "info"
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

## License

See [LICENSE](LICENSE) for license details.
