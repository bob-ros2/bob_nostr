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
Relay Index Management – Load, merge, save, and query the relay index.

The relay index is stored as a local YAML file and optionally as
a relay-index Nostr memory type via the nostr_memory skill.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml


RELAY_INDEX_DEFAULT = os.path.expanduser('/home/ros/agent/relay_index.yaml')


def load_index(path: str = None) -> Dict[str, Any]:
    """Load the relay index from a local YAML file."""
    filepath = Path(path or RELAY_INDEX_DEFAULT).resolve()

    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data, dict) and 'relays' in data:
            return data
        # Legacy format: just a list
        if isinstance(data, list):
            return {'relays': data, 'updated': None}
        return {'relays': [], 'updated': None}

    # Initialize empty index
    return {
        'version': '1.0',
        'updated': None,
        'relays': []
    }


def save_index(index: Dict[str, Any], path: str = None) -> str:
    """Save the relay index to a local YAML file."""
    filepath = Path(path or RELAY_INDEX_DEFAULT).resolve()
    index['updated'] = datetime.now(timezone.utc).isoformat()
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(index, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return str(filepath)


def merge_scan_results(index: Dict[str, Any], scan_results: List[Dict]) -> Dict[str, Any]:
    """Merge scan results into the index, updating existing entries."""
    index_by_url = {r['url']: r for r in index.get('relays', [])}

    for result in scan_results:
        url = result.get('url', '')
        if not url:
            continue

        if url in index_by_url:
            # Update existing
            existing = index_by_url[url]
            existing.update({
                'url': url,
                'trust': result.get('trust', existing.get('trust', 'unknown')),
                'latency_ms': result.get('latency_ms'),
                'nip11': result.get('nip11', existing.get('nip11', {})),
                'connected': result.get('connected'),
                'stored': result.get('stored'),
                'retrieved': result.get('retrieved'),
                'last_scan': result.get('tested_at',
                                        datetime.now(timezone.utc).isoformat()),
                'last_error': result.get('error')
            })
            # Clean up None values
            if existing.get('last_error') is None:
                existing.pop('last_error', None)
        else:
            # New entry
            entry = {
                'url': url,
                'trust': result.get('trust', 'unknown'),
                'latency_ms': result.get('latency_ms'),
                'nip11': result.get('nip11', {}),
                'connected': result.get('connected'),
                'stored': result.get('stored'),
                'retrieved': result.get('retrieved'),
                'first_seen': datetime.now(timezone.utc).isoformat(),
                'last_scan': result.get('tested_at',
                                        datetime.now(timezone.utc).isoformat()),
                'last_error': result.get('error')
            }
            index_by_url[url] = entry

    index['relays'] = list(index_by_url.values())
    return index


def get_trusted(index: Dict[str, Any]) -> List[Dict]:
    """Return only relays with 'trusted' trust level."""
    return [r for r in index.get('relays', []) if r.get('trust') == 'trusted']


def get_online(index: Dict[str, Any]) -> List[Dict]:
    """Return relays that are connected."""
    return [r for r in index.get('relays', []) if r.get('connected')]


def format_markers(index: Dict[str, Any]) -> List[Dict]:
    """Export relays in map marker format."""
    markers = []
    for r in index.get('relays', []):
        nip11 = r.get('nip11', {})
        marker = {
            'type': 'marker',
            'url': r['url'],
            'trust': r.get('trust', 'unknown'),
            'latency_ms': r.get('latency_ms'),
        }
        # Try to extract geo from NIP-11 or use N/A
        if isinstance(nip11, dict):
            marker['label'] = nip11.get('name', r['url'])
            marker['description'] = nip11.get('description', '')
        else:
            marker['label'] = r['url']
        markers.append(marker)
    return markers


def print_summary(index: Dict[str, Any]) -> None:
    """Print a summary of the relay index."""
    relays = index.get('relays', [])
    by_trust: Dict[str, int] = {}
    for r in relays:
        t = r.get('trust', 'unknown')
        by_trust[t] = by_trust.get(t, 0) + 1

    print('\n  Relay Index Summary')
    print(f"  {'-'*40}")
    print(f"  Updated: {index.get('updated', 'never')}")
    print(f'  Total relays: {len(relays)}')
    for trust, count in sorted(by_trust.items()):
        print(f'    {trust}: {count}')


def main():
    parser = argparse.ArgumentParser(
        description='Relay Index Manager – Manage relay index data'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p_list = sub.add_parser('list', help='List all relays in index')
    p_list.add_argument('--trust', default=None,
                        help='Filter by trust level (trusted, unstable, paywalled, dead)')
    p_list.add_argument('--online', action='store_true',
                        help='Show only connected/online relays')

    p_merge = sub.add_parser('merge', help='Merge scan results into index')
    p_merge.add_argument('--input', '-i', required=True,
                         help='JSON scan results file from scan_relays.py')
    p_merge.add_argument('--output', '-o', default=None,
                         help='Output path for updated index '
                         '(default: /home/ros/agent/relay_index.yaml)')

    sub.add_parser('trusted', help='List only trusted relays')

    sub.add_parser('markers', help='Export relays as map markers')

    sub.add_parser('summary', help='Print relay index summary')

    args = parser.parse_args()

    index = load_index()

    if args.command == 'list':
        relays = index.get('relays', [])
        if args.trust:
            relays = [r for r in relays if r.get('trust') == args.trust]
        if args.online:
            relays = [r for r in relays if r.get('connected')]

        print(json.dumps(relays, indent=2))

    elif args.command == 'merge':
        with open(args.input, 'r') as f:
            scan_data = json.load(f)
        scan_results = scan_data.get('relays', scan_data if isinstance(scan_data, list) else [])
        if not isinstance(scan_results, list):
            scan_results = []

        index = merge_scan_results(index, scan_results)
        path = save_index(index, args.output)
        print(json.dumps({'status': 'merged', 'count': len(scan_results),
                          'total': len(index['relays']), 'saved': path}, indent=2))

    elif args.command == 'trusted':
        trusted = get_trusted(index)
        print(json.dumps(trusted, indent=2))

    elif args.command == 'markers':
        markers = format_markers(index)
        print(json.dumps(markers, indent=2))

    elif args.command == 'summary':
        print_summary(index)


if __name__ == '__main__':
    main()
