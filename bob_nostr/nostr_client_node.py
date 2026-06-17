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
Nostr Client Bridge Node.

ROS 2 Node bridging Nostr relays with the LLM Agent.
Listens to mentions and DMs on Nostr and forwards them as prompts to the LLM agent,
then sends the replies back to Nostr.
"""

import asyncio
import json
import os
import sys
import threading
import urllib.parse
import urllib.request

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# Import nostr_sdk
try:
    from nostr_sdk import (
        Alphabet, Client, Filter, HandleNotification, Keys, Kind as NKind,
        PublicKey, RelayUrl, SingleLetterTag, Timestamp
    )
except ImportError:
    print(
        '[ERROR] nostr-sdk not installed. Run: pip install nostr-sdk',
        file=sys.stderr
    )
    sys.exit(1)

NOSTR_RELAYS_ENV = os.environ.get('NOSTR_RELAYS', '')
if not NOSTR_RELAYS_ENV:
    print(
        '[ERROR] NOSTR_RELAYS environment variable is not configured.',
        file=sys.stderr
    )
    sys.exit(1)

RELAYS = [r.strip() for r in NOSTR_RELAYS_ENV.split(',') if r.strip()]
SIGNER_URL = os.environ.get('NOSTR_SIGNER_URL', 'http://nostr-signer:8080')


class NostrBridgeNode(Node):
    """ROS 2 Node bridging Nostr relays with the LLM Agent."""

    def __init__(self):
        super().__init__('nostr_bridge_node')
        self.get_logger().info('Initializing Nostr Bridge Node...')

        # ROS 2 Pub/Sub
        self.pub_prompt = self.create_publisher(String, 'llm_prompt', 10)
        self.sub_response = self.create_subscription(
            String, 'llm_response', self.response_callback, 10
        )

        # Queue/Lock for processing
        self.current_context = None
        self.pending_replies = []
        self.lock = threading.Lock()

        # Fetch public key from signing service
        self.agent_pubkey = None
        self.agent_pubkey_hex = None
        self.fetch_public_key()

        # Track node start time to filter out old backdated Gift Wraps
        self.node_start_time = Timestamp.now()

        # Start Nostr client in asyncio loop in background thread
        self.loop = asyncio.new_event_loop()
        self.nostr_thread = threading.Thread(
            target=self.run_async_loop, daemon=True
        )
        self.nostr_thread.start()

    def fetch_public_key(self):
        """Fetch the agent public key from the isolated signing service."""
        url = f"{SIGNER_URL.rstrip('/')}/public_key"
        try:
            self.get_logger().info(
                f'Fetching public key from signer at {url}...'
            )
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                resp = json.loads(response.read().decode('utf-8'))
            self.agent_pubkey_hex = resp.get('public_key_hex')
            self.agent_pubkey = PublicKey.parse(self.agent_pubkey_hex)
            self.get_logger().info(
                f'Agent Public Key parsed: {self.agent_pubkey_hex}'
            )
        except Exception as e:
            self.get_logger().error(
                f'Failed to fetch public key from signer: {e}'
            )
            # Fallback to loading from environment if signer not ready
            secret_key = os.environ.get('NOSTR_AGENT_SECRET', '')
            if secret_key:
                try:
                    keys = Keys.parse(secret_key)
                    self.agent_pubkey = keys.public_key()
                    self.agent_pubkey_hex = self.agent_pubkey.to_hex()
                    self.get_logger().warn(
                        'Loaded key from env fallback. '
                        f'Pubkey: {self.agent_pubkey_hex}'
                    )
                except Exception as e2:
                    self.get_logger().error(
                        f'Failed fallback key parsing: {e2}'
                    )
                    sys.exit(1)
            else:
                self.get_logger().error(
                    'No secret key fallback found in env. Aborting.'
                )
                sys.exit(1)

    def run_async_loop(self):
        """Run the asyncio event loop."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.start_nostr_client())

    async def start_nostr_client(self):
        """Initialize and start the Nostr client, connecting to relays."""
        self.get_logger().info('Starting Nostr Client task...')

        # Check relay connectivity first
        import socket
        reachable_relays = []
        for r_url in RELAYS:
            try:
                parsed = urllib.parse.urlparse(r_url)
                host = parsed.hostname
                port = parsed.port
                if not port:
                    port = 443 if parsed.scheme in ('wss', 'https') else 80
                with socket.create_connection((host, port), timeout=2):
                    reachable_relays.append(r_url)
            except Exception as e:
                self.get_logger().warn(f'Relay {r_url} unreachable: {e}')

        if not reachable_relays:
            self.get_logger().error(
                'No reachable Nostr relays! Stopping client.'
            )
            return

        # Create dummy keys for client initialization since we delegate signing
        dummy_keys = Keys.generate()
        from nostr_sdk import NostrSigner
        signer = NostrSigner.keys(dummy_keys)
        self.client = Client(signer)

        for r_url in reachable_relays:
            await self.client.add_relay(RelayUrl.parse(r_url))

        await self.client.connect()
        self.get_logger().info('Connected to Nostr relays.')

        # Subscribe to Mentions (Kind 1) and Gift Wraps (Kind 1059) directed to the agent
        # Since Gift Wraps are backdated by up to 2-3 days, we subscribe with a margin.
        # We will filter out older events inside the incoming handler using self.node_start_time.
        since_time = Timestamp.from_secs(self.node_start_time.as_secs() - 259200)  # 3 days ago

        # Filter for public mentions (Kind 1) with #p tag = agent
        mention_filter = Filter().kind(NKind(1)).custom_tag(
            SingleLetterTag.lowercase(Alphabet.P),
            self.agent_pubkey_hex
        ).since(since_time)
        await self.client.subscribe(mention_filter, None)

        # Filter for Gift Wraps (Kind 1059) with #p tag = agent
        gift_filter = Filter().kind(NKind(1059)).custom_tag(
            SingleLetterTag.lowercase(Alphabet.P),
            self.agent_pubkey_hex
        ).since(since_time)
        await self.client.subscribe(gift_filter, None)

        self.get_logger().info(
            'Subscribed to Mentions (Kind 1) and Gift Wraps (Kind 1059) '
            'via #p tag filter with a 3-day history margin.'
        )

        # Class to handle incoming notifications
        class BridgeNotificationHandler(HandleNotification):
            """Handler for incoming Nostr events."""

            def __init__(self, node):
                self.node = node

            async def handle(self, relay_url, subscription_id, event):
                self.node.loop.create_task(
                    self.node.handle_incoming_event(event)
                )

            async def handle_msg(self, relay_url, msg):
                pass

        await self.client.handle_notifications(BridgeNotificationHandler(self))

    async def handle_incoming_event(self, event):
        """Process an incoming Nostr event."""
        event_id = event.id().to_hex()
        author = event.author().to_hex()
        kind = event.kind().as_u16()

        # Avoid replying to self
        if author == self.agent_pubkey_hex:
            return

        self.get_logger().info(
            f'Incoming Nostr Event Kind {kind} from {author[:16]}... '
            f'(ID: {event_id[:16]}...)'
        )

        content = ''
        if kind == 1059:
            unwrapped = self.unwrap_gift_wrap(event)
            if not unwrapped:
                self.get_logger().error('Unwrapping failed for Gift Wrap.')
                return

            rumor_created_at = unwrapped.get('created_at', 0)
            if rumor_created_at < self.node_start_time.as_secs():
                self.get_logger().info(
                    f'Ignoring old Gift Wrap rumor from {unwrapped.get("sender")[:16]}...'
                )
                return

            author = unwrapped.get('sender')
            content = unwrapped.get('content')
            kind = 1059
        elif kind == 1:
            if event.created_at().as_secs() < self.node_start_time.as_secs():
                self.get_logger().info(
                    f'Ignoring old Mention from {author[:16]}...'
                )
                return
            content = event.content()
        else:
            return

        with self.lock:
            if self.current_context is not None:
                self.get_logger().info('Agent is busy, queuing message.')
                self.pending_replies.append({
                    'id': event_id,
                    'author': author,
                    'kind': kind,
                    'content': content
                })
            else:
                self.current_context = {
                    'id': event_id,
                    'author': author,
                    'kind': kind
                }
                self.get_logger().info(
                    f'Forwarding prompt to agent: {content}'
                )
                msg = String()
                msg.data = f'[Nostr User: {author}] {content}'
                self.pub_prompt.publish(msg)

    def unwrap_gift_wrap(self, event):
        """Unwrap a NIP-17 Gift Wrap event using the isolated signer service."""
        url = f"{SIGNER_URL.rstrip('/')}/nip17_unwrap"
        payload = {
            'gift_wrap_event': json.loads(event.as_json())
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, data=data, headers={'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                resp = json.loads(response.read().decode('utf-8'))
            return resp
        except Exception as e:
            self.get_logger().error(f'Error calling unwrapper: {e}')
            return None

    def wrap_private_msg(self, peer_pubkey, content):
        """Wrap a private message into a Gift Wrap event using the isolated signer service."""
        url = f"{SIGNER_URL.rstrip('/')}/nip17_wrap"
        payload = {
            'receiver_public_key': peer_pubkey,
            'content': content
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, data=data, headers={'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                resp_json = response.read().decode('utf-8')
            return resp_json
        except Exception as e:
            self.get_logger().error(f'Error calling NIP-17 wrapper: {e}')
            return None

    def response_callback(self, msg):
        """Receive agent response from LLM ROS topic and schedule reply."""
        response_text = msg.data
        self.get_logger().info(f'Received reply from agent: {response_text}')

        with self.lock:
            if not self.current_context:
                self.get_logger().warn(
                    'Received response from agent but no active '
                    'Nostr context exists. Ignoring.'
                )
                return

            context = self.current_context
            self.current_context = None

        self.loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(
                self.send_nostr_reply(context, response_text),
                loop=self.loop
            )
        )

    async def send_nostr_reply(self, context, text):
        """Post signed reply event to Nostr relays."""
        author = context['author']
        event_id = context['id']
        kind = context['kind']

        self.get_logger().info(
            f'Posting reply to {author[:16]}... '
            f'for original event {event_id[:16]}...'
        )

        try:
            if kind == 1059:
                wrapped_json = self.wrap_private_msg(author, text)
                if not wrapped_json:
                    self.get_logger().error('Failed to wrap response private message.')
                    return
                from nostr_sdk import Event
                event = Event.from_json(wrapped_json)
            else:
                reply_kind = 1
                reply_content = text
                reply_tags = [
                    ['p', author],
                    ['e', event_id, '', 'reply']
                ]

                url = f"{SIGNER_URL.rstrip('/')}/sign"
                payload = {
                    'kind': reply_kind,
                    'content': reply_content,
                    'tags': reply_tags
                }
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(
                    url, data=data, headers={'Content-Type': 'application/json'}
                )

                with urllib.request.urlopen(req, timeout=5) as response:
                    resp_json = response.read().decode('utf-8')

                from nostr_sdk import Event
                event = Event.from_json(resp_json)

            await self.client.send_event(event)
            self.get_logger().info(
                f'✅ Reply sent successfully! ID: {event.id().to_hex()[:16]}...'
            )

        except Exception as e:
            self.get_logger().error(
                f'Failed to sign/send reply on Nostr: {e}'
            )

        # Check if there are queued incoming messages to process
        with self.lock:
            if self.pending_replies:
                next_item = self.pending_replies.pop(0)
                self.current_context = {
                    'id': next_item['id'],
                    'author': next_item['author'],
                    'kind': next_item['kind']
                }
                c_val = next_item['content']
                a_val = next_item['author']
                self.get_logger().info(f'Processing queued message: {c_val}')
                msg = String()
                msg.data = f'[Nostr User: {a_val}] {c_val}'
                self.pub_prompt.publish(msg)


def main(args=None):
    """Run the Nostr bridge ROS 2 node."""
    rclpy.init(args=args)
    node = NostrBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.get_logger().info('Shutting down Nostr Bridge Node...')
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
