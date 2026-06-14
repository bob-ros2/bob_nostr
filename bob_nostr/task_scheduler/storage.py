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
Task Persistence (Storage Layer).

Stores task definitions as a JSON array in a single file.
Uses an asyncio lock to guard concurrent read/write access.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import shutil

from pydantic import BaseModel, Field

logger = logging.getLogger('task_scheduler.storage')


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class TaskConfig(BaseModel):
    """Schema for a single scheduled task."""

    task_id: str
    skill_name: str
    script_path: str = ''
    arguments: str = ''
    trigger_type: str = 'cron'       # "cron" | "interval" | "once"
    trigger_value: str = ''          # cron-expression | seconds | ISO-datetime
    enabled: bool = True
    created_at: str = ''
    updated_at: str = ''
    last_run: str | None = None
    last_result: str | None = None   # "success" | "failure" | None
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Storage backend
# ---------------------------------------------------------------------------

class TaskStorage:
    """Read/write task definitions from/to a JSON file."""

    def __init__(self, filepath: str) -> None:
        self._filepath = filepath
        self._lock = asyncio.Lock()
        self._tasks: dict[str, TaskConfig] = {}

    # -- public API ---------------------------------------------------------

    async def load_all(self) -> dict[str, TaskConfig]:
        """Load all tasks from disk and return the internal dict."""
        async with self._lock:
            self._tasks = await self._read_file()
            return dict(self._tasks)

    async def load_active(self) -> dict[str, TaskConfig]:
        """Return only enabled tasks."""
        all_tasks = await self.load_all()
        return {tid: t for tid, t in all_tasks.items() if t.enabled}

    async def save(self, task: TaskConfig) -> None:
        """Persist a single task (insert or update)."""
        async with self._lock:
            now = _now_iso()
            if task.task_id in self._tasks:
                task.updated_at = now
            else:
                task.created_at = now
                task.updated_at = now
            self._tasks[task.task_id] = task
            await self._write_file()

    async def delete(self, task_id: str) -> bool:
        """Remove a task.  Returns True if it existed, False otherwise."""
        async with self._lock:
            existed = task_id in self._tasks
            if existed:
                del self._tasks[task_id]
                await self._write_file()
            return existed

    async def reload(self) -> dict[str, TaskConfig]:
        """Force-re-read the file from disk (used by file watcher)."""
        return await self.load_all()

    # -- internal helpers --------------------------------------------------

    async def _read_file(self) -> dict[str, TaskConfig]:
        """Parse the JSON file and return a dict keyed by task_id."""
        if not os.path.isfile(self._filepath):
            logger.info('Tasks file %s not found - starting empty.', self._filepath)
            return {}

        try:
            with open(self._filepath, encoding='utf-8') as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.exception('Corrupt tasks file %s: %s', self._filepath, exc)
            backup = self._filepath + '.bak'
            if os.path.isfile(self._filepath):
                shutil.copy2(self._filepath, backup)
                logger.info('Backed up corrupt file to %s', backup)
            return {}

        if not isinstance(raw, list):
            logger.error('Expected JSON array in %s, got %s', self._filepath, type(raw).__name__)
            return {}

        tasks: dict[str, TaskConfig] = {}
        for item in raw:
            try:
                t = TaskConfig(**item)
            except Exception as exc:
                logger.warning('Skipping invalid task entry: %s', exc)
                continue
            tasks[t.task_id] = t
        logger.info('Loaded %d task(s) from %s', len(tasks), self._filepath)
        return tasks

    async def _write_file(self) -> None:
        """Atomically write the current task dict to the JSON file."""
        dirpath = os.path.dirname(self._filepath)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)

        tmp = self._filepath + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(
                    [t.model_dump() for t in self._tasks.values()],
                    fh,
                    indent=2,
                    ensure_ascii=False,
                )
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._filepath)
        except OSError as exc:
            logger.exception('Failed to write tasks file %s: %s', self._filepath, exc)
            raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
