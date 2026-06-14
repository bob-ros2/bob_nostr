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
Task Scheduler Configuration.

All settings are loaded from environment variables with the SCHEDULER_ prefix.
Defaults are suitable for the containerized environment.
"""

from dataclasses import dataclass, field
import os


def _env(key: str, default: str) -> str:
    """Read an environment variable, returning the default if not set."""
    return os.environ.get(key, default)


@dataclass
class SchedulerSettings:
    """
    Central configuration for the task scheduler.

    All values can be overridden via environment variables (SCHEDULER_* prefix).
    """

    #: Path to the JSON file that stores all task definitions.
    tasks_file: str = field(
        default_factory=lambda: _env(
            'SCHEDULER_TASKS_FILE',
            '/home/ros/agent/scheduler/tasks.json',
        ),
    )

    #: IANA timezone string used for cron expression evaluation.
    timezone: str = field(
        default_factory=lambda: _env('SCHEDULER_TIMEZONE', 'Europe/Berlin'),
    )

    #: Interval (seconds) at which the file watcher polls tasks.json for changes.
    poll_interval: int = field(
        default_factory=lambda: int(
            _env('SCHEDULER_POLL_INTERVAL', '30'),
        ),
    )

    #: Path to the scheduler log file.
    log_file: str = field(
        default_factory=lambda: _env(
            'SCHEDULER_LOG_FILE',
            '/home/ros/agent/scheduler/scheduler.log',
        ),
    )

    #: Path to the PID file used by the daemon.
    pid_file: str = field(
        default_factory=lambda: _env(
            'SCHEDULER_PID_FILE',
            '/home/ros/agent/scheduler/scheduler.pid',
        ),
    )

    #: Root path of the task_scheduler package (auto-detected).
    skill_root: str = field(default_factory=lambda: os.path.dirname(os.path.abspath(__file__)))


# Global singleton – imported by other modules
settings = SchedulerSettings()
