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
nostr_publisher.py — Publish Kind 0, Kind 3, and Kind 1059 events via the signer.

This module reuses:
  - SignerClient   from ../../../nostr_memory/scripts/signer.py
  - resolve_host_urls from ../../../nostr_memory/scripts/nostr_relay_manager.py

All important parameters are configurable via environment variables:

  NOSTR_SIGNER_URL   (default: http://nostr-signer:8080)
  NOSTR_RELAYS       (default: ws://localhost:8781,ws://localhost:8782)
  AGENT_PROFILE_NAME   (default: bob_nostr_agent)
  AGENT_PROFILE_ABOUT  (default: ROS 2 Nostr Agent – autonomous task scheduler)
  AGENT_PROFILE_PICTURE (default: )
"""

import asyncio
import json
import logging
import os

logger = logging.getLogger('agent_contacts.publisher')

# ---------------------------------------------------------------------------
# Environment variable defaults
# ---------------------------------------------------------------------------
SIGNER_URL = os.environ.get('NOSTR_SIGNER_URL', 'http://nostr-signer:8080')
RELAYS_ENV = os.environ.get(
    'NOSTR_RELAYS',
    'ws://localhost:8781,ws://localhost:8782'
)

PROFILE_NAME = os.environ.get('AGENT_PROFILE_NAME', 'bob_nostr_agent')
PROFILE_ABOUT = os.environ.get(
    'AGENT_PROFILE_ABOUT',
    'ROS 2 Nostr Agent – autonomous task scheduler'
)
PROFILE_PICTURE = os.environ.get('AGENT_PROFILE_PICTURE', '')


def _resolve_relays() -> list:
    """Resolve relay URLs, applying container-to-host mapping if needed."""
    try:
        from nostr_relay_manager import resolve_host_urls
        resolve_host_urls()
    except ImportError:
        pass

    raw = os.environ.get('NOSTR_RELAYS', RELAYS_ENV)
    return [r.strip() for r in raw.split(',') if r.strip()]


def _get_signer_client():
    """Return a configured SignerClient instance."""
    from signer import SignerClient
    return SignerClient(url=SIGNER_URL)


def _load_env():
    """Load .env for local testing, same pattern as other skills."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
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
            return
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent


_load_env()


class NostrPublisherError(Exception):
    """Base exception for Nostr publishing errors."""

    pass


class NostrPublisher:
    """Publish Nostr events (Kind 0, Kind 3, Kind 1059)."""

    def __init__(self, signer_url: str = None, relays: list = None):
        self.signer_url = signer_url or SIGNER_URL
        self.relays = relays or _resolve_relays()

        from signer import SignerClient
        self.signer = SignerClient(url=self.signer_url)

    # ------------------------------------------------------------------
    # Kind 3 – Contact List / Follow List
    # ------------------------------------------------------------------
    def publish_kind3(self, agents: list, relays: list = None) -> dict:
        """
        Build, sign, and publish a Kind 3 (Contact List) event.

        Parameters
        ----------
        agents : list
            Agent dicts, each with at least 'pubkey' and 'name'.
        relays : list, optional
            Override relay list (defaults to self.relays).

        Returns
        -------
        dict
            Dictionary with 'success', 'event_id', 'relay_count', 'error' (if any).

        """
        targets = relays or self.relays
        if not targets:
            raise NostrPublisherError('No relays configured for publishing')

        # Build p tags: ["p", pubkey, relay_hint, name]
        tags = []
        for agent in agents:
            p_tag = ['p', agent['pubkey']]
            r = agent.get('relays', [])
            if r and isinstance(r, list) and len(r) > 0:
                p_tag.append(r[0])
            else:
                p_tag.append('')
            p_tag.append(agent.get('name', ''))
            tags.append(p_tag)

        # Content – can be empty string or descriptive JSON
        content = json.dumps({'agent_contact_list': True})

        # Sign via remote signer
        try:
            signed = self.signer.sign_event(kind=3, content=content, tags=tags)
        except Exception as e:
            raise NostrPublisherError(f'Signing Kind 3 failed: {e}') from e

        # Parse signed event JSON and send to relays
        event_id = self._send_to_relays(signed, targets)
        return {
            'success': True,
            'event_id': event_id,
            'relay_count': len(targets),
            'kind': 3,
            'agent_count': len(agents),
        }

    # ------------------------------------------------------------------
    # Kind 0 – Profile / Metadata
    # ------------------------------------------------------------------
    def publish_kind0(self, profile: dict = None, relays: list = None) -> dict:
        """
        Build, sign, and publish a Kind 0 (Metadata / Profile) event.

        Parameters
        ----------
        profile : dict, optional
            Dict with keys 'name', 'about', 'picture'.
            Falls back to env vars AGENT_PROFILE_NAME / _ABOUT / _PICTURE.
        relays : list, optional
            Override relay list (defaults to self.relays).

        Returns
        -------
        dict
            Dictionary with 'success', 'event_id', 'relay_count'.

        """
        targets = relays or self.relays
        if not targets:
            raise NostrPublisherError('No relays configured for publishing')

        p = profile or {}
        content_dict = {
            'name': p.get('name') or PROFILE_NAME,
            'about': p.get('about') or PROFILE_ABOUT,
            'picture': p.get('picture') or PROFILE_PICTURE,
            'nip05': p.get('nip05', ''),
        }
        content = json.dumps(content_dict, ensure_ascii=False)

        try:
            signed = self.signer.sign_event(kind=0, content=content, tags=[])
        except Exception as e:
            raise NostrPublisherError(f'Signing Kind 0 failed: {e}') from e

        event_id = self._send_to_relays(signed, targets)
        return {
            'success': True,
            'event_id': event_id,
            'relay_count': len(targets),
            'kind': 0,
            'profile': content_dict,
        }

    # ------------------------------------------------------------------
    # Kind 1059 – Gift-Wrapped DM (NIP-17)
    # ------------------------------------------------------------------
    def publish_kind1059(self, receiver_pubkey: str, message: str,
                         relays: list = None) -> dict:
        """
        Send an encrypted DM via NIP-17 Gift Wrap (Kind 1059).

        Parameters
        ----------
        receiver_pubkey : str
            Recipient's 64-char hex public key.
        message : str
            Plaintext message content.
        relays : list, optional
            Override relay list (defaults to self.relays).

        Returns
        -------
        dict
            Dictionary with 'success', 'event_id', 'relay_count', 'receiver'.

        """
        targets = relays or self.relays
        if not targets:
            raise NostrPublisherError('No relays configured for publishing')

        # Use signer's /nip17_wrap endpoint to create gift-wrapped event
        try:
            import urllib.request
            import urllib.error

            url = f"{self.signer_url.rstrip('/')}/nip17_wrap"
            payload = {
                'receiver_public_key': receiver_pubkey,
                'content': message,
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url, data=data,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                wrapped = json.loads(resp.read().decode())
        except Exception as e:
            raise NostrPublisherError(
                f'Gift wrap (NIP-17) failed: {e}'
            ) from e

        # The wrapped JSON already represents a signed Kind 1059 event
        event_id = self._send_to_relays(wrapped, targets)
        return {
            'success': True,
            'event_id': event_id,
            'relay_count': len(targets),
            'kind': 1059,
            'receiver': receiver_pubkey,
        }

    # ------------------------------------------------------------------
    # Internal: send signed event to relays via nostr-sdk
    # ------------------------------------------------------------------
    def _send_to_relays(self, event_data: dict, relays: list) -> str:
        """
        Send a signed event (parsed from JSON dict) to all specified relays.

        Uses nostr-sdk's Client for reliable publishing.
        Returns the event ID hex string.
        """
        try:
            from nostr_sdk import (
                Client, Event, Keys, NostrSigner, RelayUrl
            )
        except ImportError as e:
            raise NostrPublisherError(
                f'nostr-sdk not installed: {e}'
            ) from e

        # Parse signed event from JSON
        event_json = json.dumps(event_data)
        try:
            event = Event.from_json(event_json)
        except Exception as e:
            raise NostrPublisherError(
                f'Failed to parse signed event: {e}'
            ) from e

        event_id_hex = event.id().to_hex()

        async def _publish():
            # Initialize client with dummy keys (we already have signed event)
            dummy_keys = Keys.generate()
            signer = NostrSigner.keys(dummy_keys)
            client = Client(signer)

            # Add and connect to relays (all async in nostr-sdk)
            connected_relays = 0
            for r_url in relays:
                try:
                    await client.add_relay(RelayUrl.parse(r_url))
                    connected_relays += 1
                except Exception as e:
                    logger.warning(f'Failed to add relay {r_url}: {e}')

            if connected_relays == 0:
                raise NostrPublisherError('Failed to connect to any relay')

            await client.connect()
            await client.send_event(event)
            await client.shutdown()

        try:
            asyncio.run(_publish())
        except Exception as e:
            raise NostrPublisherError(
                f'Failed to publish event to relays: {e}'
            ) from e

        return event_id_hex

    # ------------------------------------------------------------------
    # Public key helper
    # ------------------------------------------------------------------
    def get_public_key_hex(self) -> str:
        """Return the agent's own public key (hex) from the signer."""
        return self.signer.get_public_key()

    def get_public_key_bech32(self) -> str:
        """Return the agent's own public key (bech32) from the signer."""
        raw = self.signer._get('/public_key')
        return raw['public_key']
