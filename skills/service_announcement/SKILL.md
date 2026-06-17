---
name: service_announcement
description: "NIP-89 Service Announcement — register, list, discover Nostr services as Kind 31990 events, and handle DM-to-service routing."
version: "1.0.0"
category: "communication"
---

# Service Announcement Skill (NIP-89)

## Goal
Enable the agent to announce its capabilities as discoverable Nostr services (NIP-89 Kind 31990), discover services from other agents, and provide DM-based help for users.

## Description
This skill implements the [NIP-89](https://github.com/nostr-protocol/nips/blob/master/89.md) specification for service announcements. It provides:

1. **`register`** — Publish a Kind 31990 event advertising a service the agent offers
2. **`list`** — Retrieve the agent's own published service announcements from relays
3. **`discover`** — Query relays for services published by other Nostr agents
4. **DM Routing Help** — Parse incoming DM content and map it to the appropriate skill

### Service-to-Skill Mapping
| Service Identifier | DM Command | Skill |
|---|---|---|
| `agent.bob/relay-scan` | `scan_relay <url>` | `relay_discovery` |
| `agent.bob/web-research` | `search_web <query>` | `web_researcher` |
| `agent.bob/journal-service` | `journal <topic>` | `journal` |
| `agent.bob/memory-backup` | `backup <kind>` | `nostr_memory` |
| `agent.bob/task-reminder` | `remind <text>` | `task_scheduler` |
| `agent.bob/code-execute` | `run <code>` | `repl_kernel` / `core_coder` |

## Usage

### Register a service
```bash
execute_skill_script service_announcement scripts/service_announcement_cli.py register \
  --id "agent.bob/relay-scan" \
  --title "Relay Scanner" \
  --description "Scan Nostr relays and produce a catalog" \
  --alt "Send a DM with: scan_relay wss://<relay-url>" \
  --relays "wss://relay.damus.io,wss://nos.lol"
```

### List my services
```bash
execute_skill_script service_announcement scripts/service_announcement_cli.py list
```

### Discover services from other agents
```bash
execute_skill_script service_announcement scripts/service_announcement_cli.py discover \
  --search "relay" --limit 10
```

### DM help (what LLM calls to show available services)
```bash
execute_skill_script service_announcement scripts/handle_dm.py help
```

### Parse a DM and identify the requested service
```bash
execute_skill_script service_announcement scripts/handle_dm.py parse \
  --dm "scan_relay wss://example.relay"
```

## Parameters

### `service_announcement_cli.py`

| Argument | Type | Default | Description |
|---|---|---|---|
| `<command>` | string | required | `register`, `list`, `discover` |
| `--id` / `-i` | string | (required for register) | Unique service identifier (e.g. `agent.bob/relay-scan`) |
| `--title` | string | (required for register) | Human-readable service title |
| `--description` | string | `""` | Detailed description of the service |
| `--alt` | string | `""` | Alternative text — what users should DM the agent |
| `--relays` | string | (from env) | Comma-separated relay URLs for the announcement |
| `--search` | string | `""` | Filter word for discover command |
| `--limit` | int | `10` | Max results for discover |

### `handle_dm.py`

| Argument | Type | Default | Description |
|---|---|---|---|
| `<command>` | string | required | `help`, `parse` |
| `--dm` | string | (required for parse) | The DM text content to parse |

## Requirements
- `NOSTR_SIGNER_URL` — URL of the isolated Nostr signer service
- `NOSTR_RELAYS` — Comma-separated relay URLs
- Python 3.10+ with `nostr-sdk` and `pyyaml`

## Technical Details

### NIP-89 Event Format (Kind 31990)

```json
{
  "kind": 31990,
  "content": "{\"name\": \"Relay Scanner\", \"description\": \"...\"}",
  "tags": [
    ["d", "agent.bob/relay-scan"],
    ["title", "Relay Scanner"],
    ["description", "Scan Nostr relays and produce a catalog"],
    ["alt", "Send a DM with: scan_relay wss://<relay-url>"],
    ["relays", "wss://relay.damus.io"],
    ["p", "<agent_pubkey>"]
  ]
}
```

### Flow

```
LLM receives DM "scan_relay wss://x"
  │
  ├──► handle_dm.py parse "scan_relay wss://x"
  │       → {"service": "agent.bob/relay-scan", "skill": "relay_discovery", "args": "wss://x"}
  │
  └──► LLM calls scan_relays.py --relays "wss://x"
          → Ergebnis als DM zurück an User
```

### Signer Integration
All Kind 31990 events are signed via the isolated `nostr-signer` service at `NOSTR_SIGNER_URL`, using the same `/sign` endpoint as other event kinds.

## Best Practices
- **Register services on startup** — use `task_scheduler` to call `register` at agent boot
- **Keep descriptions concise** — Content field has Nostr event size limits
- **Use `alt` text** — This tells users exactly what to DM
- **Service IDs should be unique** — Use reverse domain notation: `agent.bob/<service-name>`
