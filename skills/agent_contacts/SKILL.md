---
name: agent_contacts
description: "Manage Nostr agent contacts: add, list, remove, send encrypted DMs (NIP-17), and publish profile (Kind 0) and follow list (Kind 3) events."
version: "1.0.0"
category: "communication"
---

# Agent Contacts Skill

## Goal
Provide a contact list for Nostr agents with Redis persistence and Nostr protocol backup. Agents can be discovered, stored, managed, messaged, and made visible to others through standard Nostr event kinds.

## Description
This skill enables an agent to:

1. **Maintain a contact list** in Redis (`chronology:agents:*` keys) — add, list, remove agents
2. **Publish Follow List** (`Kind 3`) — announce which agents you follow to the network
3. **Publish Profile** (`Kind 0`) — make the agent visible with name, description, and picture
4. **Send encrypted DMs** (`Kind 1059` via NIP-17 Gift Wrap) — initiate private conversations

All operations are logged via the **Chronology** skill for full audit trail.

### Data Flow
```
Agent found via scan_agents.py
    │
    ▼
agent_contacts add --pubkey <hex> --name <alias>
    │
    ├──► agent_contacts_db.py  ──► Redis (chronology:agents:*)
    │
    ├──► nostr_publisher.py
    │       ├──► Signer: /sign (Kind 3) ──► Nostr Relays
    │       └──► Chronology log
    │
    └──► (optional) send-dm
            └──► Signer: /nip17_wrap (Kind 1059) ──► Nostr Relays
```

## Usage

### Add an agent to the contact list
```bash
execute_skill_script agent_contacts scripts/agent_contacts_cli.py add \
  --pubkey <64_char_hex> \
  --name my_agent_alias \
  --relays "wss://relay.damus.io,wss://nos.lol"
```

### List all known agents
```bash
execute_skill_script agent_contacts scripts/agent_contacts_cli.py list
```

### List agents as JSON (for programmatic use)
```bash
execute_skill_script agent_contacts scripts/agent_contacts_cli.py list --json
```

### Remove an agent
```bash
execute_skill_script agent_contacts scripts/agent_contacts_cli.py remove \
  --pubkey <64_char_hex>
```

### Send an encrypted DM (NIP-17 / Kind 1059)
```bash
execute_skill_script agent_contacts scripts/agent_contacts_cli.py send-dm \
  --pubkey <64_char_hex> \
  --message "Hello from bob_nostr_agent!"
```

### Set the agent's profile (Kind 0)
```bash
# Full profile
execute_skill_script agent_contacts scripts/agent_contacts_cli.py set-profile \
  --name "bob_nostr_agent" \
  --about "ROS 2 Nostr Agent – autonomous task scheduler" \
  --picture "https://example.com/avatar.png"

# Partial update (only set name)
execute_skill_script agent_contacts scripts/agent_contacts_cli.py set-profile \
  --name "bob_nostr_agent"
```

### Show current profile from relays
```bash
execute_skill_script agent_contacts scripts/agent_contacts_cli.py show-profile
```

## Parameters

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NOSTR_SIGNER_URL` | `http://nostr-signer:8080` | URL of the isolated Nostr signer service |
| `NOSTR_RELAYS` | `ws://localhost:8781,ws://localhost:8782` | Comma-separated Nostr relay URLs |
| `AGENT_CONTACTS_REDIS_HOST` | `localhost` (falls back to `CHRONO_REDIS_HOST`) | Redis host for contact persistence |
| `AGENT_CONTACTS_REDIS_PORT` | `6379` (falls back to `CHRONO_REDIS_PORT`) | Redis port |
| `AGENT_CONTACTS_REDIS_DB` | `0` (falls back to `CHRONO_REDIS_DB`) | Redis database index |
| `AGENT_CONTACTS_SET_KEY` | `chronology:agents:set` | Redis Set key for agent pubkeys |
| `AGENT_CONTACTS_HASH_PREFIX` | `chronology:agents:` | Redis Hash prefix for agent metadata |
| `AGENT_PROFILE_NAME` | `bob_nostr_agent` | Default profile name for Kind 0 |
| `AGENT_PROFILE_ABOUT` | `ROS 2 Nostr Agent – autonomous task scheduler` | Default profile about text |
| `AGENT_PROFILE_PICTURE` | _(empty)_ | Default profile picture URL |

### CLI Arguments

| Command | Argument | Required | Description |
|---------|----------|----------|-------------|
| `add` | `--pubkey` | Yes | 64-char hex public key of the agent |
| `add` | `--name` | No | Human-readable alias |
| `add` | `--relays` | No | Comma-separated relay URLs the agent uses |
| `list` | `--json` | No | Output raw JSON instead of table |
| `remove` | `--pubkey` | Yes | 64-char hex public key to remove |
| `send-dm` | `--pubkey` | Yes | Recipient's 64-char hex public key |
| `send-dm` | `--message` | Yes | Message text content |
| `set-profile` | `--name` | No | Display name |
| `set-profile` | `--about` | No | Short bio / description |
| `set-profile` | `--picture` | No | Profile picture URL |

## Requirements

- **Redis** — `nostr-redis` container running (shared with Chronology skill)
- **Nostr Signer Service** — `nostr-signer` container running (`POST /sign`, `POST /nip17_wrap`)
- **Nostr Relays** — At least one reachable relay for publishing events
- **Python packages**: `redis`, `nostr-sdk`, `nostr_memory` (local skill), `chronology` (local skill)

## Technical Details

### Redis Schema

| Key | Type | Purpose |
|-----|------|---------|
| `chronology:agents:set` | Set | All known agent pubkeys (hex), used for fast membership checks |
| `chronology:agents:{pubkey}` | Hash | `name`, `relays` (JSON array), `added_at`, `last_seen`, `last_dm_at` |

### Nostr Event Kinds

| Kind | NIP | Purpose | Content | Tags |
|------|-----|---------|---------|------|
| 0 | NIP-01 | Profile/Metadata | JSON `{name, about, picture, nip05}` | _(none)_ |
| 3 | NIP-02 | Contact List / Follows | JSON `{agent_contact_list: true}` | `["p", pubkey, relay_hint, name]` |
| 1059 | NIP-17 | Gift-Wrapped DM | Encrypted rumor (Kind 14) | `["p", receiver_pubkey]` |

### Integration

- **Chronology**: Every `add_agent`, `remove_agent`, and `send-dm` call logs a Chronology event with appropriate tags (`agent`, `contacts`, `dm`).
- **Signer Service**: All signing and encryption goes through the isolated `nostr_signer_service.py` via its HTTP API.
- **Relay Discovery**: The publisher automatically resolves relay URLs (container name ↔ host port mapping) using `NostrRelayManager.resolve_host_urls()`.

## Best Practices

- **Environment Variables**: Use `os.environ.get()` with sensible defaults for all external connections (Redis host/port, signer URL, relay URLs).
- **Central Configuration**: Keep these variables in the root `.env` file and update `.env.template`.
- **Idempotent Adds**: Adding the same agent twice is safe — `SADD` is idempotent, and the hash is simply updated.
- **Safety Guard**: `clear_all` (accessible programmatically) requires `force=True` to prevent accidental data loss.
