# tlgr Agent Reference

Compact reference for LLM agents. Use `--json` for all calls.

## Authentication

**Authentication is interactive and requires a human.** Run `tlgr account add <phone>` manually, complete 2FA, then hand the CLI to your agent. Agents work with pre-authenticated accounts only.

## Global Flags

| Flag | Env | Purpose |
|------|-----|---------|
| `--json` | `TLGR_JSON=1` | JSON output (always use this) |
| `--results-only` | | Strip envelope, emit primary result only |
| `--select <fields>` | | Comma-separated dot-path field projection |
| `-a, --account <alias>` | `TLGR_ACCOUNT` | Select account |
| `--enable-commands <list>` | `TLGR_ENABLE_COMMANDS` | Sandbox: `message.send,chat.list` |
| `--dry-run, -n` | | Preview destructive ops without executing |
| `--no-input` | | Never prompt (agent mode) |
| `--cursor <token>` | | Pagination cursor (on list commands) |

## Output Modes

Always use `--json`. Responses are JSON objects. Errors also go to stdout as JSON with `exit_code != 0`.

## Pagination

List commands return `has_more` (bool) and `next_cursor` (opaque string). Pass `--cursor <next_cursor>` to get the next page. Stop when `has_more` is `false`.

## Exit Codes

| Code | Name | Meaning |
|------|------|---------|
| 0 | SUCCESS | OK |
| 1 | GENERIC | Unknown failure |
| 2 | USAGE | Bad arguments |
| 3 | EMPTY | No results |
| 4 | AUTH | Authentication needed |
| 5 | NOT_FOUND | Chat/entity not found |
| 6 | PERMISSION | Permission denied |
| 7 | RATE_LIMITED | Retry after `wait_seconds` |
| 8 | RETRYABLE | Transient error |
| 10 | CONFIG | Config error |
| 11 | DAEMON | Daemon error |
| 12 | IPC | IPC error |

## Commands

### Messages

```
tlgr message send <chat> <text> [--file PATH] [--caption TEXT] [--reply-to ID] [--silent]
→ {"id": 123, "chat_id": -100123, "date": "..."}

tlgr message list <chat> [--limit N] [--cursor TOKEN] [--sender] [--media]
→ {"messages": [...], "has_more": true, "next_cursor": "..."}

tlgr message get <chat> <msg_id>
→ {"id": 123, "text": "...", "sender": {...}, "media": {...}, ...}

tlgr message delete <chat> <id1> [id2 ...]
→ {"deleted": 2}

tlgr message search <chat> <query> [--limit N] [--cursor TOKEN] [--local] [--regex PATTERN]
→ {"messages": [...], "has_more": false}

tlgr message pin <chat> <msg_id>
→ {"pinned": true, "msg_id": 123}

tlgr message react <chat> <msg_id> <emoji>
→ {"reacted": true, "msg_id": 123, "emoji": "👍"}

tlgr message read <chat> [--up-to MSG_ID]
→ {"read": true, "chat_id": -100123}
```

### Chats

```
tlgr chat list [--type user|group|channel] [--search TEXT] [--limit N] [--cursor TOKEN]
→ {"chats": [{"id": ..., "name": ..., "type": ..., "username": ...}], "has_more": true, "next_cursor": "..."}

tlgr chat get <chat>
→ {"id": ..., "name": ..., "type": ..., "username": ...}

tlgr chat create <name> [--type group|channel] [--members USER1 USER2]
→ {"id": ..., "name": ..., "type": ...}

tlgr chat archive <chat>
→ {"archived": true, "chat_id": ...}

tlgr chat mute <chat> [duration_seconds]
→ {"muted": true, "chat_id": ...}

tlgr chat leave <chat>
→ {"left": true, "chat_id": ...}

tlgr chat typing <chat> [--duration SECONDS]
→ {"typing": true, "chat_id": ...}
```

### Contacts

```
tlgr contact list [--limit N] [--cursor TOKEN]
→ {"contacts": [{"id": ..., "name": ..., "username": ..., "phone": ...}], "has_more": false}

tlgr contact add <phone> [name]
→ {"added": true, "user_id": 123}

tlgr contact remove <user>
→ {"removed": true}

tlgr contact search <query> [--limit N] [--cursor TOKEN]
→ {"contacts": [...], "has_more": false}
```

### Users

```
tlgr user get <user>
→ {"id": ..., "first_name": ..., "username": ..., "bio": ..., "is_bot": false, ...}
```

### Profile

```
tlgr profile get
→ {"id": ..., "first_name": ..., "last_name": ..., "username": ..., "phone": ...}

tlgr profile update [--first-name TEXT] [--last-name TEXT] [--bio TEXT] [--photo PATH]
→ {"updated": true}
```

### Media

```
tlgr media download <chat> <msg_id> [--out-dir PATH]
→ {"path": "/path/to/file", "msg_id": 123}

tlgr media upload <chat> <path> [--caption TEXT]
→ {"id": 200, "chat_id": -100123}
```

### Agent Helpers

```
tlgr agent whoami
→ {"account": "main", "user_id": 123, "username": "me", "daemon_running": true, ...}

tlgr agent exit-codes
→ {"exit_codes": {...}}

tlgr schema [command_path...]
→ {"schema_version": 1, "build": "2.0.0", "command": {...}}
```

### Daemon

```
tlgr daemon start [--foreground]
tlgr daemon stop
tlgr daemon status
→ {"running": true, "pid": 12345, "uptime_seconds": 3600, "accounts": ["main"]}
```

### Streaming

```
tlgr watch [--chat CHAT1 --chat CHAT2]
→ newline-delimited JSON to stdout, one event per line
```

## Error Response Shape

```json
{"error": "message text", "code": "RATE_LIMITED", "exit_code": 7, "wait_seconds": 30}
```

## Chat Resolution

Chat arguments accept:
- Numeric ID: `12345`, `-100123456`
- Username: `@username`

Display names and phone numbers are NOT accepted for chat arguments.

## Rate Limiting

Telegram rate limits are surfaced as exit code 7 with `wait_seconds` in the JSON error. The agent should back off accordingly.

## Sandboxing

Use `--enable-commands` to restrict what the agent can do:
- `--enable-commands message.send,message.list,chat.list` — only these commands
- `--enable-commands message` — all message subcommands
- `--enable-commands '*'` — everything (default)

## Self-Discovery

Run `tlgr schema --json` for the full machine-readable CLI schema with parameter types, defaults, and example responses.
