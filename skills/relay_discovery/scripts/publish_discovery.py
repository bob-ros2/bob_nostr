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
Publish Discovery – Store relay scan results as Nostr memory.

Takes scan results (from scan_relays.py or relay_index.py) and stores them
as relay-index or discovery-results memory types via the nostr_memory skill's
serialized mode (cli_agent_memory.py). This script itself does NOT use
nostr-sdk directly – it delegates to nostr_memory.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def find_cli_agent_memory() -> str:
    """Find the cli_agent_memory.py script in the nostr_memory skill."""
    # Try relative to this script's location
    base = Path(__file__).resolve().parent.parent.parent / 'nostr_memory' / 'scripts'
    cli = base / 'cli_agent_memory.py'
    if cli.exists():
        return str(cli)

    # Try workspace paths
    candidates = [
        '/ros2_ws/src/bob_nostr/skills/nostr_memory/scripts/cli_agent_memory.py',
        '/blue/dev/bob_nostr/ros2_ws/src/bob_nostr/skills/'
        'nostr_memory/scripts/cli_agent_memory.py',
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    return 'cli_agent_memory.py'  # fallback to PATH


def find_agent_memory_api() -> str:
    """Find the api.py to use AgentMemory directly if available."""
    base = Path(__file__).resolve().parent.parent.parent / 'nostr_memory' / 'scripts'
    api = base / 'api.py'
    if api.exists():
        return str(base)
    return None


def publish_via_cli(input_file: str, memory_type: str,
                    compress: str, relays: str = None) -> dict:
    """Publish scan results via cli_agent_memory.py CLI."""
    cli = find_cli_agent_memory()
    result = {'status': 'published', 'events': 0, 'packed_file': None,
              'error': None}

    # Step 1: Encode/pack
    with tempfile.NamedTemporaryFile(
        suffix='.json', prefix='packed_', delete=False
    ) as tmp:
        packed_file = tmp.name

    encode_cmd = [
        sys.executable, cli, 'encode', memory_type,
        '--input', input_file,
        '--output', packed_file,
        '--compress', compress
    ]
    proc = subprocess.run(
        encode_cmd, capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        result['error'] = f'encode failed: {proc.stderr.strip()}'
        return result

    result['packed_file'] = packed_file

    # Step 2: Publish (if relays provided)
    if relays:
        publish_cmd = [
            sys.executable, cli, 'publish',
            '--input', packed_file,
            '--relays', relays
        ]
        proc = subprocess.run(
            publish_cmd, capture_output=True, text=True, timeout=60
        )
        if proc.returncode != 0:
            result['error'] = f'publish failed: {proc.stderr.strip()}'
            return result

    # Count events
    try:
        with open(packed_file) as f:
            events = json.load(f)
            result['events'] = len(events) if isinstance(events, list) else 0
    except Exception:
        pass

    return result


def publish_via_api(input_file: str, memory_type: str,
                    compress: str, relays: str = None) -> dict:
    """Publish scan results using the AgentMemory API directly."""
    api_dir = find_agent_memory_api()
    if not api_dir:
        return publish_via_cli(input_file, memory_type, compress, relays)

    sys.path.insert(0, api_dir)
    try:
        from api import AgentMemory
    except ImportError as exc:
        sys.path.pop(0)
        return {'error': f'Cannot import AgentMemory: {exc}'}

    sys.path.pop(0)

    with open(input_file, 'r') as f:
        data = json.load(f)

    mem = AgentMemory()
    events = mem.pack(memory_type, data, compression=compress)
    packed_data = [
        {
            'kind': e['kind'], 'content': e['content'], 'tags': e['tags'],
            'id': e.get('id'), 'pubkey': e.get('pubkey'),
            'created_at': e.get('created_at'), 'sig': e.get('sig')
        }
        for e in events
    ]

    result = {'status': 'packed', 'events': len(packed_data),
              'packed_file': None, 'error': None}

    # Write packed data to temp file
    with tempfile.NamedTemporaryFile(
        suffix='.json', prefix='packed_', delete=False, mode='w'
    ) as tmp:
        json.dump(packed_data, tmp, indent=2)
        result['packed_file'] = tmp.name

    # Publish if relays configured
    if relays:
        cli = find_cli_agent_memory()
        publish_cmd = [
            sys.executable, cli, 'publish',
            '--input', result['packed_file'],
            '--relays', relays
        ]
        proc = subprocess.run(
            publish_cmd, capture_output=True, text=True, timeout=60
        )
        if proc.returncode != 0:
            result['error'] = f'publish failed: {proc.stderr.strip()}'
            return result
        result['status'] = 'published'

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Publish Discovery – Store scan results as Nostr memory'
    )
    parser.add_argument(
        '--input', '-i', required=True,
        help='Input JSON file (scan results from scan_relays.py or relay_index.py)'
    )
    parser.add_argument(
        '--type', default='relay-index',
        choices=['relay-index', 'discovery-results'],
        help='Memory type to use (default: relay-index)'
    )
    parser.add_argument(
        '--compress', default='none',
        choices=['none', 'gz', 'tar.gz'],
        help='Compression format (default: none)'
    )
    parser.add_argument(
        '--relays', default=None,
        help='Comma-separated relay URLs for publishing'
    )
    parser.add_argument(
        '--publish', action='store_true',
        help='Automatically publish to relays (uses NOSTR_RELAYS env if --relays not set)'
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f'[ERROR] Input file not found: {args.input}', file=sys.stderr)
        sys.exit(1)

    relays = args.relays
    if args.publish and not relays:
        relays = os.environ.get('NOSTR_RELAYS', os.environ.get('EXTERNAL_NOSTR_RELAYS', ''))

    # Try API first, fall back to CLI
    result = publish_via_api(args.input, args.type, args.compress, relays)
    if result.get('error') and 'Cannot import' in result['error']:
        result = publish_via_cli(args.input, args.type, args.compress, relays)

    print(json.dumps(result, indent=2))

    if result.get('error'):
        sys.exit(1)


if __name__ == '__main__':
    main()
