---
name: chronology
description: "Persistent, tagged event log for recording and querying chronological events via Redis."
version: "1.0.0"
category: system
---

# Chronology Skill

## Goal

Provide a persistent, Redis-backed event diary that records structured, tagged events so that agents and users can always reconstruct what happened — even after container restarts, scheduler resets, or system reboots.

## Description

The `chronology` skill stores every notable occurrence as a **structured event** in Redis, tagged with arbitrary labels for fast filtering. It is designed for parallel agents: multiple processes can safely write to the same Redis stream without conflicts thanks to Redis Streams' inherent concurrency guarantees.

Each event contains:

| Field       | Description                                        |
|-------------|----------------------------------------------------|
| `id`        | Auto-generated Redis Stream ID (≈ timestamp)       |
| `timestamp` | Human-readable ISO-8601 timestamp                  |
| `message`   | Free-text description of what happened             |
| `level`     | Severity: `DEBUG`, `INFO`, `WARN`, `ERROR`         |
| `tags`      | Comma-separated list of labels (e.g. `scheduler,agent`) |
| `source`    | Name of the component/agent that logged the event  |

## Usage

### As a CLI tool

```bash
# Log an event
python3 scripts/chronology_cli.py log \
  --message "Scheduler executed task cleanup" \
  --tags scheduler,cleanup \
  --level INFO \
  --source my_agent

# Query recent events (default: last 10)
python3 scripts/chronology_cli.py query --limit 20

# Query by tag
python3 scripts/chronology_cli.py query --tags scheduler --limit 10

# Query by time range
python3 scripts/chronology_cli.py query \
  --since "2026-06-14 12:00:00" \
  --until "2026-06-14 18:00:00"

# Query by level
python3 scripts/chronology_cli.py query --level ERROR

# Combined filter
python3 scripts/chronology_cli.py query \
  --tags scheduler \
  --level WARN \
  --limit 5

# Show stats
python3 scripts/chronology_cli.py stats

# Clear all events (with confirmation)
python3 scripts/chronology_cli.py clear --force
```

### As a Python module

```python
from chronology_engine import ChronologyEngine

engine = ChronologyEngine()

# Log
engine.log_event("Scheduler executed task cleanup",
                 tags=["scheduler", "cleanup"],
                 level="INFO",
                 source="my_agent")

# Query
events = engine.query_events(tags=["scheduler"], limit=10)

# Stats
stats = engine.get_stats()
print(stats)
```

### From execute_skill_script

```
execute_skill_script("chronology", "scripts/chronology_cli.py",
                     "log --message 'Task started' --tags scheduler --level INFO")
```

## Parameters

### Environment Variables (all prefixed with `CHRONO_`)

| Variable                | Default          | Description                              |
|-------------------------|------------------|------------------------------------------|
| `CHRONO_REDIS_HOST`     | `nostr-redis`    | Redis server hostname                    |
| `CHRONO_REDIS_PORT`     | `6379`           | Redis server port                        |
| `CHRONO_REDIS_DB`       | `0`              | Redis database number                    |
| `CHRONO_STREAM_KEY`     | `chronology:events` | Redis Stream key for events           |
| `CHRONO_MAX_EVENTS`     | `10000`          | Maximum events before trimming           |
| `CHRONO_TTL_HOURS`      | `0`              | Auto-expire events after N hours (0=off) |
| `CHRONO_TRIM_ON_LOG`    | `true`           | Trim old events on each log write        |

### CLI Arguments

| Argument          | Alias | Description                    |
|-------------------|-------|--------------------------------|
| `--message`, `-m` |       | Event message (log command)    |
| `--tags`, `-t`    |       | Comma-separated tags           |
| `--level`, `-l`   |       | Severity level                 |
| `--source`, `-s`  |       | Source component name          |
| `--since`         |       | ISO-8601 start time (query)    |
| `--until`         |       | ISO-8601 end time (query)      |
| `--limit`         | `-n`  | Max results (query, default 10)|
| `--force`         |       | Skip confirmation (clear)      |

## Requirements

- **Redis server** running (see [`compose-redis.yaml`](../../docker/compose-redis.yaml))
- Python 3.10+
- `redis` Python package (`pip install redis`)

## Technical Details

- **Storage**: Redis Streams (`XADD`, `XRANGE`, `XLEN`, `XTRIM`) for the event log.
- **Tag Indexing**: Redis Sets per tag (`chronology:tags:<tagname>`) containing event IDs for fast intersection/union queries.
- **Concurrency**: Redis Streams support multiple writers with auto-generated sequential IDs — no locking needed.
- **Persistence**: The Redis container is configured with AOF (append-only file) and periodic RDB snapshots. Data is persisted to `/volume1/ros/nostr_agent/redis`.
- **Data Flow**:
  1. `log_event()` → `XADD chronology:events * field1 val1 ...` → add event IDs to tag Sets via `SADD`.
  2. `query_events()` → if tags specified, `SINTER` tag Sets to get candidate IDs → fetch from Stream; else use `XRANGE` for time-range or `XREVRANGE` for recent.
  3. `trim_events()` → `XTRIM chronology:events MAXLEN ~ <max>` to keep size bounded.

## Best Practices

- **Tags are the primary filter mechanism** — always tag events with the agent name, task type, and context.
- **Use sensible levels**: `INFO` for normal operations, `WARN` for recoverable issues, `ERROR` for failures, `DEBUG` for verbose traces.
- **Set `CHRONO_MAX_EVENTS`** to a value appropriate for your expected event volume and retention requirements.
- **The CLI supports piping** — `chronology_cli.py query --limit 100 | grep error` works for ad-hoc analysis.
