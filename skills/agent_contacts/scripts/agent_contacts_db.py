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
agent_contacts_db.py — Redis-backed persistence for the agent contact list.

Redis keys:
  chronology:agents:set              Set of all known agent pubkeys (hex)
  chronology:agents:{pubkey}         Hash with metadata fields

All important parameters are configurable via environment variables:

  AGENT_CONTACTS_REDIS_HOST   (default: localhost)
  AGENT_CONTACTS_REDIS_PORT   (default: 6379)
  AGENT_CONTACTS_REDIS_DB     (default: 0)
  AGENT_CONTACTS_SET_KEY      (default: chronology:agents:set)
  AGENT_CONTACTS_HASH_PREFIX  (default: chronology:agents:)

Also falls back to CHRONO_REDIS_HOST/CHRONO_REDIS_PORT/CHRONO_REDIS_DB
for compatibility with the existing Chronology infrastructure.
"""

import json
import logging
import os
import time
from typing import Optional

import redis

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

logger = logging.getLogger('agent_contacts')

# ---------------------------------------------------------------------------
# Environment variable defaults (all overridable)
# ---------------------------------------------------------------------------
_REDIS_HOST = (
    os.environ.get('AGENT_CONTACTS_REDIS_HOST')
    or os.environ.get('CHRONO_REDIS_HOST')
    or 'localhost'
)
_REDIS_PORT = int(
    os.environ.get('AGENT_CONTACTS_REDIS_PORT')
    or os.environ.get('CHRONO_REDIS_PORT')
    or '6379'
)
_REDIS_DB = int(
    os.environ.get('AGENT_CONTACTS_REDIS_DB')
    or os.environ.get('CHRONO_REDIS_DB')
    or '0'
)
_SET_KEY = os.environ.get('AGENT_CONTACTS_SET_KEY', 'chronology:agents:set')
_HASH_PREFIX = os.environ.get('AGENT_CONTACTS_HASH_PREFIX', 'chronology:agents:')


class AgentContactsError(Exception):
    """Base exception for agent contacts database operations."""

    pass


class AgentContactsDB:
    """Redis-backed persistence for Nostr agent contacts."""

    def __init__(self, host: str = None, port: int = None, db: int = None,
                 set_key: str = None, hash_prefix: str = None):
        self.host = host or _REDIS_HOST
        self.port = port or _REDIS_PORT
        self.db = db or _REDIS_DB
        self.set_key = set_key or _SET_KEY
        self.hash_prefix = hash_prefix or _HASH_PREFIX

        self._redis: Optional[redis.Redis] = None
        self._chrono = None  # Lazy-loaded ChronologyEngine

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    @property
    def conn(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
            )
        return self._redis

    def close(self):
        if self._redis is not None:
            self._redis.close()
            self._redis = None

    # ------------------------------------------------------------------
    # Lazy Chronology logger
    # ------------------------------------------------------------------
    def _log_event(self, message: str, tags: list = None, level: str = 'INFO',
                   source: str = 'agent_contacts'):
        """Log an event via the Chronology engine if available."""
        if self._chrono is None:
            try:
                from chronology_engine import ChronologyEngine
                self._chrono = ChronologyEngine(
                    host=self.host, port=self.port, db=self.db
                )
            except ImportError:
                # Chronology not installed – just log to python logger
                logger.info(f'{level}: {message}')
                return
            except Exception as exc:
                logger.warning(f'Cannot init chronology: {exc}')
                return
        try:
            self._chrono.log_event(
                message=message,
                tags=tags or [],
                level=level,
                source=source,
            )
        except Exception as exc:
            logger.warning(f'Chronology log failed: {exc}')

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def _hash_key(self, pubkey: str) -> str:
        return f'{self.hash_prefix}{pubkey}'

    def add_agent(self, pubkey: str, name: str = '',
                  relays: list = None,
                  log_to_chrono: bool = True) -> bool:
        """
        Add an agent to the contact list.

        Returns True if a NEW agent was added, False if already known.
        """
        if not pubkey or not isinstance(pubkey, str) or len(pubkey) != 64:
            raise AgentContactsError(
                f'Invalid pubkey: must be 64-char hex string, got {pubkey!r}'
            )

        now = int(time.time())
        relays_json = json.dumps(relays or [])

        pipe = self.conn.pipeline()
        pipe.sadd(self.set_key, pubkey)
        pipe.hset(self._hash_key(pubkey), mapping={
            'name': name,
            'relays': relays_json,
            'added_at': str(now),
            'last_seen': str(now),
            'last_dm_at': '',
        })
        results = pipe.execute()

        is_new = results[0] == 1  # SADD returns 1 if new member added

        if log_to_chrono:
            action = 'Added new' if is_new else 'Updated existing'
            self._log_event(
                message=f'{action} agent: {name or pubkey[:12]}...',
                tags=['agent', 'contacts'],
                level='INFO' if is_new else 'DEBUG',
            )

        return is_new

    def remove_agent(self, pubkey: str, log_to_chrono: bool = True) -> bool:
        """
        Remove an agent from the contact list.

        Returns True if agent was removed, False if not found.
        """
        pipe = self.conn.pipeline()
        pipe.srem(self.set_key, pubkey)
        pipe.delete(self._hash_key(pubkey))
        results = pipe.execute()

        removed = results[0] == 1

        if removed and log_to_chrono:
            self._log_event(
                message=f'Removed agent: {pubkey[:12]}...',
                tags=['agent', 'contacts'],
                level='WARN',
            )

        return removed

    def list_agents(self) -> list:
        """
        Return a list of all known agents with metadata.

        Each entry is a dict::
            {
                'pubkey': <hex>,
                'name': <str>,
                'relays': <list>,
                'added_at': <str>,
                'last_seen': <str>,
                'last_dm_at': <str>,
            }
        """
        pubkeys = self.conn.smembers(self.set_key)
        if not pubkeys:
            return []

        pipe = self.conn.pipeline()
        for pk in pubkeys:
            pipe.hgetall(self._hash_key(pk))
        hash_results = pipe.execute()

        agents = []
        for pk, fields in zip(pubkeys, hash_results):
            if not fields:
                # Orphan – clean up
                self.conn.srem(self.set_key, pk)
                continue
            try:
                relays = json.loads(fields.get('relays', '[]'))
            except (json.JSONDecodeError, TypeError):
                relays = []
            agents.append({
                'pubkey': pk,
                'name': fields.get('name', ''),
                'relays': relays,
                'added_at': fields.get('added_at', ''),
                'last_seen': fields.get('last_seen', ''),
                'last_dm_at': fields.get('last_dm_at', ''),
            })

        # Sort by added_at descending (newest first)
        agents.sort(key=lambda a: a['added_at'], reverse=True)
        return agents

    def get_agent(self, pubkey: str) -> Optional[dict]:
        """Return metadata dict for a single agent, or None if not found."""
        if not self.conn.sismember(self.set_key, pubkey):
            return None
        fields = self.conn.hgetall(self._hash_key(pubkey))
        if not fields:
            return None
        try:
            relays = json.loads(fields.get('relays', '[]'))
        except (json.JSONDecodeError, TypeError):
            relays = []
        return {
            'pubkey': pubkey,
            'name': fields.get('name', ''),
            'relays': relays,
            'added_at': fields.get('added_at', ''),
            'last_seen': fields.get('last_seen', ''),
            'last_dm_at': fields.get('last_dm_at', ''),
        }

    def update_last_seen(self, pubkey: str):
        """Update the last_seen timestamp for an agent."""
        now = str(int(time.time()))
        self.conn.hset(self._hash_key(pubkey), 'last_seen', now)

    def update_last_dm(self, pubkey: str):
        """Update the last_dm_at timestamp for an agent."""
        now = str(int(time.time()))
        self.conn.hset(self._hash_key(pubkey), 'last_dm_at', now)

    def count(self) -> int:
        """Return the number of known agents."""
        return self.conn.scard(self.set_key)

    def clear_all(self, force: bool = False) -> int:
        """
        Remove ALL agents from the contact list.

        Returns the number removed.
        Requires force=True to proceed (safety guard).
        """
        if not force:
            raise AgentContactsError(
                'clear_all requires force=True to proceed'
            )
        pubkeys = self.conn.smembers(self.set_key)
        if not pubkeys:
            return 0

        pipe = self.conn.pipeline()
        for pk in pubkeys:
            pipe.delete(self._hash_key(pk))
        pipe.delete(self.set_key)
        pipe.execute()

        count = len(pubkeys)
        if count and force:
            self._log_event(
                message=f'Cleared all {count} agents from contact list',
                tags=['agent', 'contacts'],
                level='WARN',
            )
        return count


# ---------------------------------------------------------------------------
# CLI convenience (for quick ad-hoc queries)
# ---------------------------------------------------------------------------
def _main():
    import argparse
    parser = argparse.ArgumentParser(description='Agent Contacts DB CLI')
    parser.add_argument('action', choices=['count', 'list', 'get'])
    parser.add_argument('--pubkey', help='Pubkey for get action')
    args = parser.parse_args()

    db = AgentContactsDB()
    if args.action == 'count':
        print(f'Known agents: {db.count()}')
    elif args.action == 'list':
        agents = db.list_agents()
        if agents:
            for a in agents:
                print(f"  {a['pubkey'][:16]}...  {a['name'] or '(no name)'}")
        else:
            print('(empty)')
    elif args.action == 'get':
        if not args.pubkey:
            print('error: --pubkey required for get')
            return 1
        agent = db.get_agent(args.pubkey)
        if agent:
            print(json.dumps(agent, indent=2))
        else:
            print('Not found')
    db.close()
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(_main())
