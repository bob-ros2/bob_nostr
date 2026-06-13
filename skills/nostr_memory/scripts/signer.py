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

"""SignerClient - HTTP client for the isolated Nostr signer service."""

import json
import os
import urllib.error
import urllib.request

SIGNER_URL = os.environ.get('NOSTR_SIGNER_URL', 'http://nostr-signer:8080')


class SignerClient:
    """HTTP-Client zum isolierten Nostr-Signer."""

    def __init__(self, url: str = SIGNER_URL):
        self.url = url.rstrip('/')

    def _post(self, path: str, data: dict) -> dict:
        req = urllib.request.Request(
            f'{self.url}{path}',
            data=json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f'Signer HTTP {e.code}: {body}')

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(f'{self.url}{path}')
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def get_public_key(self) -> str:
        return self._get('/public_key')['public_key_hex']

    def sign_event(self, kind: int, content: str, tags: list) -> dict:
        return self._post('/sign', {
            'kind': kind, 'content': content, 'tags': tags
        })

    def nip44_encrypt(self, peer_pubkey: str, content: str) -> str:
        return self._post('/nip44_encrypt', {
            'peer_public_key': peer_pubkey, 'content': content
        })['encrypted_content']

    def nip44_decrypt(self, peer_pubkey: str, payload: str) -> str:
        return self._post('/nip44_decrypt', {
            'peer_public_key': peer_pubkey, 'payload': payload
        })['decrypted_content']
