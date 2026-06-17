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
DM Handler for the Service Announcement Skill.

This tool is called by the LLM agent to:
  - Parse an incoming DM and identify the requested service
  - Generate a help message listing all available services

Usage:
    help       — Print a formatted list of all services
    parse --dm "scan_relay wss://example.relay"
"""

import argparse
import json
import os
import sys

import yaml

# ---------------------------------------------------------------------------
# Service definitions
# ---------------------------------------------------------------------------
DEFAULT_SERVICES = [
    {
        'id': 'agent.bob/relay-scan',
        'title': 'Relay Scanner',
        'description': 'Scan Nostr relays, cataloging metadata with trust classification.',
        'alt': 'scan_relay wss://<relay-url>',
        'skill': 'relay_discovery',
        'script': 'scripts/scan_relays.py',
    },
    {
        'id': 'agent.bob/web-research',
        'title': 'Web Research',
        'description': 'Search the web for information on a topic and summarize results.',
        'alt': 'search_web <query>',
        'skill': 'web_researcher',
        'script': 'scripts/search.py',
    },
    {
        'id': 'agent.bob/journal-service',
        'title': 'Journal Service',
        'description': 'Create a structured journal entry from provided content or system state.',
        'alt': 'journal <topic>',
        'skill': 'journal',
        'script': 'scripts/journal_writer.py',
    },
    {
        'id': 'agent.bob/memory-backup',
        'title': 'Memory Backup',
        'description': 'Store or retrieve Nostr events as decentralized long-term memory.',
        'alt': 'backup <kind> or retrieve <event-id>',
        'skill': 'nostr_memory',
        'script': 'scripts/nostr_memory_tool.py',
    },
    {
        'id': 'agent.bob/task-reminder',
        'title': 'Task Reminder',
        'description': 'Schedule or manage timed tasks and reminders.',
        'alt': 'remind <text> or list_tasks',
        'skill': 'task_scheduler',
        'script': 'scripts/tools.py',
    },
    {
        'id': 'agent.bob/code-execute',
        'title': 'Code Execution',
        'description': 'Execute Python code in a sandboxed REPL environment and return results.',
        'alt': 'run <python-code>',
        'skill': 'repl_kernel',
        'script': 'scripts/tools.py',  # repl_execute via repl_kernel
    },
]


def _load_services() -> list:
    """Load service definitions from defaults (and optionally from YAML file)."""
    svc_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'resources')
    yaml_path = os.path.join(svc_dir, 'services_default.yaml')
    if os.path.isfile(yaml_path):
        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and 'services' in data:
                return data['services']
        except Exception as e:
            print(f'[WARN] Could not load {yaml_path}: {e}', file=sys.stderr)
    return DEFAULT_SERVICES


def cmd_help() -> None:
    """Print a formatted help message for the LLM to send as DM reply."""
    services = _load_services()

    lines = [
        '🤖 *Available Services*',
        '',
        'Send me a DM with one of these commands:',
        '',
    ]

    for svc in services:
        lines.append(f'  **{svc["alt"]}**')
        lines.append(f'  → {svc["description"]}')
        lines.append('')

    lines.append('--')
    lines.append(f'Currently offering {len(services)} services.')

    print('\n'.join(lines))


def cmd_parse(args) -> None:
    """Parse a DM and identify which service it maps to."""
    dm_text = (args.dm or '').strip().lower()
    if not dm_text:
        print(json.dumps({'error': 'Empty DM content'}, indent=2))
        sys.exit(1)

    services = _load_services()

    # Try to match by keyword in the DM
    for svc in services:
        alt_lower = svc['alt'].lower()
        # Extract the trigger keyword (e.g. "scan_relay" from "scan_relay wss://...")
        trigger = alt_lower.split()[0] if alt_lower.split() else ''
        if dm_text.startswith(trigger):
            # Extract the arguments after the trigger
            args_part = dm_text[len(trigger):].strip()
            result = {
                'matched': True,
                'service_id': svc['id'],
                'title': svc['title'],
                'skill': svc['skill'],
                'script': svc['script'],
                'arguments': args_part,
                'alt': svc['alt'],
            }
            print(json.dumps(result, indent=2))
            return

    # Try partial match in alt or title
    for svc in services:
        searchable = f'{svc["alt"]} {svc["title"]} {svc["id"]}'.lower()
        if dm_text in searchable:
            result = {
                'matched': True,
                'service_id': svc['id'],
                'title': svc['title'],
                'skill': svc['skill'],
                'script': svc['script'],
                'arguments': dm_text,
                'alt': svc['alt'],
                'note': 'Partial match — user may need clearer instruction',
            }
            print(json.dumps(result, indent=2))
            return

    # No match
    result = {
        'matched': False,
        'service_id': None,
        'title': None,
        'skill': None,
        'script': None,
        'arguments': dm_text,
        'note': 'Unknown command. Use `help` to see available services.',
    }
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Service Announcement DM Handler'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('help', help='Show available services (formatted for DM reply)')

    p_parse = sub.add_parser('parse', help='Parse a DM and map to a service')
    p_parse.add_argument('--dm', required=True, help='The DM text content to parse')

    parsed = parser.parse_args()

    if parsed.command == 'help':
        cmd_help()
    elif parsed.command == 'parse':
        cmd_parse(parsed)


if __name__ == '__main__':
    main()
