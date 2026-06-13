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

"""AgentMemory - High-level API for packing/unpacking agent memory."""

from typing import List, Union

from codec import MemoryDecoder, MemoryEncoder
from signer import SignerClient


class AgentMemory:
    """High-level API for packing/unpacking agent memory."""

    def __init__(self, signer_url: str = None):
        self.signer = SignerClient(signer_url) if signer_url else SignerClient()
        self.encoder = MemoryEncoder(self.signer)
        self.decoder = MemoryDecoder(self.signer)
        self._pubkey = None

    @property
    def pubkey(self) -> str:
        if self._pubkey is None:
            self._pubkey = self.signer.get_public_key()
        return self._pubkey

    def pack(self, type_name: str, data: Union[dict, str],
             compression: str = 'none') -> List[dict]:
        """Pack data into signed Nostr events (JSON-compatible)."""
        events = self.encoder.encode(type_name, data, our_pubkey=self.pubkey,
                                     compression=compression)
        return [
            {
                'kind': e.kind, 'content': e.content, 'tags': e.tags,
                'id': e.event_id, 'pubkey': e.pubkey,
                'created_at': e.created_at, 'sig': e.sig
            }
            for e in events if e.event_id
        ]

    def unpack(self, events: List[dict]) -> dict:
        """Unpack Nostr events back into data."""
        return self.decoder.decode(events, our_pubkey=self.pubkey)
