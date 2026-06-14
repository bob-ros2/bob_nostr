#!/usr/bin/env python3
# Copyright 2026 Bob Ros
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Task Scheduler – CLI Tool API.

This module is the primary interface for the LLM agent.  It is called via
``execute_skill_script`` with a subcommand and arguments.

Exit codes:
  0 – success
  1 – error / task not found

Usage examples (from the LLM's perspective):

  execute_skill_script task_scheduler tools.py add
      --task-id weekly_journal
      --skill-name journal
      --trigger-type cron
      --trigger-value "0 */6 * * *"
      --arguments "--collect"
      --tags "journal,periodic"

  execute_skill_script task_scheduler tools.py list
  execute_skill_script task_scheduler tools.py get --task-id weekly_journal
  execute_skill_script task_scheduler tools.py remove --task-id weekly_journal
  execute_skill_script task_scheduler tools.py suspend --task-id weekly_journal
  execute_skill_script task_scheduler tools.py resume --task-id weekly_journal
  execute_skill_script task_scheduler tools.py status
"""

import argparse
import asyncio
import json
import logging
import sys

from bob_nostr.task_scheduler.scheduler import AgentTaskScheduler
from bob_nostr.task_scheduler.storage import TaskConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger('task_scheduler.tools')


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='tools.py',
        description='Task Scheduler – Tool API for the LLM agent',
    )
    sub = p.add_subparsers(dest='command', required=True)

    # add
    add_p = sub.add_parser('add', help='Add or update a task')
    add_p.add_argument('--task-id', required=True)
    add_p.add_argument('--skill-name', required=True)
    add_p.add_argument('--script-path', default='')
    add_p.add_argument('--arguments', default='')
    add_p.add_argument('--trigger-type', required=True,
                       choices=['cron', 'interval', 'once'])
    add_p.add_argument('--trigger-value', required=True)
    add_p.add_argument('--enabled', default='true', choices=['true', 'false'])
    add_p.add_argument('--tags', default='',
                       help='Comma-separated list of tags')

    # remove
    sub.add_parser('remove', help='Delete a task').add_argument(
        '--task-id', required=True)

    # suspend
    sub.add_parser('suspend', help='Disable a task (keep config)').add_argument(
        '--task-id', required=True)

    # resume
    sub.add_parser('resume', help='Re-enable a suspended task').add_argument(
        '--task-id', required=True)

    # list
    lst = sub.add_parser('list', help='List all tasks')
    lst.add_argument('--filter-enabled', default='',
                     choices=['', 'true', 'false'],
                     help='Filter by enabled state')
    lst.add_argument('--filter-tag', default='',
                     help='Only show tasks with this tag')

    # get
    sub.add_parser('get', help='Show details of a single task').add_argument(
        '--task-id', required=True)

    # status
    sub.add_parser('status', help='Scheduler daemon status')

    return p


# ---------------------------------------------------------------------------
# JSON output helper
# ---------------------------------------------------------------------------

def _json_out(data, exit_code: int = 0) -> None:
    """Print JSON to stdout and exit with the given code."""
    print(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Handlers (async)
# ---------------------------------------------------------------------------

async def _handle_add(args, scheduler: AgentTaskScheduler) -> None:
    tags = [t.strip() for t in args.tags.split(',') if t.strip()] if args.tags else []
    cfg = TaskConfig(
        task_id=args.task_id,
        skill_name=args.skill_name,
        script_path=args.script_path,
        arguments=args.arguments,
        trigger_type=args.trigger_type,
        trigger_value=args.trigger_value,
        enabled=(args.enabled == 'true'),
        tags=tags,
    )
    await scheduler.add_task(cfg)
    _json_out({'status': 'ok', 'task_id': args.task_id})


async def _handle_remove(args, scheduler: AgentTaskScheduler) -> None:
    ok = await scheduler.remove_task(args.task_id)
    if not ok:
        _json_out({'status': 'error', 'message': f'Task {args.task_id!r} not found'}, 1)
    _json_out({'status': 'ok', 'task_id': args.task_id})


async def _handle_suspend(args, scheduler: AgentTaskScheduler) -> None:
    ok = await scheduler.suspend_task(args.task_id)
    if not ok:
        _json_out({'status': 'error', 'message': f'Task {args.task_id!r} not found'}, 1)
    _json_out({'status': 'ok', 'task_id': args.task_id, 'enabled': False})


async def _handle_resume(args, scheduler: AgentTaskScheduler) -> None:
    ok = await scheduler.resume_task(args.task_id)
    if not ok:
        _json_out({'status': 'error', 'message': f'Task {args.task_id!r} not found'}, 1)
    _json_out({'status': 'ok', 'task_id': args.task_id, 'enabled': True})


async def _handle_list(args, scheduler: AgentTaskScheduler) -> None:
    tasks = await scheduler.list_tasks()

    if args.filter_enabled:
        flag = args.filter_enabled == 'true'
        tasks = {tid: t for tid, t in tasks.items() if t.enabled == flag}

    if args.filter_tag:
        tasks = {tid: t for tid, t in tasks.items()
                 if args.filter_tag in t.tags}

    items: list[dict] = []
    for tid, t in sorted(tasks.items()):
        items.append({
            'task_id': tid,
            'skill_name': t.skill_name,
            'trigger_type': t.trigger_type,
            'trigger_value': t.trigger_value,
            'enabled': t.enabled,
            'last_run': t.last_run,
            'last_result': t.last_result,
            'tags': t.tags,
        })

    _json_out({'status': 'ok', 'count': len(items), 'tasks': items})


async def _handle_get(args, scheduler: AgentTaskScheduler) -> None:
    t = await scheduler.get_task(args.task_id)
    if t is None:
        _json_out({'status': 'error', 'message': f'Task {args.task_id!r} not found'}, 1)
    _json_out({'status': 'ok', 'task': t.model_dump()})


async def _handle_status(args, scheduler: AgentTaskScheduler) -> None:
    _json_out({'status': 'ok', 'scheduler': scheduler.get_status()})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    scheduler = AgentTaskScheduler()
    await scheduler.start()

    try:
        handler_map = {
            'add': _handle_add,
            'remove': _handle_remove,
            'suspend': _handle_suspend,
            'resume': _handle_resume,
            'list': _handle_list,
            'get': _handle_get,
            'status': _handle_status,
        }
        handler = handler_map.get(args.command)
        if handler is None:
            parser.print_help()
            sys.exit(1)
        await handler(args, scheduler)
    finally:
        await scheduler.stop()


if __name__ == '__main__':
    asyncio.run(main())
