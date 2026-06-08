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
Integration test for NIP-17 (Gift Wrap) direct message flow.

Sends a private Gift Wrapped message to the agent and awaits a Gift Wrapped reply.
"""

import asyncio
import json
import os
import urllib.request

from nostr_sdk import (
    Client, EventBuilder, Filter, gift_wrap, HandleNotification, Keys,
    Kind as NKind, NostrSigner, PublicKey, RelayUrl, Timestamp, UnwrappedGift
)

import pytest

# Resolve target Agent Public Key dynamically from signer service if not overridden in env
NOSTR_SIGNER_URL = os.environ.get('NOSTR_SIGNER_URL', 'http://localhost:8080')
AGENT_PUBKEY_HEX = os.environ.get('AGENT_PUBKEY_HEX')

if not AGENT_PUBKEY_HEX:
    try:
        req = urllib.request.Request(f'{NOSTR_SIGNER_URL.rstrip("/")}/public_key')
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode())
            AGENT_PUBKEY_HEX = res_data.get('public_key_hex')
            print(f'Dynamically resolved agent public key: {AGENT_PUBKEY_HEX}')
    except Exception as e:
        print(f'Failed to fetch public key from signer at {NOSTR_SIGNER_URL}: {e}')

if not AGENT_PUBKEY_HEX:
    # Fallback to default Curator key
    AGENT_PUBKEY_HEX = '7009f1551e0e7652ef4e5ca69da4afde1b09ebc8162df21e4b2f879489fe60ad'

RELAY_URLS = os.environ.get(
    'NOSTR_RELAYS',
    'ws://nostr-relay-1:8080'
).split(',')

# Event to notify when reply is received
reply_received = asyncio.Event()
unwrapped_result = {}


class ReplyHandler(HandleNotification):
    """Handler to check and decrypt incoming NIP-17 responses."""

    def __init__(self, tester_signer, start_time):
        self.tester_signer = tester_signer
        self.start_time = start_time

    async def handle(self, relay_url, subscription_id, event):
        if event.kind().as_u16() == 1059:
            try:
                unwrapped = await UnwrappedGift.from_gift_wrap(
                    self.tester_signer, event
                )
                rumor = unwrapped.rumor()
                if rumor.created_at().as_secs() >= self.start_time.as_secs():
                    unwrapped_result['sender'] = unwrapped.sender().to_hex()
                    unwrapped_result['content'] = rumor.content()
                    reply_received.set()
            except Exception as e:
                print(f'[ERROR] Failed to unwrap: {e}')

    async def handle_msg(self, relay_url, msg):
        pass


@pytest.mark.asyncio
async def test_nip17_flow():
    """Test the end-to-end NIP-17 DM flow to verify agent bridges."""
    # Reset event and results for clean test runs
    reply_received.clear()
    unwrapped_result.clear()

    print(f'Target Agent Pubkey: {AGENT_PUBKEY_HEX}')
    print(f'Connecting to relays: {RELAY_URLS}')

    # Generate temporary keys for the tester client
    tester_keys = Keys.generate()
    tester_signer = NostrSigner.keys(tester_keys)
    client = Client(tester_signer)

    for url in RELAY_URLS:
        await client.add_relay(RelayUrl.parse(url))

    await client.connect()
    print('Connected to relays.')

    agent_pub = PublicKey.parse(AGENT_PUBKEY_HEX)

    # 1. Subscribe to Gift Wraps (Kind 1059) addressed to the tester
    # Since Gift Wraps are backdated, we use a 3-day history margin and filter in python.
    tester_start_time = Timestamp.now()
    since_time = Timestamp.from_secs(tester_start_time.as_secs() - 259200)
    sub_filter = Filter().kinds([NKind(1059)]).pubkey(
        tester_keys.public_key()
    ).since(since_time)
    await client.subscribe(sub_filter, None)
    print('Subscribed to replies (Kind 1059) with history margin.')

    # 2. Build and wrap the test message (Kind 14 rumor)
    prompt = 'Ping! Teste NIP-17 bitte mit der Antwort: PONG_SUCCESS.'
    print(f"Sending prompt to agent: '{prompt}'")

    rumor_builder = EventBuilder.private_msg_rumor(agent_pub, prompt)
    rumor = rumor_builder.build(tester_keys.public_key())

    # Wrap using tester keys
    wrapped_event = await gift_wrap(tester_signer, agent_pub, rumor)

    # Publish to relays
    await client.send_event(wrapped_event)
    print('Sent Gift Wrap event to agent.')

    # 3. Listen for response
    print('Waiting for response...')
    handler_task = asyncio.create_task(
        client.handle_notifications(ReplyHandler(tester_signer, tester_start_time))
    )

    try:
        await asyncio.wait_for(reply_received.wait(), timeout=60.0)
        print('\n' + '=' * 40)
        print(f"From: {unwrapped_result.get('sender')}")
        print(f"Content: {unwrapped_result.get('content')}")
        print('=' * 40 + '\n')

        content = unwrapped_result.get('content', '')
        assert 'PONG_SUCCESS' in content or 'pong' in content.lower(), (
            f"Expected 'PONG_SUCCESS' but got '{content}'"
        )
        print('SUCCESS: NIP-17 integration works flawlessly!')
    except asyncio.TimeoutError:
        pytest.fail('Timeout: No reply received from agent within 60 seconds.')
    finally:
        handler_task.cancel()
        await client.disconnect()


if __name__ == '__main__':
    try:
        asyncio.run(test_nip17_flow())
    except KeyboardInterrupt:
        print('\nExiting.')
