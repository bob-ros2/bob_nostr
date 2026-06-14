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
Task Scheduler – Thin CLI wrapper for the agent harness.

This stub delegates to the ROS-installed ``bob_nostr.task_scheduler.tools``
module.  The actual implementation lives at::

    bob_nostr/task_scheduler/tools.py

Usage (from agent harness, unchanged)::

    execute_skill_script task_scheduler scripts/tools.py add ...
    execute_skill_script task_scheduler scripts/tools.py list
    execute_skill_script task_scheduler scripts/tools.py get --task-id ...
    execute_skill_script task_scheduler scripts/tools.py remove --task-id ...
    execute_skill_script task_scheduler scripts/tools.py suspend --task-id ...
    execute_skill_script task_scheduler scripts/tools.py resume --task-id ...
    execute_skill_script task_scheduler scripts/tools.py status
"""

import subprocess
import sys


def main() -> None:
    """Delegate to the ROS-installed tools module."""
    cmd = [
        sys.executable,
        '-m', 'bob_nostr.task_scheduler.tools',
        *sys.argv[1:],
    ]
    proc = subprocess.run(cmd)
    sys.exit(proc.returncode)


if __name__ == '__main__':
    main()
