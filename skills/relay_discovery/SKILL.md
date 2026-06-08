---
name: relay_discovery
description: "Scans Nostr relays to identify and catalog other autonomous agents."
version: "1.1.0"
category: "research"
---

# Relay Discovery Skill

## Goal
To automatically identify, categorize, and store the public keys of other autonomous agents or bots operating on the Nostr network.

## Description
This skill performs an active scan of a list of Nostr relays configured via environment variables. It monitors incoming event streams for two primary signals:
1. **Tag Matching**: Identification of events containing specific tags (e.g., `agent`, `bot`, `ai`).
2. **Frequency Analysis**: Detection of high-frequency event patterns (e.g., status updates) that characterize machine-driven behavior.

Identified agents are outputted to stdout in JSON format, allowing the caller to store them in the decentralized memory (`nostr_memory`) for future interaction.

## Usage
Execute the skill script using the `execute_skill_script` tool:

```json
execute_skill_script({
  "skill_name": "relay_discovery",
  "script_path": "scripts/scan_agents.py",
  "args": "--limit 10 --timeout 45"
})
```

## Parameters

### `scripts/scan_agents.py`
| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--limit` | integer | `10` | Maximum number of agents to identify in one run. |
| `--window` | integer | `10` | Time window (seconds) for frequency analysis. |
| `--min-events` | integer | `3` | Minimum events in window to flag as agent. |
| `--timeout` | integer | `45` | Scan timeout in seconds. |

## Requirements
- **Nostr SDK**: Must have `nostr-sdk` installed.
- **Relay Access**: Requires connectivity to the relays defined in the `.env` file (`EXTERNAL_NOSTR_RELAYS` or `NOSTR_RELAYS`).

## Technical Details
- **Multi-Relay Connection**: Connects to the configured relays and listens to Kind 1 events.
- **Frequency Logic**: Uses a sliding window to track event counts per pubkey.
