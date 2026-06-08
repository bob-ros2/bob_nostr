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
Example: Using the Nostr Memory Skill.

Starts relays, stores memories, retrieves them, and displays the status.
"""

import os
import shlex
import subprocess
import sys
import time

# Path to the skill directory (dynamically determined)
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_script(script, args):
    """Execute a skill script."""
    cmd = [sys.executable, f'{SKILL_DIR}/scripts/{script}'] + shlex.split(args)
    print(f'\n$ {" ".join(cmd)}')
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode


def main():
    print('=' * 60)
    print('  Nostr Memory Skill – Example Workflow')
    print('=' * 60)

    # 1. Check if relays are reachable
    print('\n[1/5] Checking if Nostr relays are reachable...')
    ret = run_script('nostr_relay_manager.py', '--action status')
    if ret != 0:
        print('\n[ERROR] Relays are not reachable. Please start them manually via Docker Compose')
        print('and make sure NOSTR_RELAYS environment variable is correctly set.')
        sys.exit(1)

    # 3. Set agent status
    print('\n[3/5] Saving agent status...')
    run_script('nostr_memory_tool.py',
               '--action set_status --content \'{"role": "main_agent", '
               '"mood": "curious", "version": "1.0"}\'')

    # 4. Store a memory
    print('\n[4/5] Saving memory (Kind 5000)...')
    run_script('nostr_memory_tool.py',
               '--action store --kind 5000 '
               '--content \'{"topic": "evolution_plan", '
               '"suggestion": "Introduce Nostr-based memory"}\' '
               '--tags "nostr,memory,evolution"')

    # Wait briefly until events are propagated
    time.sleep(2)

    # 5. Retrieve stored memories
    print('\n[5/5] Searching stored memories...')
    run_script('nostr_memory_tool.py',
               '--action search --kind 5000 --limit 5')

    # 6. Retrieve status
    print('\n[Bonus] Retrieving agent status...')
    run_script('nostr_memory_tool.py',
               '--action get_status')

    print('\n' + '=' * 60)
    print('  Workflow completed.')
    print('  Relays continue running. Stop them via Docker Compose if needed.')
    print('=' * 60)


if __name__ == '__main__':
    main()
