---
name: journal
description: "Creates structured agent journal files locally. Does NOT use nostr-sdk or implement task scheduling – Nostr publishing is delegated to nostr_memory, scheduling to the future task_scheduler skill."
version: "1.0.0"
category: "journal"
---

# Journal Skill

## Goal
Generate structured, timestamped markdown journal entries capturing the agent's current system state. Journals are saved locally and can optionally be published to Nostr relays via the [`nostr_memory`](../nostr_memory/) skill.

## Description
This skill provides tools for creating and managing local journal files. It does **NOT**:

- ❌ Use `nostr-sdk` directly
- ❌ Implement any task scheduling (cron, timers, triggers)
- ❌ Publish to Nostr relays on its own

Instead, it focuses solely on local journal creation and retention management. Publishing to Nostr is delegated to the [`nostr_memory`](../nostr_memory/) skill's serialized mode (`cli_agent_memory.py`).

## Usage

### 1. Create a journal entry with system data collection

```bash
execute_skill_script journal scripts/journal_writer.py \
    --output-dir /home/ros/agent/journal/ --collect
```

### 2. Create a journal entry without collection (manual data only)

```bash
execute_skill_script journal scripts/journal_writer.py \
    --output-dir /home/ros/agent/journal/ \
    --agent-status "debugging relay connectivity" \
    --model "deepseek-v4-pro"
```

### 3. List local journal files

```bash
execute_skill_script journal scripts/journal_retention.py list \
    --directory /home/ros/agent/journal/
```

### 4. Clean old journal files (remove > 30 days)

```bash
execute_skill_script journal scripts/journal_retention.py clean \
    --directory /home/ros/agent/journal/ --max-age 30
```

### 5. Archive old journals before removal

```bash
execute_skill_script journal scripts/journal_retention.py clean \
    --directory /home/ros/agent/journal/ --max-age 30 --archive
```

### 6. Dry-run cleanup (see what would be removed)

```bash
execute_skill_script journal scripts/journal_retention.py clean \
    --directory /home/ros/agent/journal/ --max-age 30 --dry-run
```

## Parameters

### `scripts/journal_writer.py`
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--output-dir` | string | `journal/` | Directory for journal files |
| `--template` | string | built-in | Path to custom template file |
| `--collect` | flag | false | Collect system data automatically (ROS 2, Docker, relays, uptime, memory) |
| `--recent-actions-file` | string | none | Path to recent actions log file |
| `--error-file` | string | none | Path to error log file |
| `--model` | string | `LLM_MODEL` env | Model info string |
| `--agent-status` | string | `operational` | Agent status description |

### `scripts/journal_retention.py`
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `command` | string | required | `list` or `clean` |
| `--directory` | string | `journal/` | Directory containing journal files |
| `--max-age` | int | `30` | Maximum age in days before removal (clean command) |
| `--archive` | flag | false | Create tar.gz archive of old journals before removal |
| `--dry-run` | flag | false | Show what would be deleted without actually removing |

## Journal Publishing Workflow

The journal skill itself never publishes to Nostr. To publish a journal, use the nostr_memory skill:

```bash
# Step 1: Create journal locally
execute_skill_script journal scripts/journal_writer.py \
    --output-dir /home/ros/agent/journal/ --collect

# Step 2: Pack with compression
execute_skill_script nostr_memory scripts/cli_agent_memory.py \
    encode session-journal \
    --input /home/ros/agent/journal/20260613_140000_agent_journal.md \
    --output /tmp/packed.json --compress gz

# Step 3: Publish to relays
execute_skill_script nostr_memory scripts/cli_agent_memory.py \
    publish --input /tmp/packed.json \
    --relays "wss://nos.lol,wss://relay.snort.social,wss://relay.damus.io"
```

## Requirements
- Python 3.10+
- Access to ROS 2 CLI tools (optional, for system data collection)
- Docker CLI (optional, for container status)
- No `nostr-sdk` dependency – this skill is nostr-sdk free

## Technical Details

### Data Collection (--collect flag)
When `--collect` is specified, the writer gathers:
- Active ROS 2 nodes and topics (`ros2 node list`, `ros2 topic list`)
- Running Docker containers (`docker ps`)
- Relay status via [`nostr_relay_manager.py`](../nostr_memory/scripts/nostr_relay_manager.py) (if available)
- System uptime (`uptime -p` or `/proc/uptime`)
- Memory usage (`free -m`)
- Recent actions log contents (if `--recent-actions-file` provided)
- Error log contents (if `--error-file` provided)

### Journal Storage on Nostr
Journals are stored as `session-journal` memory type (defined in [`memory_spec.yaml`](../nostr_memory/resources/memory_spec.yaml)):
```yaml
- name: session-journal
  kind: 30001
  serializable: true
  content_format: markdown
  visibility: encrypted
  d_tag: "agent:journal:{date}"
  t: "sjl"
```

### Task Scheduling (Future)
This skill deliberately excludes scheduling logic. A future `task_scheduler` skill will:
- Call `journal_writer.py` at configurable intervals
- Call `cli_agent_memory.py encode` + `publish` after each journal
- Handle session-end events and error conditions

## File Structure
```
skills/journal/
├── SKILL.md
├── scripts/
│   ├── journal_writer.py      # Creates journal markdown files
│   └── journal_retention.py   # Manages local journal retention
└── resources/
    └── journal_template.md    # Template for journal entries
```
