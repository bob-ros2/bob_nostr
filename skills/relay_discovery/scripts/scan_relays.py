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
Relay Persistence Scanner.

Tests Nostr relays for connectivity, event storage, retrievability, NIP-11
metadata, and trust-level assessment.

Port of the live agent's relay_scanner logic with trust-level classification:
trusted, unstable, local, paywalled.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional
import urllib.request

from nostr_sdk import (
    Client, Event, Filter, Keys, Kind as NKind,
    NostrSigner, RelayUrl, Timestamp
)


def _parse_env(env_path: str) -> None:
    """Parse key-value pairs from an env file and set them in os.environ."""
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('\'"')
                    if key:
                        os.environ[key] = val
    except Exception:
        pass


def load_env_file() -> None:
    """Load variables from .env file into os.environ, checking various paths."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while True:
        env_path = os.path.join(current_dir, '.env')
        if os.path.exists(env_path):
            _parse_env(env_path)
            return
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent

    fallbacks = [
        '/ros2_ws/src/bob_nostr/.env',
        '/blue/dev/bob_nostr/ros2_ws/src/bob_nostr/.env'
    ]
    for path in fallbacks:
        if os.path.exists(path):
            _parse_env(path)
            return


def resolve_relays(relays_arg: Optional[str]) -> List[str]:
    """Resolve relay URLs from argument, env, or defaults."""
    if relays_arg:
        return [r.strip() for r in relays_arg.split(',') if r.strip()]

    relays_env = os.environ.get('EXTERNAL_NOSTR_RELAYS', '').strip()
    if not relays_env:
        relays_env = os.environ.get('NOSTR_RELAYS', '').strip()

    if relays_env:
        return [r.strip().strip('\'"') for r in relays_env.split(',') if r.strip()]

    # Fallback to default seed list
    default_relays = [
        'wss://nos.lol',
        'wss://relay.damus.io',
        'wss://relay.snort.social',
        'wss://relay.nostr.band',
        'wss://cache1.primal.net'
    ]
    return default_relays


def fetch_nip11(url: str, timeout: int = 10) -> Dict[str, Any]:
    """Fetch NIP-11 metadata from a relay's HTTP endpoint."""
    # Convert wss:// to https:// for NIP-11 endpoint
    http_url = url.replace('wss://', 'https://').replace('ws://', 'http://')
    http_url = http_url.rstrip('/')
    nip11_url = f'{http_url}/'

    headers = {'Accept': 'application/nostr+json'}
    try:
        req = urllib.request.Request(nip11_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body)
    except Exception:
        return {}


def classify_trust(
    nip11: Dict[str, Any],
    connected: bool,
    stored: bool,
    retrieved: bool
) -> str:
    """Classify relay into trust level."""
    if not connected:
        return 'dead'
    if nip11.get('limitation', {}).get('payment_required', False):
        return 'paywalled'
    if stored and retrieved:
        return 'trusted'
    if connected and not stored:
        return 'unstable'
    return 'unstable'


async def test_relay(client: Client, relay_url: str, timeout: int) -> Dict[str, Any]:
    """Test a single relay: connect, store event, retrieve, assess."""
    result: Dict[str, Any] = {
        'url': relay_url,
        'connected': False,
        'stored': False,
        'retrieved': False,
        'nip11': {},
        'trust': 'dead',
        'latency_ms': 0,
        'error': None,
        'tested_at': datetime.now(timezone.utc).isoformat()
    }

    start = time.time()

    # Test connectivity
    try:
        parsed = RelayUrl.parse(relay_url)
        await client.add_relay(parsed)
        await client.connect()
    except Exception as exc:
        result['error'] = str(exc)
        result['latency_ms'] = int((time.time() - start) * 1000)
        return result

    result['connected'] = True

    # Fetch NIP-11 in parallel (use thread for sync HTTP)
    nip11 = fetch_nip11(relay_url, timeout=timeout)
    result['nip11'] = nip11

    # Store a test event
    test_content = json.dumps({
        'test': 'persistence_check',
        'timestamp': int(time.time()),
        'relay': relay_url
    })

    dummy_keys = Keys.generate()
    test_event = Event(
        kind=NKind(1),
        content=test_content,
        tags=[['t', 'persistence_test'], ['expiration', str(int(time.time()) + 300)]],
        keys=dummy_keys,
        created_at=Timestamp.now()
    )
    signed_event = test_event.sign_hash()

    try:
        # Set a shorter timeout for the actual relay operations
        event_id = signed_event.id().to_hex()
        await asyncio.wait_for(client.send_event(signed_event), timeout=timeout)
        result['stored'] = True

        # Small delay to let relay process
        await asyncio.sleep(1)

        # Retrieve the event back
        try:
            f = Filter().kind(NKind(1)).id(event_id)
            retrieved_events = await asyncio.wait_for(
                client.get_events_of([f], 3 * timeout, False),
                timeout=timeout
            )
            for re in retrieved_events:
                if re.id().to_hex() == event_id:
                    result['retrieved'] = True
                    break
        except asyncio.TimeoutError:
            pass
    except asyncio.TimeoutError:
        result['error'] = 'Timeout during store/retrieve'
    except Exception as exc:
        result['error'] = str(exc)

    result['trust'] = classify_trust(
        nip11, result['connected'], result['stored'], result['retrieved']
    )
    result['latency_ms'] = int((time.time() - start) * 1000)

    return result


async def run_scans(
    relays: List[str],
    timeout: int,
    retention_check: bool = False
) -> List[Dict[str, Any]]:
    """Run persistence tests on all relays."""
    results = []

    for relay_url in relays:
        print(f'[*] Testing {relay_url}...')
        dummy_keys = Keys.generate()
        signer = NostrSigner.keys(dummy_keys)
        client = Client(signer)
        try:
            result = await test_relay(client, relay_url, timeout)
        except Exception as exc:
            result = {
                'url': relay_url,
                'connected': False,
                'stored': False,
                'retrieved': False,
                'nip11': {},
                'trust': 'dead',
                'latency_ms': 0,
                'error': str(exc),
                'tested_at': datetime.now(timezone.utc).isoformat()
            }
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        results.append(result)
        status = '✓' if result['trust'] == 'trusted' else '✗'
        print(f"  {status} {relay_url}: {result['trust']} "
              f"({result['latency_ms']}ms)")

        if result.get('error'):
            print(f"     Error: {result['error']}")

    return results


def main():
    load_env_file()

    parser = argparse.ArgumentParser(
        description='Relay Persistence Scanner – Test Nostr relay connectivity and storage'
    )
    parser.add_argument(
        '--relays', default=None,
        help='Comma-separated relay URLs (overrides env vars)'
    )
    parser.add_argument(
        '--timeout', type=int, default=20,
        help='Timeout per relay in seconds (default: 20)'
    )
    parser.add_argument(
        '--retention-check', action='store_true',
        help='Run retention test (not yet implemented)'
    )
    parser.add_argument(
        '--output', default=None,
        help='Path for JSON result file (default: stdout)'
    )
    args = parser.parse_args()

    relays = resolve_relays(args.relays)

    if not relays:
        print('[ERROR] No relays to scan.', file=sys.stderr)
        sys.exit(1)

    print(f'[*] Scanning {len(relays)} relay(s) with {args.timeout}s timeout...')
    if args.retention_check:
        print('[*] Note: Retention check is a placeholder; full implementation '
              'requires multi-pass tests over hours/days.')

    results = asyncio.run(run_scans(relays, args.timeout))

    summary = {
        'scan_type': 'persistence',
        'timestamp': int(time.time()),
        'total': len(results),
        'by_trust': {},
        'relays': results
    }
    for r in results:
        t = r['trust']
        summary['by_trust'][t] = summary['by_trust'].get(t, 0) + 1

    output_json = json.dumps(summary, indent=2)

    if args.output:
        output_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(output_json)
        print(f'\n[*] Results written to {output_path}')

    print('\n--- SCAN SUMMARY ---')
    print(f"    Total: {summary['total']}")
    for trust, count in sorted(summary['by_trust'].items()):
        print(f'    {trust}: {count}')
    print(f'\n{output_json}')


if __name__ == '__main__':
    main()
