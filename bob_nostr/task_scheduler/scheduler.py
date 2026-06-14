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
Agent Task Scheduler – Core Scheduling Engine.

Uses APScheduler's AsyncIOScheduler to manage cron, interval, and one-shot
triggers.  Task definitions are loaded from a JSON file (via TaskStorage)
and kept in sync through a background file watcher loop.
"""

import asyncio
from collections.abc import Callable
import contextlib
import datetime
import logging
import os
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bob_nostr.task_scheduler.config import settings
from bob_nostr.task_scheduler.storage import TaskConfig, TaskStorage

logger = logging.getLogger('task_scheduler.scheduler')

# Type for optional callback when a task fires (used for testing / hooks)
FireCallback = Callable[[TaskConfig], None]


# ---------------------------------------------------------------------------
# Helper: resolve the absolute path of a skill's script
# ---------------------------------------------------------------------------

def _resolve_skill_script(skill_name: str, script_path: str) -> str | None:
    """
    Return the absolute path to *script_path* inside *skill_name*.

    Checks, in order:
      1. ``/ros2_ws/src/bob_nostr/skills/{skill_name}/{script_path}``
      2. ``/home/ros/agent/skills/{skill_name}/{script_path}``
    Returns ``None`` if neither exists.
    """
    candidates = [
        f'/ros2_ws/src/bob_nostr/skills/{skill_name}/{script_path}',
        f'/home/ros/agent/skills/{skill_name}/{script_path}',
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


# ---------------------------------------------------------------------------
# Scheduler class
# ---------------------------------------------------------------------------

class AgentTaskScheduler:
    """Orchestrates APScheduler jobs for all active tasks."""

    def __init__(self) -> None:
        self._aps = AsyncIOScheduler(timezone=settings.timezone)
        self._storage = TaskStorage(settings.tasks_file)
        self._running = False
        self._watcher_task: asyncio.Task | None = None
        self._start_time: datetime.datetime | None = None
        self._on_fire: FireCallback | None = None

    # -- life cycle --------------------------------------------------------

    async def start(self) -> None:
        """Load tasks and start both the APScheduler and the file watcher."""
        if self._running:
            logger.warning('Scheduler is already running.')
            return

        logger.info('Starting task scheduler (timezone=%s)', settings.timezone)
        self._start_time = datetime.datetime.now(tz=datetime.timezone.utc)

        tasks = await self._storage.load_all()
        for task in tasks.values():
            self._register_task(task)

        self._aps.start()
        self._running = True

        self._watcher_task = asyncio.create_task(
            self._file_watcher_loop(),
            name='task_scheduler_watcher',
        )
        logger.info('Scheduler started with %d task(s).', len(tasks))

    async def stop(self) -> None:
        """Graceful shutdown: cancel watcher, remove all jobs, stop APS."""
        if not self._running:
            return
        logger.info('Stopping task scheduler ...')
        self._running = False

        if self._watcher_task:
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task

        self._aps.shutdown(wait=True)
        logger.info('Scheduler stopped.')

    # -- task management (called by tools.py) ------------------------------

    async def add_task(self, cfg: TaskConfig) -> None:
        """Add or replace a task in storage and (if enabled) in the runtime."""
        old = (await self._storage.load_all()).get(cfg.task_id)
        if old and old.enabled:
            self._unregister_task(cfg.task_id)

        await self._storage.save(cfg)

        if cfg.enabled:
            self._register_task(cfg)
        logger.info('Task %s added/updated (enabled=%s).', cfg.task_id, cfg.enabled)

    async def remove_task(self, task_id: str) -> bool:
        """Delete a task.  Returns True if the task existed."""
        self._unregister_task(task_id)
        existed = await self._storage.delete(task_id)
        if existed:
            logger.info('Task %s removed.', task_id)
        return existed

    async def suspend_task(self, task_id: str) -> bool:
        """Disable a task without removing its configuration."""
        tasks = await self._storage.load_all()
        task = tasks.get(task_id)
        if task is None:
            return False
        self._unregister_task(task_id)
        task.enabled = False
        await self._storage.save(task)
        logger.info('Task %s suspended.', task_id)
        return True

    async def resume_task(self, task_id: str) -> bool:
        """Re-enable a previously suspended task."""
        tasks = await self._storage.load_all()
        task = tasks.get(task_id)
        if task is None:
            return False
        task.enabled = True
        await self._storage.save(task)
        self._register_task(task)
        logger.info('Task %s resumed.', task_id)
        return True

    async def list_tasks(self) -> dict[str, TaskConfig]:
        """Return all known tasks."""
        return await self._storage.load_all()

    async def get_task(self, task_id: str) -> TaskConfig | None:
        """Return a single task or None."""
        tasks = await self._storage.load_all()
        return tasks.get(task_id)

    def get_status(self) -> dict:
        """Return a snapshot of the scheduler's runtime state."""
        return {
            'running': self._running,
            'uptime_seconds': (
                (
                    datetime.datetime.now(tz=datetime.timezone.utc)
                    - self._start_time
                ).total_seconds()
                if self._start_time
                else 0
            ),
            'apscheduler_jobs': len(self._aps.get_jobs()),
            'timezone': settings.timezone,
            'tasks_file': settings.tasks_file,
        }

    # -- hook for testing --------------------------------------------------

    def set_on_fire(self, cb: FireCallback) -> None:
        """Register a callback invoked every time a task fires."""
        self._on_fire = cb

    # -- internal: APScheduler management ----------------------------------

    def _register_task(self, task: TaskConfig) -> None:
        """Add a job to the APScheduler for *task*."""
        job_id = f'task_{task.task_id}'
        try:
            trigger = self._build_trigger(task)
        except ValueError as exc:
            logger.exception('Cannot build trigger for task %s: %s', task.task_id, exc)
            return

        self._aps.add_job(
            self._fire_task,
            trigger=trigger,
            args=[task],
            id=job_id,
            name=task.task_id,
            replace_existing=True,
        )

    def _unregister_task(self, task_id: str) -> None:
        """Remove a job from the APScheduler."""
        job_id = f'task_{task_id}'
        try:
            self._aps.remove_job(job_id)
        except Exception:
            pass  # job may not exist

    @staticmethod
    def _build_trigger(task: TaskConfig):
        """Construct an APScheduler trigger from a TaskConfig."""
        ttype = task.trigger_type
        tval = task.trigger_value

        if ttype == 'cron':
            # Standard 5-field cron expression
            parts = tval.strip().split()
            if len(parts) != 5:
                msg = f'Invalid cron expression {tval!r} – expected 5 fields'
                raise ValueError(
                    msg,
                )
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                timezone=settings.timezone,
            )

        if ttype == 'interval':
            seconds = int(tval)
            return IntervalTrigger(seconds=seconds)

        if ttype == 'once':
            return DateTrigger(run_date=tval, timezone=settings.timezone)

        msg = f'Unknown trigger_type: {ttype!r}'
        raise ValueError(msg)

    # -- internal: task execution ------------------------------------------

    async def _fire_task(self, task: TaskConfig) -> None:
        """Execute a task's skill script via subprocess."""
        logger.info('Firing task %s (skill=%s)', task.task_id, task.skill_name)

        # Allow test hooks
        if self._on_fire:
            self._on_fire(task)
            return

        # Resolve script path
        script_abs = _resolve_skill_script(task.skill_name, task.script_path)
        if script_abs is None:
            logger.error(
                'Task %s: script %s/%s not found – skipping.',
                task.task_id, task.skill_name, task.script_path,
            )
            task.last_result = 'failure'
            task.last_run = _now_iso()
            await self._storage.save(task)
            return

        cmd = [sys.executable, script_abs]
        if task.arguments:
            cmd.extend(task.arguments.split())

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300,
            )
        except asyncio.TimeoutError:
            logger.exception('Task %s timed out after 300s.', task.task_id)
            task.last_result = 'failure'
            task.last_run = _now_iso()
            await self._storage.save(task)
            return
        except Exception as exc:
            logger.exception('Task %s execution error: %s', task.task_id, exc)
            task.last_result = 'failure'
            task.last_run = _now_iso()
            await self._storage.save(task)
            return

        if proc.returncode == 0:
            logger.info(
                'Task %s completed successfully (stdout=%d bytes).',
                task.task_id, len(stdout or b''),
            )
            task.last_result = 'success'
        else:
            logger.error(
                'Task %s failed (exit=%d, stderr=%s).',
                task.task_id, proc.returncode,
                (stderr or b'').decode('utf-8', errors='replace')[:500],
            )
            task.last_result = 'failure'

        task.last_run = _now_iso()
        await self._storage.save(task)

    # -- internal: file watcher --------------------------------------------

    async def _file_watcher_loop(self) -> None:
        """
        Periodically re-read tasks.json and sync the runtime.

        This allows external edits (e.g. the LLM writing via tools.py) to be
        picked up without restarting the scheduler daemon.
        """
        interval = max(settings.poll_interval, 5)  # floor at 5 s
        while self._running:
            await asyncio.sleep(interval)

            try:
                disk_tasks = await self._storage.reload()
            except Exception as exc:
                logger.warning('File watcher reload failed: %s', exc)
                continue

            # Remove jobs for tasks no longer on disk
            current_ids = set(disk_tasks.keys())
            for job in list(self._aps.get_jobs()):
                tid = job.name  # we stored task_id in job.name
                if tid not in current_ids:
                    self._unregister_task(tid)

            # Add / update jobs for tasks on disk
            for task in disk_tasks.values():
                job_id = f'task_{task.task_id}'
                existing = self._aps.get_job(job_id)
                if existing is None and task.enabled:
                    self._register_task(task)
                elif existing is not None and not task.enabled:
                    self._unregister_task(task.task_id)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
