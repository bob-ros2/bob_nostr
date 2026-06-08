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

"""Scan Nostr relays to identify potential autonomous agents and bots."""

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Dict, List

from nostr_sdk import (
    Client, Filter, HandleNotification, Keys, Kind as NKind,
    NostrSigner, RelayUrl, Timestamp
)

# Default fallback relays if environment variables are not set
DEFAULT_RELAYS = [
    'wss://relay.damus.io',
    'wss://nos.lol',
    'wss://relay.nostr.band',
    'wss://cache1.primal.net'
]

AGENT_TAGS = ['agent', 'bot', 'ai', 'autonomous']

# Tracking for frequency analysis
pubkey_history: Dict[str, List[float]] = {}
found_agents = set()


def _parse_env(env_path):
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


def load_env_file():
    """Load variables from .env file into os.environ, checking various paths."""
    # 1. Walk up from the script's directory
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

    # 2. Check standard container/workspace paths as fallback
    fallbacks = [
        '/ros2_ws/src/bob_nostr/.env',
        '/blue/dev/bob_nostr/ros2_ws/src/bob_nostr/.env'
    ]
    for path in fallbacks:
        if os.path.exists(path):
            _parse_env(path)
            return


async def main():
    """Run the agent scan discovery loop."""
    # Load .env file for local testing
    load_env_file()

    # Parse arguments
    parser = argparse.ArgumentParser(description='Nostr Agent Scan Tool')
    parser.add_argument('--limit', type=int, default=10, help='Max agents to find')
    parser.add_argument(
        '--window', type=int, default=10,
        help='Time window (seconds) for frequency analysis'
    )
    parser.add_argument(
        '--min-events', type=int, default=3,
        help='Min events in window to flag as agent'
    )
    parser.add_argument('--timeout', type=int, default=45, help='Scan timeout in seconds')
    args = parser.parse_args()

    # Resolve relays from env variable
    relays_env = os.environ.get('EXTERNAL_NOSTR_RELAYS', '').strip()
    if not relays_env:
        # Fallback to general NOSTR_RELAYS
        relays_env = os.environ.get('NOSTR_RELAYS', '').strip()

    if relays_env:
        relays = [r.strip().strip('\'"') for r in relays_env.split(',') if r.strip()]
    else:
        relays = DEFAULT_RELAYS

    print(f'[*] Starting Agent Discovery on {len(relays)} relays...')
    for r in relays:
        print(f'  - {r}')

    # Initialize client with dummy keys since we are only listening/subscribing
    dummy_keys = Keys.generate()
    signer = NostrSigner.keys(dummy_keys)
    client = Client(signer)

    # Add relays
    for r_url in relays:
        try:
            await client.add_relay(RelayUrl.parse(r_url))
        except Exception as e:
            print(f'[!] Error parsing/adding relay {r_url}: {e}', file=sys.stderr)

    try:
        await client.connect()
        print('[*] Connected to relays.')
    except Exception as e:
        print(f'[!] Failed to connect to relays: {e}', file=sys.stderr)
        sys.exit(1)

    # Subscribe to Kind 1 (Text notes) to analyze messages
    # We only care about events starting from now
    since_time = Timestamp.now()
    subscribe_filter = Filter().kind(NKind(1)).since(since_time)
    await client.subscribe(subscribe_filter, None)

    stop_event = asyncio.Event()

    async def handle_event(event):
        pubkey = event.author().to_hex()
        tags = [tag.as_vec() for tag in event.tags().to_vec()]

        # Check 1: Specific Tags
        is_agent_tag = False
        for tag in tags:
            if not tag:
                continue
            if tag[0] == 't' and len(tag) > 1 and tag[1].lower() in AGENT_TAGS:
                is_agent_tag = True
                break
            if tag[0].lower() in AGENT_TAGS:
                is_agent_tag = True
                break

        # Check 2: Frequency Analysis
        now = time.time()
        if pubkey not in pubkey_history:
            pubkey_history[pubkey] = []

        pubkey_history[pubkey].append(now)
        # Clean old timestamps
        pubkey_history[pubkey] = [
            t for t in pubkey_history[pubkey]
            if now - t < args.window
        ]

        is_high_frequency = len(pubkey_history[pubkey]) >= args.min_events

        if is_agent_tag or is_high_frequency:
            if pubkey not in found_agents:
                reason = 'Tag Match' if is_agent_tag else 'High Frequency'
                print(f'[!] Potential Agent Found: {pubkey} (Reason: {reason})')
                found_agents.add(pubkey)
                if len(found_agents) >= args.limit:
                    stop_event.set()

    class DiscoveryHandler(HandleNotification):
        async def handle(self, relay_url, subscription_id, event):
            asyncio.create_task(handle_event(event))

        async def handle_msg(self, relay_url, msg):
            pass

    # Start handling notifications in a background task
    handler_task = asyncio.create_task(client.handle_notifications(DiscoveryHandler()))

    # Wait for the limit or timeout
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=float(args.timeout))
    except asyncio.TimeoutError:
        print(f'[*] Scan timeout of {args.timeout} seconds reached.')

    # Graceful shutdown
    print('[*] Shutting down connection...')
    try:
        await client.shutdown()
    except Exception as e:
        print(f'[!] Error during client shutdown: {e}', file=sys.stderr)

    handler_task.cancel()
    try:
        await handler_task
    except asyncio.CancelledError:
        pass

    # Output results in a format the LLM or user can parse
    result = {
        'status': 'success',
        'timestamp': int(time.time()),
        'relays_scanned': relays,
        'agents_found_count': len(found_agents),
        'agents': list(found_agents)
    }

    print('\n--- DISCOVERY RESULTS ---')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[*] Interrupted by user.')
        sys.exit(0)
