---
name: relay_discovery
description: "Scans Nostr relays to identify agents, test relay persistence, resolve geo-IP, manage relay index, and publish results to Nostr memory."
version: "2.0.0"
category: "research"
---

# Relay Discovery Skill

## Goal
Discover, test, and catalog Nostr relays and autonomous agents operating on the network. Results are stored locally and optionally published as Nostr memory.

## Description
This skill provides a comprehensive relay discovery toolkit:

1. **Agent Discovery** ([`scan_agents.py`](scripts/scan_agents.py)): Identifies autonomous agents via tag matching and frequency analysis
2. **Persistence Scanner** ([`scan_relays.py`](scripts/scan_relays.py)): Tests relay connectivity, event storage, retrievability, NIP-11 metadata, and classifies trust levels
3. **Geo-IP Resolution** ([`relay_geo.py`](scripts/relay_geo.py)): Resolves relay hostnames to geographic locations via ip-api.com
4. **Relay Index** ([`relay_index.py`](scripts/relay_index.py)): Loads, merges, saves, and queries the relay index (local YAML)
5. **Publish Results** ([`publish_discovery.py`](scripts/publish_discovery.py)): Stores scan results as relay-index or discovery-results Nostr memory

## Usage

### Agent Discovery
```bash
execute_skill_script relay_discovery scripts/scan_agents.py --limit 10 --timeout 45
```

### Relay Persistence Scan
```bash
# Scan all configured relays
execute_skill_script relay_discovery scripts/scan_relays.py --timeout 20

# Scan specific relays and save results
execute_skill_script relay_discovery scripts/scan_relays.py \
    --relays "wss://nos.lol,wss://relay.damus.io" \
    --output /tmp/scan_results.json
```

### Geo-IP Resolution
```bash
execute_skill_script relay_discovery scripts/relay_geo.py \
    wss://nos.lol wss://relay.damus.io

# Export as map markers
execute_skill_script relay_discovery scripts/relay_geo.py \
    wss://nos.lol --markers
```

### Relay Index Management
```bash
# Print summary
execute_skill_script relay_discovery scripts/relay_index.py summary

# List trusted relays
execute_skill_script relay_discovery scripts/relay_index.py trusted

# Merge scan results into index
execute_skill_script relay_discovery scripts/relay_index.py merge \
    --input /tmp/scan_results.json

# Export as map markers
execute_skill_script relay_discovery scripts/relay_index.py markers
```

### Publish Results to Nostr
```bash
# Pack scan results as relay-index memory type
execute_skill_script relay_discovery scripts/publish_discovery.py \
    --input /tmp/scan_results.json --compress gz

# Pack and publish to relays
execute_skill_script relay_discovery scripts/publish_discovery.py \
    --input /tmp/scan_results.json --compress gz --publish \
    --relays "wss://nos.lol,wss://relay.damus.io"
```

## Parameters

### `scripts/scan_agents.py`
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--limit` | integer | `10` | Maximum number of agents to identify |
| `--window` | integer | `10` | Time window (seconds) for frequency analysis |
| `--min-events` | integer | `3` | Minimum events in window to flag as agent |
| `--timeout` | integer | `45` | Scan timeout in seconds |

### `scripts/scan_relays.py`
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--relays` | string | from env | Comma-separated relay URLs |
| `--timeout` | int | `20` | Timeout per relay in seconds |
| `--retention-check` | flag | false | Run retention test (placeholder) |
| `--output` | string | stdout | Path for JSON result file |

### `scripts/relay_geo.py`
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `relay` | positional | required | One or more relay URLs to resolve |
| `--timeout` | int | `5` | Timeout per query in seconds |
| `--markers` | flag | false | Output in map-marker format |

### `scripts/relay_index.py`
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `command` | string | required | `list`, `merge`, `trusted`, `markers`, `summary` |
| `--trust` | string | none | Filter by trust level (list command) |
| `--online` | flag | false | Show only online relays (list command) |
| `--input` / `-i` | string | required | Input JSON file (merge command) |
| `--output` / `-o` | string | auto | Output path (merge command) |

### `scripts/publish_discovery.py`
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--input` / `-i` | string | required | Input JSON file |
| `--type` | string | `relay-index` | Memory type (`relay-index` or `discovery-results`) |
| `--compress` | string | `none` | Compression format (`none`, `gz`, `tar.gz`) |
| `--relays` | string | none | Relay URLs for publishing |
| `--publish` | flag | false | Publish to relays after packing |

## Trust Levels
| Level | Description |
|-------|-------------|
| `trusted` | Reliably stores and returns events, good uptime, free |
| `unstable` | Intermittent availability or unknown retention |
| `local` | Self-hosted relay instance |
| `paywalled` | Requires payment for access |
| `dead` | Unreachable or not responding |

## Discovery Workflow
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  scan_relays.py │───▶│  relay_index.py  │───▶│ publish_discov-  │
│  (persistence,  │    │  (merge, query,  │    │ ery.py          │
│   NIP-11, trust)│    │   export)        │    │ (Nostr storage)  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌─────────────────┐
│  relay_geo.py   │    │  journal_writer  │
│  (Geo-IP res.)  │    │  (relay status)  │
└─────────────────┘    └─────────────────┘
```

## Requirements
- Python 3.10+ with `nostr-sdk` and `pyyaml`
- Internet connectivity to target relays
- Access to `nostr_memory` skill for publishing (via `cli_agent_memory.py`)

## File Structure
```
skills/relay_discovery/
├── SKILL.md
├── scripts/
│   ├── scan_agents.py                # Agent discovery (tag + frequency)
│   ├── scan_relays.py                # Relay persistence scanner
│   ├── relay_geo.py                  # Geo-IP resolution
│   ├── relay_index.py                # Relay index management
│   └── publish_discovery.py          # Store results as Nostr memory
└── resources/
    └── default_relays.yaml           # Seed list of known relays
```
