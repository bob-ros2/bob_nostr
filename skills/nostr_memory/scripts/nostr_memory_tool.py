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
Nostr Memory Tool – Decentralized agent memory via Nostr protocol.

Enables storing, searching, and retrieving agent memories
as signed Nostr events on 3 local relays.

Usage:
    python3 nostr_memory_tool.py --action store --kind 5000 --content '...'
    python3 nostr_memory_tool.py --action search --kind 5000 --limit 5
    python3 nostr_memory_tool.py --action get_status
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import time


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


load_env_file()


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


resolve_host_urls()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Configure relays from environment variable only
NOSTR_RELAYS_ENV = os.environ.get('NOSTR_RELAYS', '')
if not NOSTR_RELAYS_ENV:
    print(
        '[ERROR] NOSTR_RELAYS environment variable is not configured.',
        file=sys.stderr
    )
    print(
        'Please set it in your environment or .env file, e.g.:',
        file=sys.stderr
    )
    print(
        'export NOSTR_RELAYS="ws://localhost:8781,ws://localhost:8782"',
        file=sys.stderr
    )
    sys.exit(1)

DEFAULT_RELAYS = [r.strip() for r in NOSTR_RELAYS_ENV.split(',') if r.strip()]


# Agent Memory Event Kinds
KIND_TEXT_NOTE = 1
KIND_AGENT_MEMORY = 5000       # Structured Agent Memory
KIND_AGENT_STATE = 30000       # Replaceable Agent State (parameterized)
KIND_AGENT_LOG = 5001          # System logs / Event log
KIND_AGENT_DIALOG = 5002       # Conversation history / Dialog context
KIND_DELETION = 5              # Deletion event


# ---------------------------------------------------------------------------
# Nostr Client (asynchronous, using nostr-sdk)
# ---------------------------------------------------------------------------

class NostrMemoryClient:
    """Wraps the nostr-sdk client for agent memory operations."""

    def __init__(self, relays=None, secret_key=None, signer_url=None):
        """Initialize the client."""
        self.relays = relays or DEFAULT_RELAYS
        self._secret_key = secret_key or os.environ.get(
            'NOSTR_AGENT_SECRET', ''
        )
        self.signer_url = signer_url or os.environ.get('NOSTR_SIGNER_URL', '')
        self._keys = None
        self._client = None

    def _ensure_keys(self):
        """Ensure that a keypair exists (generate or load)."""
        if self._keys is not None:
            return self._keys

        try:
            from nostr_sdk import Keys
        except ImportError:
            print(
                '[ERROR] nostr-sdk not installed. '
                'Run: pip install nostr-sdk',
                file=sys.stderr
            )
            sys.exit(1)

        if self._secret_key:
            try:
                self._keys = Keys.parse(self._secret_key)
                print(f'[INFO] Agent Public Key: '
                      f'{self._keys.public_key().to_bech32()}',
                      file=sys.stderr)
            except Exception as e:
                print(f'[ERROR] Invalid Secret Key: {e}', file=sys.stderr)
                sys.exit(1)
        else:
            # No key present => generate and output
            self._keys = Keys.generate()
            secret_hex = self._keys.secret_key().to_hex()
            pub_bech32 = self._keys.public_key().to_bech32()
            print('[INFO] 🔑 New keypair generated!', file=sys.stderr)
            print(f'[INFO] Public Key (npub): {pub_bech32}', file=sys.stderr)
            print(f'[INFO] Secret Key (Hex):  {secret_hex}', file=sys.stderr)
            print(
                '[INFO] Set NOSTR_AGENT_SECRET=... '
                'for a persistent identity.',
                file=sys.stderr
            )

        return self._keys

    def _get_pubkey_hex(self):
        """Get the public key hex of the agent."""
        if hasattr(self, '_cached_pubkey_hex') and self._cached_pubkey_hex:
            return self._cached_pubkey_hex

        if self.signer_url:
            import urllib.request
            url = f"{self.signer_url.rstrip('/')}/public_key"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=5) as response:
                    resp = json.loads(response.read().decode('utf-8'))
                self._cached_pubkey_hex = resp.get('public_key_hex')
                return self._cached_pubkey_hex
            except Exception as e:
                print(f'[ERROR] Failed to query signer pubkey: {e}',
                      file=sys.stderr)
                return None
        else:
            keys = self._ensure_keys()
            self._cached_pubkey_hex = keys.public_key().to_hex()
            return self._cached_pubkey_hex

    async def encrypt_content(self, content: str) -> str:
        """Encrypt content using NIP-44 self-encryption."""
        pubkey_hex = self._get_pubkey_hex()
        if not pubkey_hex:
            raise ValueError(
                'Cannot encrypt: Agent public key could not be determined.'
            )

        if self.signer_url:
            import urllib.request
            url = f"{self.signer_url.rstrip('/')}/nip44_encrypt"
            payload = {
                'peer_public_key': pubkey_hex,
                'content': content
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url, data=data, headers={'Content-Type': 'application/json'}
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    resp = json.loads(response.read().decode('utf-8'))
                return resp.get('encrypted_content')
            except Exception as e:
                print(f'[ERROR] Remote encryption failed: {e}',
                      file=sys.stderr)
                return None
        else:
            try:
                from nostr_sdk import nip44_encrypt, PublicKey, Nip44Version
                keys = self._ensure_keys()
                peer_pub = PublicKey.parse(pubkey_hex)
                return nip44_encrypt(
                    keys.secret_key(), peer_pub, content, Nip44Version.V2
                )
            except Exception as e:
                print(f'[ERROR] Local encryption failed: {e}',
                      file=sys.stderr)
                return None

    async def decrypt_content(self, encrypted_content: str) -> str:
        """Decrypt content using NIP-44 self-encryption."""
        pubkey_hex = self._get_pubkey_hex()
        if not pubkey_hex:
            raise ValueError(
                'Cannot decrypt: Agent public key could not be determined.'
            )

        if self.signer_url:
            import urllib.request
            url = f"{self.signer_url.rstrip('/')}/nip44_decrypt"
            payload = {
                'peer_public_key': pubkey_hex,
                'payload': encrypted_content
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url, data=data, headers={'Content-Type': 'application/json'}
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    resp = json.loads(response.read().decode('utf-8'))
                return resp.get('decrypted_content')
            except Exception as e:
                print(f'[ERROR] Remote decryption failed: {e}',
                      file=sys.stderr)
                return None
        else:
            try:
                from nostr_sdk import nip44_decrypt, PublicKey
                keys = self._ensure_keys()
                peer_pub = PublicKey.parse(pubkey_hex)
                return nip44_decrypt(
                    keys.secret_key(), peer_pub, encrypted_content
                )
            except Exception as e:
                print(f'[ERROR] Local decryption failed: {e}',
                      file=sys.stderr)
                return None

    async def _get_client(self):
        """Initialize or return the nostr-sdk client."""
        if self._client is not None:
            return self._client

        try:
            from nostr_sdk import Client, NostrSigner
        except ImportError:
            print('[ERROR] nostr-sdk not installed.', file=sys.stderr)
            sys.exit(1)

        # Check reachability of the relays before attempting to start/connect
        import urllib.parse
        import socket

        reachable_relays = []
        for relay_url in self.relays:
            try:
                parsed = urllib.parse.urlparse(relay_url)
                host = parsed.hostname
                port = parsed.port
                if not port:
                    port = 443 if parsed.scheme in ('wss', 'https') else 80
                with socket.create_connection((host, port), timeout=2):
                    reachable_relays.append(relay_url)
            except Exception as e:
                print(f'[WARNING] Relay {relay_url} is unreachable: {e}',
                      file=sys.stderr)

        if not reachable_relays:
            print('[ERROR] None of the configured Nostr relays are reachable.',
                  file=sys.stderr)
            sys.exit(1)

        if self.signer_url:
            # When using a remote signer, the client doesn't need to load the
            # real agent key. We initialize the client with a dummy keypair
            # to satisfy nostr-sdk's signer requirement.
            from nostr_sdk import Keys as SDKKeys
            dummy_keys = SDKKeys.generate()
            signer = NostrSigner.keys(dummy_keys)
        else:
            keys = self._ensure_keys()
            signer = NostrSigner.keys(keys)
        client = Client(signer)

        from nostr_sdk import RelayUrl
        for relay_url in reachable_relays:
            await client.add_relay(RelayUrl.parse(relay_url))

        await client.connect()
        self._client = client
        return client

    async def store_event(self, kind: int, content: str, tags: list = None,
                          encrypt: bool = None):
        """Create and send a signed Nostr event to all relays."""
        try:
            from nostr_sdk import Tag, Kind as NKind, EventBuilder, Event
        except ImportError:
            print('[ERROR] nostr-sdk not installed.', file=sys.stderr)
            sys.exit(1)

        client = await self._get_client()
        tags = tags or []

        # Auto-encrypt all event kinds except Kind 1 (Text Note) if not explicitly specified
        should_encrypt = encrypt
        if should_encrypt is None:
            should_encrypt = (kind != KIND_TEXT_NOTE)

        if should_encrypt:
            encrypted = await self.encrypt_content(content)
            if encrypted:
                content = encrypted
                if not any(t[0] == 'encrypted' for t in tags):
                    tags.append(['encrypted', 'nip44'])

        if self.signer_url:
            # Sign the event using the remote signing service
            import urllib.request
            import urllib.error
            url = f"{self.signer_url.rstrip('/')}/sign"
            payload = {
                'kind': kind,
                'content': content,
                'tags': tags
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url, data=data, headers={'Content-Type': 'application/json'}
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    resp_json = response.read().decode('utf-8')
                event = Event.from_json(resp_json)
            except Exception as e:
                print(f'[ERROR] Remote signing failed: {e}', file=sys.stderr)
                return None
        else:
            # Convert Python tags to nostr-sdk Tag objects
            sdk_tags = []
            for t in tags:
                if len(t) >= 2:
                    sdk_tags.append(Tag.parse([t[0], t[1]]))

            # Build, sign and send event locally
            keys = self._ensure_keys()
            event = EventBuilder(
                NKind(kind), content
            ).tags(sdk_tags).sign_with_keys(keys)

        await client.send_event(event)

        event_id_hex = event.id().to_hex()
        print(f'✅ Event saved | Kind: {kind} | ID: {event_id_hex[:16]}...')

        return event_id_hex

    async def fetch_events(self, kind: int = None, limit: int = 10,
                           since: int = 0, until: int = 0,
                           authors: list = None,
                           event_ids: list = None,
                           tag_filter: list = None,
                           decrypt: bool = True):
        """Retrieve events from relays (newest first)."""
        try:
            from nostr_sdk import Filter, Kind as NKind, EventId
        except ImportError as e:
            print(f'[ERROR] nostr-sdk not installed: {e}', file=sys.stderr)
            sys.exit(1)

        client = await self._get_client()

        # Build filter
        sk_filter = Filter().limit(limit)
        if kind is not None:
            sk_filter = sk_filter.kind(NKind(kind))
        if since > 0:
            sk_filter = sk_filter.since(since)
        if until > 0:
            from nostr_sdk import Timestamp
            sk_filter = sk_filter.until(Timestamp.from_secs(until))
        if tag_filter:
            from nostr_sdk import SingleLetterTag, Alphabet
            for tag_entry in tag_filter:
                if len(tag_entry) >= 2:
                    tag_key = tag_entry[0]
                    if len(tag_key) == 1 and tag_key.isalpha():
                        alphabet_letter = getattr(Alphabet, tag_key.upper(), None)
                        if alphabet_letter is not None:
                            sk_filter = sk_filter.custom_tag(
                                SingleLetterTag.lowercase(alphabet_letter),
                                tag_entry[1]
                            )
                        else:
                            print(
                                f'[WARNING] Unknown single-letter tag "{tag_key}", '
                                f'skipping.',
                                file=sys.stderr
                            )
                    else:
                        print(
                            f'[WARNING] Invalid tag key "{tag_key}" — '
                            f'must be a single letter. Skipping.',
                            file=sys.stderr
                        )
        if authors:
            from nostr_sdk import PublicKey
            author_keys = [PublicKey.parse(a) for a in authors]
            sk_filter = sk_filter.authors(author_keys)
        if event_ids:
            sdk_ids = []
            for eid in event_ids:
                if isinstance(eid, str):
                    sdk_ids.append(EventId.parse(eid))
                else:
                    sdk_ids.append(eid)
            sk_filter = sk_filter.ids(sdk_ids)

        # Start subscription, collect events
        events = await client.fetch_events(sk_filter, timedelta(seconds=5))

        results = []
        for event in events.to_vec():
            tags = [t.as_vec() for t in event.tags().to_vec()]
            content = event.content()

            # Automatically decrypt if event has 'encrypted' tag
            is_encrypted = any(
                t[0] == 'encrypted' and len(t) > 1 and t[1] == 'nip44'
                for t in tags
            )
            if is_encrypted and decrypt:
                try:
                    decrypted = await self.decrypt_content(content)
                    if decrypted is not None:
                        content = decrypted
                except Exception as e:
                    print(
                        f'[WARNING] Failed to decrypt event '
                        f'{event.id().to_hex()[:16]}: {e}',
                        file=sys.stderr
                    )

            results.append({
                'id': event.id().to_hex(),
                'pubkey': event.author().to_hex(),
                'created_at': event.created_at().as_secs(),
                'kind': event.kind().as_u16(),
                'tags': tags,
                'content': content,
            })

        # Sort descending by created_at (newest first)
        results.sort(key=lambda e: e['created_at'], reverse=True)

        return results

    async def get_agent_state(self):
        """Retrieve the current agent status (Kind 30000)."""
        events = await self.fetch_events(kind=KIND_AGENT_STATE, limit=1)
        if events:
            return (
                json.loads(events[0]['content'])
                if events[0]['content'] else {}
            )
        return {}

    async def set_agent_state(self, state_dict: dict, encrypt: bool = None):
        """Store the agent status (Kind 30000, replaceable)."""
        content = json.dumps(state_dict, ensure_ascii=False)
        tags = [['d', 'agent_state']]
        return await self.store_event(
            KIND_AGENT_STATE, content, tags, encrypt=encrypt
        )

    async def delete_event(self, event_id_hex: str):
        """Send a deletion event (Kind 5) for a specific event ID."""
        content = json.dumps([event_id_hex])
        tags = [['e', event_id_hex]]
        return await self.store_event(KIND_DELETION, content, tags)

    async def disconnect(self):
        """Disconnect WebSocket connections."""
        if self._client:
            await self._client.disconnect()
            print('[INFO] Connections disconnected.', file=sys.stderr)

    async def list_keys_info(self):
        """Display the current key information."""
        if self.signer_url:
            import urllib.request
            url = f"{self.signer_url.rstrip('/')}/public_key"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=5) as response:
                    resp = json.loads(response.read().decode('utf-8'))
                pub_hex = resp.get('public_key_hex')
                pub_npub = resp.get('public_key')
                print(f'Public Key (Hex):  {pub_hex}')
                print(f'Public Key (npub): {pub_npub}')
                print(f'Signer URL:        {self.signer_url}')
                print(
                    '🔒 Private Key:    [PROTECTED] '
                    '(Managed by isolated signer container)'
                )
            except Exception as e:
                print(
                    f'[ERROR] Failed to query public key from signer: {e}',
                    file=sys.stderr
                )
        else:
            keys = self._ensure_keys()
            pub_hex = keys.public_key().to_hex()
            pub_npub = keys.public_key().to_bech32()
            print(f'Public Key (Hex):  {pub_hex}')
            print(f'Public Key (npub): {pub_npub}')
            if self._secret_key:
                print(
                    f'Secret Key (Hex):  {self._secret_key[:8]}... '
                    '(configured)'
                )
            else:
                print('⚠️  No Secret Key set – temporary key.')


# ---------------------------------------------------------------------------
# CLI Arguments & Main
# ---------------------------------------------------------------------------

def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Nostr Memory Tool – Decentralized Agent Memory'
    )
    parser.add_argument('--action', required=True,
                        choices=['store', 'get', 'search', 'delete',
                                 'set_status', 'get_status', 'list_keys'],
                        help='Action to execute')
    parser.add_argument(
        '--kind', type=int, default=KIND_AGENT_MEMORY,
        help=f'Nostr Event Kind (default: {KIND_AGENT_MEMORY})'
    )
    parser.add_argument('--content', default='',
                        help='Event content (JSON string or text)')
    parser.add_argument('--event-id', default='',
                        help='Event ID (hex) to retrieve/delete')
    parser.add_argument('--tags', default='',
                        help='Comma-separated tags, e.g. "ros2,memory"')
    # Alias for compatibility – allow --tag as singular form
    parser.add_argument('--tag', dest='tags', default='',
                        help='Alias for --tags (single or comma-separated)')
    parser.add_argument('--limit', type=int, default=10,
                        help='Maximum number of matches in search')
    parser.add_argument('--since', type=int, default=0,
                        help='Unix timestamp – only newer events')
    parser.add_argument('--until', type=int, default=0,
                        help='Unix timestamp – only events older than this')
    parser.add_argument('--authors', default='',
                        help='Comma-separated author pubkeys (hex)')
    parser.add_argument('--tag-filter', default='',
                        help='JSON array of tag filters, e.g. \'[["t","ros2"]]\'')
    parser.add_argument('--relays', default='',
                        help='Comma-separated relay URLs (Override)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON (for machine processing)')
    parser.add_argument(
        '--encrypt', dest='encrypt', action='store_true',
        help='Force encryption of the event content using NIP-44'
    )
    parser.add_argument(
        '--no-encrypt', dest='encrypt', action='store_false',
        help='Force saving event content in plain text (unencrypted)'
    )
    parser.set_defaults(encrypt=None)

    return parser.parse_args()


def _build_tags(tag_str: str, kind: int) -> list:
    """Build Nostr tags from comma-separated string."""
    tags = []
    if tag_str:
        for t in tag_str.split(','):
            t = t.strip()
            if t:
                tags.append(['t', t])
    # For Kind 30000: d-tag for replaceability
    if kind == KIND_AGENT_STATE:
        if not any(t[0] == 'd' for t in tags):
            tags.append(['d', 'agent_state'])
    return tags


def _format_event(ev: dict, json_output: bool = False) -> str:
    """Format an event for output."""
    if json_output:
        return json.dumps(ev, ensure_ascii=False, indent=2)

    created = datetime.fromtimestamp(ev['created_at'], tz=timezone.utc)
    content_preview = (
        ev['content'][:120] + '...'
        if len(ev['content']) > 120 else ev['content']
    )
    return (
        f'┌─ Event {ev["id"][:16]}...\n'
        f'│  Kind:    {ev["kind"]}\n'
        f'│  From:    {ev["pubkey"][:16]}...\n'
        f'│  Time:    {created.strftime("%Y-%m-%d %H:%M:%S UTC")}\n'
        f'│  Tags:    {ev["tags"]}\n'
        f'│  Content: {content_preview}\n'
        f'└─'
    )


async def main_async():
    """Run asynchronous main logic."""
    args = parse_args()

    # Configure relays
    relays = DEFAULT_RELAYS
    if args.relays:
        relays = [r.strip() for r in args.relays.split(',') if r.strip()]

    # Secret Key from environment
    secret_key = os.environ.get('NOSTR_AGENT_SECRET', '')

    client = NostrMemoryClient(relays=relays, secret_key=secret_key)

    try:
        if args.action == 'store':
            tags = _build_tags(args.tags, args.kind)
            event_id = await client.store_event(
                args.kind, args.content, tags, encrypt=args.encrypt
            )
            if event_id:
                print(f'\nEvent-ID: {event_id}')

        elif args.action == 'get':
            if not args.event_id:
                print(
                    '[ERROR] --event-id is required for get', file=sys.stderr
                )
                sys.exit(1)
            try:
                events = await client.fetch_events(
                    event_ids=[args.event_id], limit=1
                )
                if events:
                    print(_format_event(events[0], args.json))
                else:
                    print(
                        f'⚠️  No event with ID '
                        f'{args.event_id[:16]}... found.'
                    )
            except Exception as e:
                print(f'[ERROR] During retrieval: {e}', file=sys.stderr)
                sys.exit(1)

        elif args.action == 'search':
            # Parse authors
            author_list = None
            if args.authors:
                raw_authors = [a.strip() for a in args.authors.split(',') if a.strip()]
                # Validate: hex pubkeys must be exactly 64 chars (32 bytes)
                valid_authors = []
                for a in raw_authors:
                    if len(a) != 64:
                        print(
                            f'[ERROR] Invalid author pubkey length: '
                            f'{len(a)} chars (need 64 hex chars / 32 bytes): '
                            f'{a[:16]}...',
                            file=sys.stderr
                        )
                        sys.exit(1)
                    if not all(c in '0123456789abcdefABCDEF' for c in a):
                        print(
                            f'[ERROR] Invalid author pubkey (non-hex characters): '
                            f'{a[:16]}...',
                            file=sys.stderr
                        )
                        sys.exit(1)
                    valid_authors.append(a)
                author_list = valid_authors

            # Parse tag filter
            tag_list = None
            if args.tag_filter:
                import json as _json
                tag_list = _json.loads(args.tag_filter)

            events = await client.fetch_events(
                kind=args.kind,
                limit=args.limit,
                since=args.since,
                until=args.until,
                authors=author_list,
                tag_filter=tag_list,
            )
            if not events:
                print(f'🔍 No events of kind {args.kind} found.')
            else:
                print(f'🔍 Found {len(events)} event(s) of kind {args.kind}:\n')
                for ev in events:
                    print(_format_event(ev, args.json))
                    print()

        elif args.action == 'delete':
            if not args.event_id:
                print(
                    '[ERROR] --event-id is required for delete',
                    file=sys.stderr
                )
                sys.exit(1)
            await client.delete_event(args.event_id)
            print(f'🗑️  Deletion event for {args.event_id[:16]}... sent.')

        elif args.action == 'set_status':
            try:
                content_json = json.loads(args.content) if args.content else {}
            except json.JSONDecodeError:
                content_json = {'message': args.content}
            # Automatically add timestamp
            content_json['_updated_at'] = int(time.time())
            await client.set_agent_state(content_json, encrypt=args.encrypt)
            print('✅ Agent status updated.')

        elif args.action == 'get_status':
            state = await client.get_agent_state()
            if state:
                if args.json:
                    print(json.dumps(state, ensure_ascii=False, indent=2))
                else:
                    print('📋 Current agent status:')
                    for key, val in state.items():
                        print(f'  {key}: {val}')
            else:
                print('ℹ️  No agent status stored.')

        elif args.action == 'list_keys':
            await client.list_keys_info()

    finally:
        await client.disconnect()


def main():
    """Run the main entrypoint."""
    asyncio.run(main_async())


if __name__ == '__main__':
    main()
