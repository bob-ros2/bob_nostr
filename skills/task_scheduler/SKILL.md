---
name: task_scheduler
description: "Cron, interval, and one-shot task scheduler for periodic skill execution. Manages task lifecycle (add, suspend, resume, remove) with JSON-file persistence."
version: "1.0.0"
category: "system"
---

# Task Scheduler Skill

## Goal

Provide a persistent, autonomous scheduling layer that executes registered skill scripts at configurable times (cron, interval, one-shot). The scheduler runs as a background daemon and exposes CLI tools for the LLM agent to manage tasks at runtime.

## Description

The `task_scheduler` skill uses **APScheduler** (AsyncIOScheduler) to manage three trigger types:

| Trigger | Description |
|---|---|
| `cron` | Standard 5-field cron expression (`minute hour day month day_of_week`) |
| `interval` | Execute every N seconds |
| `once` | Execute at a specific date/time (ISO 8601) |

All task definitions are persisted in a **single JSON file** (path configurable via environment variable). A file-watcher loop polls for external changes, allowing the LLM to add/remove tasks via the tool API without restarting the daemon.

### Execution Model

When a task fires, the scheduler calls `subprocess.run()` on the target skill's script:

```
python3 /ros2_ws/src/bob_nostr/skills/{skill_name}/{script_path} {arguments}
```

The scheduler looks for the script in two locations (checked in order):
1. `/ros2_ws/src/bob_nostr/skills/{skill_name}/{script_path}` (core skills)
2. `/home/ros/agent/skills/{skill_name}/{script_path}` (custom skills)

Exit code `0` records `last_result = "success"`; any non-zero exit records `"failure"`. The scheduler never crashes on task execution failure — errors are logged and the scheduler continues running.

## Architecture (ROS 2 Integration)

The scheduler core lives in the ROS 2 Python sub-package [`bob_nostr/task_scheduler/`](../../bob_nostr/task_scheduler/):

```
ros2_ws/src/bob_nostr/
├── bob_nostr/
│   ├── setup.cfg                       # console_scripts: task_scheduler entry point
│   └── task_scheduler/                 # ROS sub-package (core implementation)
│       ├── __init__.py
│       ├── config.py                   # Pydantic settings (env vars)
│       ├── scheduler.py                # APScheduler core engine + file watcher
│       ├── storage.py                  # TaskConfig model + JSON persistence
│       ├── tools.py                    # CLI tool API (add/list/remove/suspend/resume/status)
│       ├── scripts/
│       │   └── run_scheduler.py        # Daemon entry point (signal handling)
│       └── resources/
│           └── tasks_default.json      # Optional default tasks on first start
└── skills/
    └── task_scheduler/                 # Skill stub (for agent harness)
        ├── SKILL.md                    # This file – documentation & tool API
        └── scripts/
            └── tools.py                # Thin wrapper → delegates to ROS package
```

The daemon is launched as a ROS executable:

```bash
ros2 run bob_nostr task_scheduler           # start daemon
ros2 run bob_nostr task_scheduler --status  # print status
```

The skill folder contains only the [`SKILL.md`](SKILL.md) and a thin [`scripts/tools.py`](scripts/tools.py) wrapper that delegates to the ROS-installed version.

## Environment Variables (Parameters)

All configuration is driven by environment variables with sensible defaults, following the [TEMPLATE_SPEC.md](../TEMPLATE_SPEC.md) specification.

| Variable | Default | Description |
|---|---|---|
| `SCHEDULER_TASKS_FILE` | `/home/ros/agent/scheduler/tasks.json` | Path to the JSON file containing all task definitions |
| `SCHEDULER_TIMEZONE` | `Europe/Berlin` | IANA timezone for cron expression evaluation |
| `SCHEDULER_POLL_INTERVAL` | `30` | File-watcher polling interval in seconds (minimum 5) |
| `SCHEDULER_LOG_FILE` | `/home/ros/agent/scheduler/scheduler.log` | Path to the scheduler daemon log file |
| `SCHEDULER_PID_FILE` | `/home/ros/agent/scheduler/scheduler.pid` | Path to the PID file for daemon lifecycle |

These variables can be set in the root `.env` file and should be added to `.env.template`.

> **Note on persistence**: The default `tasks_file` path (`/home/ros/agent/scheduler/tasks.json`) is on a writable bind-mounted volume, ensuring tasks survive container restarts. The skill code itself resides in the read-only core skills directory.

## Usage

All interactions go through `execute_skill_script()`:

```bash
execute_skill_script task_scheduler scripts/tools.py add \
    --task-id weekly_journal \
    --skill-name journal \
    --script-path scripts/journal_writer.py \
    --trigger-type cron \
    --trigger-value "0 */6 * * *" \
    --arguments "--collect" \
    --tags "journal,periodic"
```

### Tool API Reference

#### `add` – Create or update a task

```bash
execute_skill_script task_scheduler scripts/tools.py add \
    --task-id <ID> \
    --skill-name <SKILL> \
    --trigger-type cron|interval|once \
    --trigger-value <VALUE> \
    [--script-path <PATH>] \
    [--arguments <ARGS>] \
    [--enabled true|false] \
    [--tags <TAG1,TAG2>]
```

| Argument | Required | Description |
|---|---|---|
| `--task-id` | yes | Unique identifier for the task |
| `--skill-name` | yes | Name of the skill folder (e.g. `journal`, `nostr_memory`) |
| `--trigger-type` | yes | One of `cron`, `interval`, `once` |
| `--trigger-value` | yes | Cron expression (`"0 */6 * * *"`), seconds (`"3600"`), or ISO datetime (`"2026-06-15T08:00:00"`) |
| `--script-path` | no | Relative script path (e.g. `scripts/journal_writer.py`). Default empty means the script is inferred. |
| `--arguments` | no | CLI arguments passed to the script (e.g. `"--collect"`) |
| `--enabled` | no | `true` (default) or `false` |
| `--tags` | no | Comma-separated tags for filtering (e.g. `"journal,periodic"`) |

**Example – journal every 6 hours:**
```bash
execute_skill_script task_scheduler scripts/tools.py add \
    --task-id journal_6h \
    --skill-name journal \
    --script-path scripts/journal_writer.py \
    --trigger-type cron \
    --trigger-value "0 */6 * * *" \
    --arguments "--collect" \
    --tags "journal"
```

**Example – nostr memory backup daily:**
```bash
execute_skill_script task_scheduler scripts/tools.py add \
    --task-id daily_backup \
    --skill-name nostr_memory \
    --script-path scripts/cli_agent_memory.py \
    --trigger-type cron \
    --trigger-value "0 2 * * *" \
    --arguments "publish --input /tmp/backup.json" \
    --tags "backup"
```

**Example – one-shot task in 5 minutes:**
```bash
execute_skill_script task_scheduler scripts/tools.py add \
    --task-id once_cleanup \
    --skill-name journal \
    --script-path scripts/journal_retention.py \
    --trigger-type once \
    --trigger-value "now+300" \
    --arguments "clean --max-age 30"
```

#### `list` – List all registered tasks

```bash
execute_skill_script task_scheduler scripts/tools.py list
execute_skill_script task_scheduler scripts/tools.py list --filter-enabled true
execute_skill_script task_scheduler scripts/tools.py list --filter-tag journal
```

**Response:**
```json
{
  "status": "ok",
  "count": 2,
  "tasks": [
    {
      "task_id": "journal_6h",
      "skill_name": "journal",
      "trigger_type": "cron",
      "trigger_value": "0 */6 * * *",
      "enabled": true,
      "last_run": null,
      "last_result": null,
      "tags": ["journal"]
    }
  ]
}
```

#### `get` – Show details of a single task

```bash
execute_skill_script task_scheduler scripts/tools.py get --task-id journal_6h
```

#### `remove` – Delete a task permanently

```bash
execute_skill_script task_scheduler scripts/tools.py remove --task-id journal_6h
```

#### `suspend` – Disable a task (keep configuration)

```bash
execute_skill_script task_scheduler scripts/tools.py suspend --task-id journal_6h
```

#### `resume` – Re-enable a suspended task

```bash
execute_skill_script task_scheduler scripts/tools.py resume --task-id journal_6h
```

#### `status` – Check if the scheduler daemon is running

```bash
execute_skill_script task_scheduler scripts/tools.py status
```

**Response:**
```json
{
  "status": "ok",
  "scheduler": {
    "running": true,
    "uptime_seconds": 12345,
    "apscheduler_jobs": 3,
    "timezone": "Europe/Berlin",
    "tasks_file": "/home/ros/agent/scheduler/tasks.json"
  }
}
```

## Files

```
skills/task_scheduler/
├── SKILL.md                  # This file – documentation & tool API
└── scripts/
    └── tools.py              # Thin wrapper → delegates to ROS-installed bob_nostr.task_scheduler.tools
```

```
/ros2_ws/src/bob_nostr/bob_nostr/task_scheduler/   (ROS sub-package – core implementation)
├── __init__.py
├── config.py
├── scheduler.py
├── storage.py
├── tools.py
├── scripts/
│   └── run_scheduler.py
└── resources/
    └── tasks_default.json
```

```
/home/ros/agent/scheduler/       (data – written at runtime)
├── tasks.json                   # Task definitions
├── scheduler.log                # Daemon log
└── scheduler.pid                # PID file
```

## Requirements

- Python 3.10+
- `apscheduler>=3.10,<4.0`
- `pydantic>=2.0` (already present via `nostr_memory`)
- `pydantic-settings>=2.0`
- Writable directory for `tasks.json` (default: `/home/ros/agent/scheduler/`)

## Technical Details

### Architecture

```
┌──────────────────────────────────────────────────────┐
│  LLM Agent (agent_brain)                             │
│  ┌───────────────────────────────────────────────┐   │
│  │ execute_skill_script("task_scheduler", ...)   │   │
│  └──────────┬────────────────────────────────────┘   │
└─────────────┼────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────┐
│  skills/task_scheduler/scripts/tools.py (thin)    │
│  → delegates to:                                  │
│    python3 -m bob_nostr.task_scheduler.tools ...   │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  bob_nostr/task_scheduler/  (ROS sub-package)     │
│  ┌────────────────────────────────────────┐      │
│  │  tools.py (CLI Tool API)               │─────►│  tasks.json
│  │  add / remove / suspend / resume       │      │  (persistence)
│  │  list / get / status                   │      └──────────────────┘
│  └──────────┬─────────────────────────────┘
│             │
│             ▼
│  ┌────────────────────────────┐
│  │  scheduler.py              │
│  │  ┌──────────────────────┐  │
│  │  │ AsyncIOScheduler     │  │  ┌────────────────┐
│  │  │ ┌──────────────────┐ │  │  │ journal_writer │
│  │  │ │ CronTrigger      │─┼──┼─►│ .py (subproc)  │
│  │  │ │ IntervalTrigger  │ │  │  └────────────────┘
│  │  │ │ DateTrigger      │ │  │
│  │  │ └──────────────────┘ │  │  ┌────────────────┐
│  │  │ File Watcher (30s)   │──┼──┤ nostr_memory   │
│  │  └──────────────────────┘  │  │ .py (subproc)  │
│  └────────────────────────────┘  └────────────────┘
└──────────────────────────────────────────────────┘
```

### Daemon Lifecycle

The scheduler runs as a ROS executable (`ros2 run bob_nostr task_scheduler`):

| Event | Behaviour |
|---|---|
| `SIGTERM` / `SIGINT` | Graceful shutdown: complete running tasks, flush storage, remove PID file |
| `SIGHUP` | Reload `tasks.json` from disk (pick up external changes) |
| `SIGUSR1` | Print runtime status (job count, uptime) to stderr |

### Task Schema (JSON)

```json
{
  "task_id": "journal_6h",
  "skill_name": "journal",
  "script_path": "scripts/journal_writer.py",
  "arguments": "--collect",
  "trigger_type": "cron",
  "trigger_value": "0 */6 * * *",
  "enabled": true,
  "created_at": "2026-06-14T00:00:00+00:00",
  "updated_at": "2026-06-14T00:00:00+00:00",
  "last_run": "2026-06-14T06:00:00+00:00",
  "last_result": "success",
  "tags": ["journal"]
}
```

### Error Handling

| Scenario | Behaviour |
|---|---|
| `tasks.json` is missing | Created with empty `[]` on first write |
| `tasks.json` is corrupt | Backup saved as `.bak`, scheduler starts with empty task list |
| Task execution fails | Error logged, `last_result = "failure"`, scheduler continues |
| Script not found | Error logged, `last_result = "failure"`, scheduler continues |
| Duplicate `task_id` on `add` | Old job removed from scheduler before new one is registered |
| File watcher reload fails | Logged as warning, scheduler continues with previous state |

## Best Practices

- **Set environment variables** in the root `.env` file and add them to `.env.template` (see [TEMPLATE_SPEC.md](../TEMPLATE_SPEC.md)).
- **Default paths** target `/home/ros/agent/scheduler/` because this directory is on a writable bind-mounted volume. Do not change the tasks file path to a read-only location.
- **Use descriptive `task_id` values** like `journal_6h`, `backup_daily`, `cleanup_weekly` for easy filtering.
- **Use tags** to group tasks by purpose (`journal`, `backup`, `cleanup`, `discovery`) for filtered listing.
- **Start the daemon** via ROS: `ros2 run bob_nostr task_scheduler &`
- **Check daemon status** with the `status` tool or `ros2 run bob_nostr task_scheduler --status`.
