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
CLI for agent_memory library (serialized/compressed Nostr memory operations).

Usage:
  python3 cli_agent_memory.py encode <type> -i <input.yaml> -o <output.json>
  python3 cli_agent_memory.py decode -i <input.json> -o <output.yaml>
  python3 cli_agent_memory.py list-types
  python3 cli_agent_memory.py publish -i <events.json> [--relays <urls>]
"""

import argparse
import json
import os
import sys

from api import AgentMemory
from registry import load_spec
import yaml


def cmd_encode(args):
    mem = AgentMemory()
    with open(args.input, encoding='utf-8') as f:
        if args.input.endswith(('.yaml', '.yml')):
            data = yaml.safe_load(f)
        elif args.input.endswith('.json'):
            data = json.load(f)
        else:
            # .md, .txt, or unknown – treat as raw string content
            data = f.read()
    events = mem.pack(args.type, data, compression=args.compress)
    with open(args.output, 'w') as f:
        json.dump(events, f, indent=2)
    print(f'  Encoded {len(events)} event(s) -> {args.output}')


def cmd_decode(args):
    mem = AgentMemory()
    with open(args.input) as f:
        events = json.load(f)
    result = mem.unpack(events)
    out = result['content']
    fmt = result.get('format', 'text')
    with open(args.output, 'w') as f:
        if fmt == 'yaml':
            yaml.dump(out, f, default_flow_style=False, allow_unicode=True)
        elif fmt == 'json':
            json.dump(out, f, indent=2)
        else:
            f.write(str(out))
    print(f"  Decoded ({result['type']}, {fmt}, encrypted={result['encrypted']}) -> {args.output}")


def cmd_list_types(args):
    spec = load_spec()
    print(f"\n  {'Name':<20} {'Kind':<8} {'Serializable':<14} {'Visibility':<12} Format")
    print(f"  {'-'*20} {'-'*8} {'-'*14} {'-'*12} {'-'*12}")
    for mt in spec.get('memory_types', []):
        print(f"  {mt['name']:<20} {mt['kind']:<8} {str(mt.get('serializable', False)):<14} "
              f"{mt.get('visibility', 'public'):<12} {mt.get('content_format', 'text')}")
    print()


def cmd_publish(args):
    """Publish packed events to Nostr relays via the signer."""
    relays_str = args.relays or os.environ.get('NOSTR_RELAYS', '')
    if not relays_str:
        print('[ERROR] No relays configured. '
              'Set NOSTR_RELAYS env var or use --relays.',
              file=sys.stderr)
        sys.exit(1)
    relays = [r.strip() for r in relays_str.split(',') if r.strip()]

    with open(args.input) as f:
        events = json.load(f)

    # _signer = SignerClient()  # unused
    print(f'  Publishing {len(events)} event(s) to {len(relays)} relay(s)...')

    # Use nostr-sdk client to send events to relays
    try:
        from nostr_sdk import Client, Event, Keys as SDKKeys, NostrSigner, RelayUrl
    except ImportError:
        print('[ERROR] nostr-sdk not installed. Run: pip install nostr-sdk', file=sys.stderr)
        sys.exit(1)

    dummy_keys = SDKKeys.generate()
    signer_obj = NostrSigner.keys(dummy_keys)
    client = Client(signer_obj)

    import asyncio

    async def _publish():
        for relay_url in relays:
            await client.add_relay(RelayUrl.parse(relay_url))
        await client.connect()

        for ev_data in events:
            # Convert dict event to Event JSON and send
            event_json = json.dumps({
                'id': ev_data.get('id', ''),
                'pubkey': ev_data.get('pubkey', ''),
                'created_at': ev_data.get('created_at', 0),
                'kind': ev_data['kind'],
                'tags': ev_data['tags'],
                'content': ev_data['content'],
                'sig': ev_data.get('sig', '')
            })
            event = Event.from_json(event_json)
            event_id = event.id().to_hex()
            await client.send_event(event)
            print(f'  [OK] Published event {event_id[:16]}...')

        await client.disconnect()
        print(f'  Done. {len(events)} event(s) published.')

    asyncio.run(_publish())


def main():
    parser = argparse.ArgumentParser(description='Agent Memory CLI – Serialized Nostr Storage')
    sub = parser.add_subparsers(dest='command', required=True)

    p_encode = sub.add_parser('encode', help='Encode data into Nostr events')
    p_encode.add_argument('type', help='Memory type (e.g. relay-index)')
    p_encode.add_argument('-i', '--input', required=True, help='Input file (yaml/json/md)')
    p_encode.add_argument('-o', '--output', default='events.json', help='Output file')
    p_encode.add_argument('--compress', default='none',
                          choices=['none', 'gz', 'tar.gz'],
                          help='Compression format (default: none)')

    p_decode = sub.add_parser('decode', help='Decode Nostr events into data')
    p_decode.add_argument('-i', '--input', required=True, help='Input events file (json)')
    p_decode.add_argument('-o', '--output', default='decoded.yaml', help='Output file')

    sub.add_parser('list-types', help='List all registered memory types')

    p_publish = sub.add_parser('publish', help='Publish packed events to Nostr relays')
    p_publish.add_argument(
        '-i', '--input', required=True,
        help='Input events file (json from encode)'
    )
    p_publish.add_argument(
        '--relays', default=None,
        help='Comma-separated relay URLs (overrides NOSTR_RELAYS)'
    )

    args = parser.parse_args()

    if args.command == 'encode':
        cmd_encode(args)
    elif args.command == 'decode':
        cmd_decode(args)
    elif args.command == 'list-types':
        cmd_list_types(args)
    elif args.command == 'publish':
        cmd_publish(args)


if __name__ == '__main__':
    main()
