# Gateway

The Gateway is tlgr's generic event-driven pipeline engine. It replaces the
old `AutoforwardJob` and `AutoreplyJob` with a single class that runs any
combination of filters, processors, and actions.

## Mental model

A Gateway job is a pipeline:

```
  Event Source (Telegram, future: webhook)
       │
       ▼
  ┌────────────────────┐
  │   Event Envelope   │  Thin wrapper: source + raw payload + account
  └────────┬───────────┘
           │
           ▼
  ┌────────────────────┐
  │   Filter Tree      │  AND / OR / NOT composition
  │                    │  Two phases: event-context + message-content
  └────────┬───────────┘
           │ passed
           ▼
  ┌────────────────────┐
  │   Processors       │  Optional text modification chain
  │   (job-level)      │
  └────────┬───────────┘
           │
           ▼
  ┌────────────────────┐
  │   Action List      │  1..N actions, each may override
  │                    │  filters and processors
  │  ┌──────────────┐  │
  │  │ Action 1     │  │  e.g. reply: "hello!"
  │  ├──────────────┤  │
  │  │ Action 2     │  │  e.g. forward: {to: "@log"}
  │  │  filters: .. │  │  per-action filter override
  │  │  processors: │  │  per-action processor override
  │  └──────────────┘  │
  └────────────────────┘
```

## Event Envelope

Defined in `event.py`:

```python
@dataclass(slots=True)
class Event:
    source: str          # "telegram", "webhook", etc.
    raw: Any             # original Telethon event or webhook payload
    account: str         # which account received it
    timestamp: datetime
```

The envelope is intentionally thin. Filters extract what they need from `raw`
directly, keeping the envelope protocol-agnostic.

## Configuration

Jobs are defined in `~/.tlgr/jobs.yaml`. The Gateway config parser (`config.py`)
reads this file and produces `GatewayConfig` objects.

```yaml
jobs:
  - name: my-job
    account: main
    enabled: true           # default: true
    filters:                # optional
      chat_type: private
    processors:             # optional, job-level
      - strip_formatting
    actions:
      - reply: "hello!"
      - forward:
          to: ["@archive"]
          processors: [add_prefix:prefix=[FWD]]  # overrides job-level
```

### Action config syntax

Actions use concise syntax where the action name is the key:

```yaml
# Simple: string value
- reply: "hello!"

# Complex: dict value with sub-keys
- forward:
    to: ["@dest1", "@dest2"]
    drop_author: true
    filters:
      has_media: true
    processors:
      - strip_formatting
```

## Engine lifecycle

The `Gateway` class extends `BaseJob` so it integrates with the daemon's
`JobRunner` lifecycle:

1. **setup()** -- logs configuration, resolves any needed entities
2. **run()** -- registers a `NewMessage(incoming=True)` handler, awaits forever
3. **teardown()** -- removes the event handler, logs stats

On each incoming event:

1. Wrap in `Event` envelope
2. Evaluate the filter tree (`evaluate(filters, event)`)
3. If passed, iterate over actions
4. For each action: check per-action filters, resolve processor chain, execute

## Adding a new job

Just add an entry to `~/.tlgr/jobs.yaml` and restart the daemon (or run
`tlgr job add` to open the file in your editor).

No code changes needed -- the Gateway engine handles any combination of
registered filters, processors, and actions.
