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

"""Codec - Encode/decode memory types to/from Nostr events."""

import base64
from dataclasses import dataclass
import hashlib
import json
from typing import List, Optional, Union
import uuid

from compress import compress_data, COMPRESSION_NONE, decompress_data
from registry import get_memory_type, get_obfuscation_config, get_serialization_config
from signer import SignerClient
import yaml


@dataclass
class MemoryEvent:
    kind: int
    content: str
    tags: List[List[str]]
    event_id: Optional[str] = None
    pubkey: Optional[str] = None
    created_at: Optional[int] = None
    sig: Optional[str] = None


def obfuscate_tag(value: str) -> str:
    """Deterministic hash (SHA256, 8 hex chars) for tag obfuscation."""
    cfg = get_obfuscation_config()
    truncate = cfg.get('truncate', 8)
    return hashlib.sha256(value.encode()).hexdigest()[:truncate]


def _make_memory_event(signer_response: dict) -> MemoryEvent:
    """Convert signer response dict to MemoryEvent."""
    return MemoryEvent(
        kind=signer_response['kind'],
        content=signer_response['content'],
        tags=signer_response['tags'],
        event_id=signer_response.get('id'),
        pubkey=signer_response.get('pubkey'),
        created_at=signer_response.get('created_at'),
        sig=signer_response.get('sig')
    )


class MemoryEncoder:
    """Encodes data into Nostr events per memory type specification."""

    def __init__(self, signer_client: Optional[SignerClient] = None):
        self.signer = signer_client or SignerClient()

    def encode(self, type_name: str, data: Union[dict, str],
               our_pubkey: Optional[str] = None,
               encrypt: Optional[bool] = None,
               compression: str = COMPRESSION_NONE) -> List[MemoryEvent]:
        mt = get_memory_type(type_name)
        if encrypt is None:
            encrypt = (mt.get('visibility') == 'encrypted')
        if our_pubkey is None and encrypt:
            our_pubkey = self.signer.get_public_key()

        # Serialize content
        if isinstance(data, dict):
            if mt.get('content_format') == 'yaml':
                content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
            elif mt.get('content_format') == 'json':
                content = json.dumps(data, indent=2)
            else:
                content = str(data)
        else:
            content = data

        # Compression (before encryption – compressed data is not high-entropy yet)
        compression_applied = COMPRESSION_NONE
        original_size = len(content.encode('utf-8'))
        if compression and compression != COMPRESSION_NONE:
            content_bytes = content.encode('utf-8')
            compressed_bytes, compression_applied = compress_data(content_bytes, compression)
            content = base64.b64encode(compressed_bytes).decode()

        # Tags (computed before encryption so d/t values are stable)
        tag_spec = mt.get('tags', {})
        d_tag_value = tag_spec.get('d', type_name)
        t_code = tag_spec.get('t', type_name[:3])
        version = tag_spec.get('version', '1')

        if encrypt:
            d_tag_value = obfuscate_tag(d_tag_value)
            t_code = obfuscate_tag(t_code)

        serializable = mt.get('serializable', False)
        chunk_size = mt.get('chunk_size', 20000) or 20000
        ser_cfg = get_serialization_config()
        header_kind = ser_cfg.get('header_kind', 30001)
        chunk_kind = ser_cfg.get('chunk_kind', 30002)

        content_bytes = content.encode('utf-8')

        if not serializable or len(content_bytes) <= chunk_size:
            # Single event path: encrypt AFTER confirming size is safe
            if encrypt and our_pubkey:
                content = self.signer.nip44_encrypt(our_pubkey, content)
            tags = [['d', d_tag_value], ['t', t_code], ['version', version]]
            if compression_applied != COMPRESSION_NONE:
                tags.append(['compression', compression_applied])
            event = self.signer.sign_event(
                kind=mt['kind'],
                content=content,
                tags=tags
            )
            return [_make_memory_event(event)]

        # Serialized (multi-event): chunk BEFORE encrypt, encrypt each chunk
        session_id = str(uuid.uuid4())
        chunks = [content_bytes[i:i+chunk_size] for i in range(0, len(content_bytes), chunk_size)]
        events = []

        # Header (unencrypted YAML metadata)
        header_meta = yaml.dump({
            'type': type_name, 'total_chunks': len(chunks),
            'session': session_id, 'format': mt.get('content_format', 'text'),
            'encrypted': encrypt,
            'compression': compression_applied,
            'compression_original_size': (
                original_size if compression_applied != COMPRESSION_NONE else None),
        }, default_flow_style=False)
        h_ev = self.signer.sign_event(
            kind=header_kind, content=header_meta,
            tags=[['d', d_tag_value], ['t', t_code], ['h', ''],
                  ['chunks', str(len(chunks))], ['version', version]]
        )
        events.append(_make_memory_event(h_ev))

        # Chunks: base64-encode, then encrypt each individually
        for i, chunk_bytes in enumerate(chunks):
            chunk_content = base64.b64encode(chunk_bytes).decode()
            if encrypt and our_pubkey:
                chunk_content = self.signer.nip44_encrypt(our_pubkey, chunk_content)
            c_ev = self.signer.sign_event(
                kind=chunk_kind, content=chunk_content,
                tags=[['d', f'{d_tag_value}:{session_id}:{i}'],
                      ['t', t_code], ['h', session_id],
                      ['seq', str(i)], ['total', str(len(chunks))],
                      ['version', version]]
            )
            events.append(_make_memory_event(c_ev))

        return events


class MemoryDecoder:
    """Decodes Nostr events back into readable data."""

    def __init__(self, signer_client: Optional[SignerClient] = None):
        self.signer = signer_client or SignerClient()

    def decode(self, events: List[Union[dict, MemoryEvent]],
               our_pubkey: Optional[str] = None) -> dict:
        if not events:
            raise ValueError('No events to decode.')

        parsed = []
        for e in events:
            if isinstance(e, dict):
                parsed.append(MemoryEvent(
                    kind=e.get('kind', 0), content=e.get('content', ''),
                    tags=e.get('tags', []), event_id=e.get('id'),
                    pubkey=e.get('pubkey'), created_at=e.get('created_at'),
                    sig=e.get('sig')
                ))
            else:
                parsed.append(e)

        is_serialized = any(
            any(t[0] == 'h' and len(t) > 1 and t[1] == '' for t in e.tags)
            for e in parsed
        )
        has_chunks = any(
            any(t[0] == 'h' for t in e.tags)
            and any(t[0] == 'seq' for t in e.tags)
            for e in parsed
        )

        if is_serialized and has_chunks:
            return self._decode_serialized(parsed, our_pubkey)
        return self._decode_single(parsed[0], our_pubkey)

    def _decode_single(self, event: MemoryEvent,
                       our_pubkey: Optional[str] = None) -> dict:
        content = self._try_decrypt(event.content, our_pubkey)
        content = self._try_decompress(content, event.tags, None)
        fmt, parsed = self._parse_content(content)
        return {
            'type': self._resolve_type(event.tags),
            'content': parsed, 'format': fmt,
            'encrypted': (content != event.content)
        }

    def _decode_serialized(self, events: List[MemoryEvent],
                           our_pubkey: Optional[str] = None) -> dict:
        header = None
        chunks = {}
        for e in events:
            td = {t[0]: t[1] if len(t) > 1 else '' for t in e.tags}
            if 'chunks' in td and td.get('h') == '':
                header = e
            elif 'seq' in td:
                chunks[int(td['seq'])] = e

        if not header:
            raise ValueError('No header event found.')

        # Parse header metadata for encryption flag
        header_meta = {}
        try:
            header_meta = yaml.safe_load(header.content) or {}
        except Exception:
            pass
        is_encrypted = header_meta.get('encrypted', True)

        total = 0
        for t in header.tags:
            if t[0] == 'chunks' and len(t) > 1:
                total = int(t[1])
                break

        data_parts = []
        for i in range(total):
            if i not in chunks:
                raise ValueError(f'Missing chunk {i}/{total}')
            chunk_content = chunks[i].content
            # Each chunk is encrypt(base64(chunk_bytes)) — decrypt first,
            # then base64-decode
            if is_encrypted and our_pubkey:
                chunk_content = self._try_decrypt(chunk_content, our_pubkey)
            data_parts.append(base64.b64decode(chunk_content))

        content = b''.join(data_parts).decode('utf-8')
        content = self._try_decompress(content, header.tags, header.content)
        fmt, parsed = self._parse_content(content)

        return {
            'type': self._resolve_type(header.tags),
            'content': parsed, 'format': fmt,
            'encrypted': is_encrypted
        }

    def _try_decrypt(self, content: str, pubkey: Optional[str]) -> str:
        if pubkey:
            try:
                return self.signer.nip44_decrypt(pubkey, content)
            except Exception:
                pass
        return content

    def _try_decompress(self, content: str, tags: list, header_content: Optional[str]) -> str:
        """Detect and decompress content. Checks header YAML first, then tags."""
        compression = None
        # Try parsing header event content for compression metadata
        if header_content:
            try:
                meta = yaml.safe_load(header_content)
                if isinstance(meta, dict):
                    compression = meta.get('compression')
            except Exception:
                pass
        # Fallback: check tags for compression hint
        if not compression or compression == COMPRESSION_NONE:
            for t in tags:
                if t[0] == 'compression' and len(t) > 1:
                    compression = t[1]
                    break
        if compression and compression != COMPRESSION_NONE:
            try:
                compressed_bytes = base64.b64decode(content)
                decompressed = decompress_data(compressed_bytes, compression)
                return decompressed.decode('utf-8')
            except Exception:
                pass
        return content

    def _parse_content(self, content: str) -> tuple:
        try:
            p = yaml.safe_load(content)
            if isinstance(p, (dict, list)):
                return ('yaml', p)
        except Exception:
            pass
        try:
            p = json.loads(content)
            return ('json', p)
        except Exception:
            pass
        return ('text', content)

    def _resolve_type(self, tags: list) -> str:
        td = {t[0]: t[1] if len(t) > 1 else '' for t in tags}
        t_code = td.get('t', '')
        d_val = td.get('d', '')

        from registry import load_spec
        spec = load_spec()
        for name, mt in spec.get('_by_name', {}).items():
            spec_t = mt.get('tags', {}).get('t', '')
            spec_d = mt.get('tags', {}).get('d', '')
            if obfuscate_tag(spec_t) == t_code or spec_t == t_code:
                return name
            if obfuscate_tag(spec_d) == d_val or spec_d == d_val:
                return name
        return 'unknown'
