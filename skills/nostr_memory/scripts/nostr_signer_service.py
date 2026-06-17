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
Nostr Signer Service – An isolated microservice to sign and encrypt events.

This service keeps the NOSTR_AGENT_SECRET private key safe inside
its own container. It exposes a simple HTTP API to sign events,
encrypt/decrypt DMs (NIP-04 / NIP-44), and retrieve the public key.
"""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys

# Configure relays/dependencies safely
try:
    from nostr_sdk import (
        EventBuilder, Keys, Kind as NKind, Nip44Version, PublicKey, Tag,
        Timestamp, nip04_decrypt, nip04_encrypt, nip44_decrypt,
        nip44_encrypt, UnwrappedGift, gift_wrap, NostrSigner, Event
    )
except ImportError:
    print(
        '[ERROR] nostr-sdk not installed. Run: pip install nostr-sdk',
        file=sys.stderr
    )
    sys.exit(1)

PORT = int(os.environ.get('SIGNER_PORT', '8080'))
HOST = os.environ.get('SIGNER_HOST', '0.0.0.0')
SECRET_KEY_RAW = os.environ.get('NOSTR_AGENT_SECRET', '')


def get_secret_key(raw_value):
    """
    Retrieve the secret key from the provided raw value.

    If the value is a valid file path, it reads the content from that file.
    Otherwise, it treats the value as the secret key itself.
    """
    if not raw_value:
        return None

    # Check if it's a path to a file (e.g., a Docker secret)
    if os.path.isfile(raw_value):
        try:
            with open(raw_value, 'r') as f:
                return f.read().strip()
        except Exception as e:
            print(f'[ERROR] Could not read secret file {raw_value}: {e}', file=sys.stderr)
            return None

    return raw_value


actual_secret = get_secret_key(SECRET_KEY_RAW)

if not actual_secret:
    print(
        '[WARNING] NOSTR_AGENT_SECRET not set or file not found. '
        'Generating a temporary secret key for this run...',
        file=sys.stderr
    )
    KEYS = Keys.generate()
else:
    try:
        KEYS = Keys.parse(actual_secret)
    except Exception as e:
        print(f'[ERROR] Invalid NOSTR_AGENT_SECRET: {e}', file=sys.stderr)
        sys.exit(1)

pubkey_bech32 = KEYS.public_key().to_bech32()
truncated = pubkey_bech32[:7] + '...' + pubkey_bech32[-4:]
print(
    f'[INFO] Signer initialized for public key: {truncated}',
    file=sys.stderr
)


class SignerHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for the isolated Nostr Signer service."""

    def log_message(self, log_format, *args):
        """Log request messages to stderr."""
        sys.stderr.write(
            '%s - - [%s] %s\n' % (
                self.address_string(),
                self.log_date_time_string(),
                log_format % args
            )
        )

    def do_GET(self):
        """Handle GET requests for public key and health endpoints."""
        if self.path == '/public_key':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                'public_key': KEYS.public_key().to_bech32(),
                'public_key_hex': KEYS.public_key().to_hex()
            }
            self.wfile.write(json.dumps(response).encode('utf-8'))
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'healthy'}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """Handle POST requests for signing and encrypting/decrypting."""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

        try:
            data = json.loads(post_data.decode('utf-8'))
        except Exception as e:
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(
                json.dumps({'error': f'Invalid JSON: {e}'}).encode('utf-8')
            )
            return

        if self.path == '/sign':
            kind_num = data.get('kind')
            content = data.get('content', '')
            tags_list = data.get('tags', [])

            if kind_num is None:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps({'error': "Missing 'kind'"}).encode('utf-8')
                )
                return

            try:
                sdk_tags = []
                for t in tags_list:
                    if len(t) >= 2:
                        sdk_tags.append(Tag.parse([t[0], t[1]]))

                event_builder = EventBuilder(
                    NKind(kind_num), content
                ).tags(sdk_tags)
                event = event_builder.sign_with_keys(KEYS)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(event.as_json().encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': f'Signing error: {e}'}
                    ).encode('utf-8')
                )

        elif self.path == '/nip04_encrypt':
            peer_pubkey_str = data.get('peer_public_key')
            content = data.get('content')

            if not peer_pubkey_str or content is None:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': "Missing 'peer_public_key' or 'content'"}
                    ).encode('utf-8')
                )
                return

            try:
                peer_pubkey = PublicKey.parse(peer_pubkey_str)
                encrypted = nip04_encrypt(
                    KEYS.secret_key(), peer_pubkey, content
                )

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps({'encrypted_content': encrypted}).encode('utf-8')
                )
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': f'Encryption error: {e}'}
                    ).encode('utf-8')
                )

        elif self.path == '/nip04_decrypt':
            peer_pubkey_str = data.get('peer_public_key')
            encrypted_content = data.get('encrypted_content')

            if not peer_pubkey_str or encrypted_content is None:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error':
                         "Missing 'peer_public_key' or 'encrypted_content'"}
                    ).encode('utf-8')
                )
                return

            try:
                peer_pubkey = PublicKey.parse(peer_pubkey_str)
                decrypted = nip04_decrypt(
                    KEYS.secret_key(), peer_pubkey, encrypted_content
                )

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps({'decrypted_content': decrypted}).encode('utf-8')
                )
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': f'Decryption error: {e}'}
                    ).encode('utf-8')
                )

        elif self.path == '/nip44_encrypt':
            peer_pubkey_str = data.get('peer_public_key')
            content = data.get('content')

            if not peer_pubkey_str or content is None:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': "Missing 'peer_public_key' or 'content'"}
                    ).encode('utf-8')
                )
                return

            try:
                peer_pubkey = PublicKey.parse(peer_pubkey_str)
                encrypted = nip44_encrypt(
                    KEYS.secret_key(), peer_pubkey, content, Nip44Version.V2
                )

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps({'encrypted_content': encrypted}).encode('utf-8')
                )
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': f'Encryption error: {e}'}
                    ).encode('utf-8')
                )

        elif self.path == '/nip44_decrypt':
            peer_pubkey_str = data.get('peer_public_key')
            payload = data.get('payload')

            if not peer_pubkey_str or payload is None:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': "Missing 'peer_public_key' or 'payload'"}
                    ).encode('utf-8')
                )
                return

            try:
                peer_pubkey = PublicKey.parse(peer_pubkey_str)
                decrypted = nip44_decrypt(
                    KEYS.secret_key(), peer_pubkey, payload
                )

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps({'decrypted_content': decrypted}).encode('utf-8')
                )
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': f'Decryption error: {e}'}
                    ).encode('utf-8')
                )

        elif self.path == '/nip17_wrap':
            receiver_pubkey_str = data.get('receiver_public_key')
            content = data.get('content')

            if not receiver_pubkey_str or content is None:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': "Missing 'receiver_public_key' or 'content'"}
                    ).encode('utf-8')
                )
                return

            try:
                receiver_pubkey = PublicKey.parse(receiver_pubkey_str)
                signer = NostrSigner.keys(KEYS)

                # Create rumor (Kind 14)
                rumor_builder = EventBuilder.private_msg_rumor(receiver_pubkey, content)
                rumor = rumor_builder.custom_created_at(Timestamp.now()).build(KEYS.public_key())

                # Wrap it using our private key / signer
                async def wrap_coro():
                    return await gift_wrap(signer, receiver_pubkey, rumor)

                wrapped_event = asyncio.run(wrap_coro())

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(wrapped_event.as_json().encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': f'NIP-17 wrapping error: {e}'}
                    ).encode('utf-8')
                )

        elif self.path == '/nip17_unwrap':
            gift_wrap_data = data.get('gift_wrap_event')

            if not gift_wrap_data:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': "Missing 'gift_wrap_event'"}
                    ).encode('utf-8')
                )
                return

            try:
                if isinstance(gift_wrap_data, dict):
                    gift_wrap_str = json.dumps(gift_wrap_data)
                else:
                    gift_wrap_str = str(gift_wrap_data)

                gift_wrap_event = Event.from_json(gift_wrap_str)
                signer = NostrSigner.keys(KEYS)

                async def unwrap_coro():
                    return await UnwrappedGift.from_gift_wrap(signer, gift_wrap_event)

                unwrapped = asyncio.run(unwrap_coro())
                rumor = unwrapped.rumor()

                # Convert tags to simple list of lists of strings
                tags_list = []
                for t in rumor.tags().to_vec():
                    tags_list.append(t.as_vec())

                response = {
                    'sender': unwrapped.sender().to_hex(),
                    'content': rumor.content(),
                    'created_at': rumor.created_at().as_secs(),
                    'kind': rumor.kind().as_u16(),
                    'tags': tags_list
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                import traceback
                print(f'[ERROR] NIP-17 unwrapping exception: {e}', file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {'error': f'NIP-17 unwrapping error: {e}'}
                    ).encode('utf-8')
                )

        else:
            self.send_response(404)
            self.end_headers()


def run(server_class=HTTPServer, handler_class=SignerHandler):
    """Start the signing/crypto server."""
    server_address = (HOST, PORT)
    httpd = server_class(server_address, handler_class)
    print(
        f'[INFO] Starting signing/crypto server on {HOST}:{PORT}...',
        file=sys.stderr
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    print('[INFO] Stopping signing/crypto server...', file=sys.stderr)
    httpd.server_close()


if __name__ == '__main__':
    run()
