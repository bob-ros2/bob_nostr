---
name: nostr_memory
description: "Decentralized, censorship-resistant long-term memory for the agent via the Nostr protocol. Supports simple single-event storage and serialized multi-event storage with compression, NIP-44 encryption, tag obfuscation, and type registry."
version: "3.0.0"
category: "memory"
---

# Nostr Memory Skill

## Goal
Establish a persistent, censorship-resistant, and decentralized memory for the agent based on the Nostr protocol. Two operation modes are available: **simple** single-event storage and **serialized** multi-event storage for large data.

## Description
This skill provides all Nostr-based memory operations in one unified skill. It replaces the need for traditional databases (Redis, CouchDB, Qdrant) with a cryptographically verifiable, decentralized storage system built on Nostr relays.

### Simple Mode (`nostr_memory_tool.py`)
Store, retrieve, search, and delete single Nostr events with NIP-44 encryption. Ideal for small, structured data like agent state, configs, and short memories. All events are signed by the isolated signer service and distributed to multiple relays for redundancy.

### Serialized Mode (`cli_agent_memory.py`)
For large data exceeding single-event limits, this mode encodes data across multiple Nostr events using Header events (Kind 30001) and Chunk events (Kind 30002). Features include:
- **Type registry**: Memory types defined in [`resources/memory_spec.yaml`](resources/memory_spec.yaml) (`relay-index`, `session-journal`, `agent-config`)
- **Obfuscation**: Deterministic SHA-256 tag hashing for privacy
- **Compression**: gzip and tar.gz support (see Phase 2)
- **Chunking**: Splits large payloads into configurable chunks with reassembly

Both modes share the same isolated signer ([`nostr_signer_service.py`](scripts/nostr_signer_service.py)). The [`signer.py`](scripts/signer.py) HTTP client is used by the serialized mode, while the simple mode uses `nostr-sdk`'s built-in client.

## Usage

### Simple Mode

#### 1. Start relays (Docker Compose) - Only if consciously decided manually!
Relays are started externally using Docker Compose. For example, run:
```bash
docker compose -f docker/compose-nostr.yaml up -d
```

#### 2. Store memory
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action store --kind 5000 --content '{"topic": "evolution_plan", "data": "...", "tags": ["nostr", "memory"]}'
```

#### 3. Retrieve memory (by ID)
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action get --event-id <hex_event_id>
```

#### 4. Search memories
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action search --kind 5000 --limit 10
```

#### 5. Enhanced search with filters
```bash
# Search only own events (agent as author)
execute_skill_script nostr_memory scripts/nostr_memory_tool.py \
    --action search --kind 5000 --authors "<agent_pubkey_hex>" --limit 20

# Search events in a time window
execute_skill_script nostr_memory scripts/nostr_memory_tool.py \
    --action search --kind 30001 --since 1718208000 --until 1718294400 --limit 50

# Search events with specific tags
execute_skill_script nostr_memory scripts/nostr_memory_tool.py \
    --action search --kind 30001 --tag-filter '[["t","sjl"],["h","<session_id>"]]' --limit 10
```

#### 6. Store agent status (replaceable)
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action set_status --data '{"mood": "operational", "uptime": 3600}'
```

#### 7. Retrieve status
```bash
execute_skill_script nostr_memory scripts/nostr_memory_tool.py --action get_status
```

#### 8. Check relay status
```bash
execute_skill_script nostr_memory scripts/nostr_relay_manager.py --action status
```

### Serialized Mode

#### Encode data into Nostr events
```bash
execute_skill_script nostr_memory scripts/cli_agent_memory.py \
    encode session-journal --input /tmp/journal.md --output /tmp/packed.json --compress gz
```

#### Decode Nostr events back into data
```bash
execute_skill_script nostr_memory scripts/cli_agent_memory.py \
    decode --input /tmp/packed_events.json --output /tmp/decoded.yaml
```

#### List available memory types
```bash
execute_skill_script nostr_memory scripts/cli_agent_memory.py list-types
```

#### Publish packed events to relays
```bash
execute_skill_script nostr_memory scripts/cli_agent_memory.py \
    publish --input /tmp/packed.json --relays "wss://nos.lol,wss://relay.snort.social"
```

## Parameters

### `scripts/nostr_memory_tool.py` (Simple Mode)
| Argument | Type | Default | Description |
|----------|-----|----------|--------------|
| `--action` | string | (required) | Execute action: `store`, `get`, `search`, `delete`, `set_status`, `get_status`, `list_keys` |
| `--kind` | int | `1` | Nostr Event Kind (1=Text, 5000=Memory, 30000=Status) |
| `--content` | string | `""` | JSON string or text content of the event |
| `--event-id` | string | `""` | Hex event ID to retrieve a specific event |
| `--tags` | string | `""` | Comma-separated tags |
| `--limit` | int | `10` | Maximum number of return results during search |
| `--since` | int | `0` | Unix timestamp – only events newer than this |
| `--until` | int | `0` | Unix timestamp – only events older than this |
| `--authors` | string | `""` | Comma-separated hex pubkeys of authors |
| `--tag-filter` | string | `""` | JSON array of tag filters, e.g. `'[["t","ros2"],["d","agent_state"]]'` |
| `--relays` | string | (env) | Comma-separated relay URLs (override) |
| `--encrypt` | flag | | Force NIP-44 encryption of the content (overrides default) |
| `--no-encrypt` | flag | | Force unencrypted plain text storage of the content (overrides default) |

### `scripts/cli_agent_memory.py` (Serialized Mode)
| Argument | Type | Default | Description |
|----------|-----|----------|--------------|
| `--action` / `<command>` | string | required | `encode`, `decode`, `list-types`, `publish` |
| `type` | string | required (encode) | Memory type name (`relay-index`, `session-journal`, `agent-config`) |
| `--input` / `-i` | string | required | Input file path |
| `--output` / `-o` | string | auto | Output file path |
| `--compress` | string | `none` | Compression format: `none`, `gz`, `tar.gz` |
| `--relays` | string | from env | Comma-separated relay URLs for publishing |

### `scripts/nostr_relay_manager.py`
| Argument | Type | Default | Description |
|----------|-----|----------|--------------|
| `--action` | string | `status` | Action to execute: `status` or `test` (both check connectivity) |

## Requirements
- Python 3.10+ with `nostr-sdk` (`pip install nostr-sdk`)
- `pyyaml` for YAML serialization
- Access to reachable Nostr relays configured via the `NOSTR_RELAYS` environment variable
- Isolated signer service at `NOSTR_SIGNER_URL` (recommended)

## Technical Details

### Architecture
```
┌───────────────┐     WebSocket      ┌──────────────────┐
│  nostr_client │ ──────────────────►│  Relay 1 (ws://)  │
│  (Agent)      │                    │  Port 8781        │
│               │ ──────────────────►├──────────────────┤
│  SKILL.md     │                    │  Relay 2 (ws://)  │
│  scripts/     │ ──────────────────►│  Port 8782        │
└───────────────┘                    └──────────────────┘
         │
         │ HTTP (sign/encrypt/decrypt)
         ▼
┌───────────────────┐
│  nostr-signer     │
│  (isolated)       │
└───────────────────┘
```

### Event Kinds Used
| Kind | Name | Usage |
|------|-------------|------------|
| 1 | Text Note | General memories, journals (always plaintext by default) |
| 1984 | Reporting | Error reports, system logs (encrypted by default) |
| 30000 | Replaceable | Agent state (encrypted by default) |
| 30001 | Header | Serialized memory header (type registry) |
| 30002 | Chunk | Serialized memory chunk |
| 5000–5999 | Custom (Agent Memories) | Structured memories (encrypted by default) |
| 5 | Deletion | Deletes a previously sent event |

### Memory Types (from memory_spec.yaml)
| Name | Kind | Serializable | Visibility | Format |
|------|------|-------------|------------|--------|
| relay-index | 30001 | true | encrypted | yaml |
| session-journal | 30001 | true | encrypted | markdown |
| agent-config | 30001 | false | encrypted | yaml |
| discovery-results | 30001 | true | encrypted | yaml |

### Serialization Pipeline
1. Content is serialized (YAML/JSON/Markdown) based on the memory type's `content_format`
2. Content is NIP-44 encrypted via the isolated signer
3. Tags are generated, optionally obfuscated via SHA-256 hashing
4. If content exceeds `chunk_size`, it is split into multiple events:
   - **Header event** (Kind 30001): Contains type, total chunks, session UUID, format, encryption status
   - **Chunk events** (Kind 30002): Each contains a Base64-encoded chunk with sequence number

### Key Management
Each agent has its own secp256k1 key pair:
- **Private Key (nsec/hex)**: Stored in the signer container environment (`NOSTR_AGENT_SECRET`)
- **Public Key (npub/hex)**: Derived from the secret – the identity of the agent

#### Isolated Key Protection (Recommended)
To prevent the LLM agent from accidentally leaking or exposing its own private key, run an isolated signing container (`nostr-signer` service):
1. The private key (`NOSTR_AGENT_SECRET`) is stored in `.env.signer` and loaded **only** by the `nostr-signer` container
2. The agent container does **not** have the private key in its environment. Instead, it has `NOSTR_SIGNER_URL=http://nostr-signer:8080`
3. When the agent needs to save or sign an event, it calls the `nostr-signer` microservice via HTTP to perform the signing

This completely isolates the private key from the main LLM-facing process.

### Multi-Relay Strategy
The client sends each event to **all configured relays** (default: 2 local relays). When reading, the first relay that responds is used as the source. Fallback: If a timeout occurs, the next relay is queried.

## Best Practices
- **Environment Variables**: Use `os.environ.get()` for all external connections (API-URLs, paths). All relay URLs come from `NOSTR_RELAYS`, signer URL from `NOSTR_SIGNER_URL`.
- **Central Configuration**: Keep these variables in the root `.env` file and update `.env.template`. The signer secret stays in `.env.signer`.
- **Always write to all relays**: Only this ensures true redundancy.
- **Replaceable Events for status**: Kind 30000 for states, Kind 5000+ for historical data.
- **Use tags for metadata**: Tags like `["t", "ros2"]` allow granular search.
- **Key security**: Run the isolated `nostr-signer` container to protect the private key.
- **Relay disk space**: By default, `relayd` containers store indefinitely. Reset volumes if needed via `--action clean`.
- **Compression guideline**: Use `--compress gz` for data >10KB; `--compress tar.gz` for directories.
