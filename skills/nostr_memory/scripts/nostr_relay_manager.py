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

"""Nostr Relay Manager – Status and connectivity checker for Nostr relays."""

import argparse
import os
import socket
import sys
import urllib.parse


def load_env_file():
    """Load variables from .env file into os.environ if it exists."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while True:
        env_path = os.path.join(current_dir, '.env')
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            key, val = line.split('=', 1)
                            key = key.strip()
                            val = val.strip().strip("'\"")
                            if key and key not in os.environ:
                                os.environ[key] = val
            except Exception:
                pass
            break
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent


def resolve_host_urls():
    """Resolve container names to host ports when outside docker."""
    in_docker = (
        os.path.exists('/.dockerenv') or
        os.environ.get('ROS_NAMESPACE') is not None
    )
    if not in_docker:
        import socket
        try:
            socket.gethostbyname('nostr-signer')
            in_docker = True
        except socket.gaierror:
            in_docker = False

    # Map remote signer URL
    signer_url = os.environ.get('NOSTR_SIGNER_URL', '')
    if signer_url and not in_docker and 'nostr-signer:8080' in signer_url:
        resolved_signer = signer_url.replace(
            'nostr-signer:8080', 'localhost:8080'
        )
        os.environ['NOSTR_SIGNER_URL'] = resolved_signer

    # Map relay URLs
    relays_env = os.environ.get('NOSTR_RELAYS', '')
    if relays_env and not in_docker:
        relays = [r.strip() for r in relays_env.split(',') if r.strip()]
        mapped = []
        for r in relays:
            if 'nostr-relay-1:8080' in r:
                mapped.append(r.replace(
                    'nostr-relay-1:8080', 'localhost:8781'
                ))
            elif 'nostr-relay-2:8080' in r:
                mapped.append(r.replace(
                    'nostr-relay-2:8080', 'localhost:8782'
                ))
            else:
                mapped.append(r)
        os.environ['NOSTR_RELAYS'] = ','.join(mapped)


load_env_file()
resolve_host_urls()


def check_relay_reachable(relay_url, timeout=2):
    """Check reachability of a single Nostr relay using a socket connection."""
    try:
        parsed = urllib.parse.urlparse(relay_url)
        host = parsed.hostname
        port = parsed.port
        if not port:
            port = 443 if parsed.scheme in ('wss', 'https') else 80
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except Exception as e:
        return False, str(e)


def main():
    """Run diagnostics to check the connectivity of the configured relays."""
    parser = argparse.ArgumentParser(description='Nostr Relay Manager')
    parser.add_argument(
        '--action', required=False, default='status',
        choices=['status', 'test', 'start', 'stop', 'restart', 'logs',
                 'clean'],
        help='Action to execute'
    )
    parser.add_argument(
        '--relay', default='all',
        help='Relay name/URL (ignored, kept for compatibility)'
    )
    parser.add_argument(
        '--lines', type=int, default=50,
        help='Number of lines for logs (ignored)'
    )
    parser.add_argument(
        '--confirm', action='store_true',
        help='Confirms local starting of relays (ignored)'
    )
    args = parser.parse_args()

    # Load relays from environmental variable
    relays_env = os.environ.get('NOSTR_RELAYS', '')
    if not relays_env:
        print(
            '[ERROR] NOSTR_RELAYS environment variable is not set.',
            file=sys.stderr
        )
        print(
            'Please configure it in your .env file or export it, e.g.:',
            file=sys.stderr
        )
        print(
            'export NOSTR_RELAYS="ws://localhost:8781,ws://localhost:8782"',
            file=sys.stderr
        )
        sys.exit(1)

    relays = [r.strip() for r in relays_env.split(',') if r.strip()]

    if args.action in ['start', 'stop', 'restart', 'clean', 'logs']:
        print(
            f"[ERROR] Action '{args.action}' "
            'is no longer supported by the relay manager.',
            file=sys.stderr
        )
        print(
            'Managing relay containers should be handled '
            'externally via Docker Compose directly.',
            file=sys.stderr
        )
        print(
            'This script now only supports checking status / '
            'connectivity of the configured relays.',
            file=sys.stderr
        )
        sys.exit(1)

    # For status and test actions:
    print('🔍 Checking Nostr relays connectivity...')
    all_reachable = True
    any_reachable = False

    for r in relays:
        reachable, err = check_relay_reachable(r)
        if reachable:
            print(f'  ✅ {r}: Reachable')
            any_reachable = True
        else:
            print(f'  ❌ {r}: Unreachable ({err})')
            all_reachable = False

    if not any_reachable:
        print(
            '[ERROR] None of the configured Nostr relays are reachable!',
            file=sys.stderr
        )
        sys.exit(1)
    elif not all_reachable:
        print(
            '[WARNING] Some Nostr relays are unreachable, '
            'but at least one is online.',
            file=sys.stderr
        )
        sys.exit(0)
    else:
        print('✅ All Nostr relays are reachable.')
        sys.exit(0)


if __name__ == '__main__':
    main()
