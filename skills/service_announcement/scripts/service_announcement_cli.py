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
NIP-89 Service Announcement CLI.

Register, list, and discover Nostr services (Kind 31990).

Usage:
    register   --id <service_id> --title <title> [--description <desc>] [--alt <alt>]
              [--relays <urls>]
    list       [--author <hex_pubkey>]
    discover   [--search <term>] [--limit <count>]
"""

import argparse
import asyncio
import json
import os
import sys
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SIGNER_URL = os.environ.get('NOSTR_SIGNER_URL', 'http://nostr-signer:8080')
RELAYS_ENV = os.environ.get('NOSTR_RELAYS', '')
if not RELAYS_ENV:
    print('[ERROR] NOSTR_RELAYS environment variable not set.', file=sys.stderr)
    sys.exit(1)
RELAYS = [r.strip() for r in RELAYS_ENV.split(',') if r.strip()]


def _fetch_pubkey() -> str:
    """Fetch agent public key hex from signer."""
    url = f"{SIGNER_URL.rstrip('/')}/public_key"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data.get('public_key_hex', '')
    except Exception as e:
        print(f'[ERROR] Failed to fetch public key: {e}', file=sys.stderr)
        sys.exit(1)


def _sign_event(kind: int, content: str, tags: list) -> dict:
    """Sign an event via the isolated signer service."""
    url = f"{SIGNER_URL.rstrip('/')}/sign"
    payload = {
        'kind': kind,
        'content': content,
        'tags': tags,
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f'[ERROR] Signing failed: {e}', file=sys.stderr)
        sys.exit(1)


def _publish_event(event_json: dict) -> None:
    """Publish a signed event to all configured relays using nostr-sdk."""
    try:
        from nostr_sdk import Client, Event, Keys, NostrSigner, RelayUrl
    except ImportError:
        print('[ERROR] nostr-sdk not installed. Run: pip install nostr-sdk', file=sys.stderr)
        sys.exit(1)

    async def _publish():
        dummy_keys = Keys.generate()
        signer = NostrSigner.keys(dummy_keys)
        client = Client(signer)

        for r_url in RELAYS:
            try:
                await client.add_relay(RelayUrl.parse(r_url))
            except Exception:
                pass  # skip unreachable

        await client.connect()
        event = Event.from_json(json.dumps(event_json))
        await client.send_event(event)
        await client.disconnect()

    asyncio.run(_publish())


def cmd_register(args) -> None:
    """Register a new service via Kind 31990 event."""
    service_id = args.id
    title = args.title
    description = args.description or ''
    alt = args.alt or ''
    relay_hints = args.relays or RELAYS_ENV
    pubkey = _fetch_pubkey()

    content = json.dumps({
        'name': title,
        'description': description,
    })

    tags = [
        ['d', service_id],
        ['title', title],
        ['description', description],
        ['alt', alt],
        ['relays', relay_hints],
        ['p', pubkey],
    ]

    print(f'[INFO] Signing Kind 31990 event for service: {service_id}')
    signed = _sign_event(31990, content, tags)

    print(f'[INFO] Publishing to {len(RELAYS)} relay(s)...')
    _publish_event(signed)

    event_id = signed.get('id', 'unknown')
    print(f'[OK] Service registered — ID: {event_id[:16]}...')
    print(f'     Service: {service_id}')
    print(f'     Title:   {title}')


def cmd_list(args) -> None:
    """List services announced by a given author (default: self)."""
    try:
        from nostr_sdk import Client, Filter, Keys, Kind as NKind, NostrSigner, RelayUrl, Timestamp
    except ImportError:
        print('[ERROR] nostr-sdk not installed. Run: pip install nostr-sdk', file=sys.stderr)
        sys.exit(1)

    author_hex = args.author or _fetch_pubkey()

    async def _list():
        from datetime import timedelta
        dummy_keys = Keys.generate()
        signer = NostrSigner.keys(dummy_keys)
        client = Client(signer)

        for r_url in RELAYS:
            try:
                await client.add_relay(RelayUrl.parse(r_url))
            except Exception:
                pass
        await client.connect()

        since = Timestamp.from_secs(0)
        filter_ = (
            Filter()
            .kind(NKind(31990))
            .author(PublicKey.parse(author_hex))
            .since(since)
        )
        events = await client.fetch_events(filter_, timedelta(seconds=10))
        await client.disconnect()

        results = []
        for ev in events.to_vec():
            raw_tags = [t.as_vec() for t in ev.tags().to_vec()]
            tags_dict = {t[0]: t[1] if len(t) > 1 else '' for t in raw_tags if t}
            results.append({
                'id': ev.id().to_hex(),
                'title': tags_dict.get('title', ''),
                'service_id': tags_dict.get('d', ''),
                'description': tags_dict.get('description', ''),
                'alt': tags_dict.get('alt', ''),
                'created_at': ev.created_at().as_secs(),
            })

        if not results:
            print(f'No services found for author: {author_hex[:16]}...')
            return

        print(f'{len(results)} service(s) found for {author_hex[:16]}...:')
        for i, svc in enumerate(results, 1):
            print('')
            print(f'  [{i}] {svc["title"]}')
            print(f'      ID:  {svc["service_id"]}')
            print(f'      Alt: {svc["alt"]}')

    # Import PublicKey here since it's also from nostr_sdk
    from nostr_sdk import PublicKey
    asyncio.run(_list())


def cmd_discover(args) -> None:
    """Discover services from any agent on configured relays."""
    try:
        from nostr_sdk import (
            Client, Filter, Keys, Kind as NKind, NostrSigner,
            RelayUrl, Timestamp,
        )
    except ImportError:
        print('[ERROR] nostr-sdk not installed. Run: pip install nostr-sdk', file=sys.stderr)
        sys.exit(1)

    search_term = (args.search or '').lower()
    limit = args.limit

    async def _discover():
        from datetime import timedelta
        dummy_keys = Keys.generate()
        signer = NostrSigner.keys(dummy_keys)
        client = Client(signer)

        for r_url in RELAYS:
            try:
                await client.add_relay(RelayUrl.parse(r_url))
            except Exception:
                pass
        await client.connect()

        since = Timestamp.from_secs(0)
        filter_ = Filter().kind(NKind(31990)).since(since)
        events = await client.fetch_events(filter_, timedelta(seconds=10))
        await client.disconnect()

        results = []
        for ev in events.to_vec():
            ev_id = ev.id().to_hex()
            author = ev.author().to_hex()
            raw_tags = [t.as_vec() for t in ev.tags().to_vec()]
            tags_dict = {t[0]: t[1] if len(t) > 1 else '' for t in raw_tags if t}
            title = tags_dict.get('title', '')
            service_id = tags_dict.get('d', '')
            desc = tags_dict.get('description', '')
            alt = tags_dict.get('alt', '')

            # Filter by search term if provided
            if search_term:
                searchable = f'{title} {service_id} {desc} {alt}'.lower()
                if search_term not in searchable:
                    continue

            results.append({
                'id': ev_id,
                'author': author,
                'title': title,
                'service_id': service_id,
                'alt': alt,
                'created_at': ev.created_at().as_secs(),
            })

            if len(results) >= limit:
                break

        if not results:
            msg = f' matching "{search_term}"' if search_term else ''
            print(f'[INFO] No services found{msg}.')
            return

        print(f'[OK] {len(results)} service(s) found:')
        for i, svc in enumerate(results, 1):
            print('')
            print(f'  [{i}] {svc["title"]}')
            print(f'      Agent:  {svc["author"][:16]}...')
            print(f'      ID:     {svc["service_id"]}')
            print(f'      Alt:    {svc["alt"]}')

    asyncio.run(_discover())


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description='NIP-89 Service Announcement CLI'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # register
    p_reg = sub.add_parser('register', help='Register a new service (Kind 31990)')
    p_reg.add_argument(
        '--id', '-i', required=True,
        help='Unique service identifier (e.g. agent.bob/relay-scan)'
    )
    p_reg.add_argument('--title', required=True, help='Human-readable service title')
    p_reg.add_argument('--description', default='', help='Detailed service description')
    p_reg.add_argument('--alt', default='', help='Alt text — what users should DM')
    p_reg.add_argument('--relays', default='', help='Comma-separated relay URLs for announcement')

    # list
    p_list = sub.add_parser('list', help='List services from an author (default: self)')
    p_list.add_argument('--author', default='', help='64-char hex pubkey of the service author')

    # discover
    p_disc = sub.add_parser('discover', help='Discover services from any agent')
    p_disc.add_argument('--search', default='', help='Filter by keyword in title/description')
    p_disc.add_argument('--limit', type=int, default=10, help='Max results')

    parsed = parser.parse_args()

    if parsed.command == 'register':
        cmd_register(parsed)
    elif parsed.command == 'list':
        cmd_list(parsed)
    elif parsed.command == 'discover':
        cmd_discover(parsed)


if __name__ == '__main__':
    main()
