#!/usr/bin/env python3
# Copyright 2026 Bob Nostr contributors
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
chronology_engine.py — Core Redis-backed event log engine.

All configuration via CHRONO_* environment variables with sensible defaults.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from typing import Optional

import redis

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

logger = logging.getLogger('chronology')

# ---------------------------------------------------------------------------
# Environment variable defaults
# ---------------------------------------------------------------------------
REDIS_HOST = os.environ.get('CHRONO_REDIS_HOST', 'nostr-redis')
REDIS_PORT = int(os.environ.get('CHRONO_REDIS_PORT', '6379'))
REDIS_DB = int(os.environ.get('CHRONO_REDIS_DB', '0'))
STREAM_KEY = os.environ.get('CHRONO_STREAM_KEY', 'chronology:events')
MAX_EVENTS = int(os.environ.get('CHRONO_MAX_EVENTS', '10000'))
TTL_HOURS = int(os.environ.get('CHRONO_TTL_HOURS', '0'))
TRIM_ON_LOG = os.environ.get('CHRONO_TRIM_ON_LOG', 'true').lower() in ('1', 'true', 'yes')

TAG_SET_PREFIX = 'chronology:tags:'
SOURCE_SET_KEY = 'chronology:sources'


class ChronologyError(Exception):
    """Base exception for chronology operations."""

    pass


class ChronologyEngine:
    """Redis-backed structured event logger with tag indexing."""

    def __init__(self, host: str = None, port: int = None, db: int = None,
                 stream_key: str = None, max_events: int = None,
                 ttl_hours: int = None, trim_on_log: bool = None):
        self.host = host or REDIS_HOST
        self.port = port or REDIS_PORT
        self.db = db or REDIS_DB
        self.stream_key = stream_key or STREAM_KEY
        self.max_events = max_events or MAX_EVENTS
        self.ttl_hours = ttl_hours or TTL_HOURS
        self.trim_on_log = trim_on_log if trim_on_log is not None else TRIM_ON_LOG

        self._redis: Optional[redis.Redis] = None

    # ------------------------------------------------------------------
    # Connection management
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
    # Core: log an event
    # ------------------------------------------------------------------
    def log_event(self, message: str, tags: list = None, level: str = 'INFO',
                  source: str = None, timestamp: str = None) -> str:
        """
        Write a structured event to the Redis stream.

        Returns the Redis Stream entry ID.
        """
        tags = tags or []
        level = level.upper()
        if level not in ('DEBUG', 'INFO', 'WARN', 'ERROR'):
            raise ChronologyError(f'Invalid level: {level}')

        ts = timestamp or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        # Generate a deterministic event_id from content for tagging
        sorted_tags = ','.join(sorted(tags))
        raw = f'{ts}:{message}:{level}:{sorted_tags}:{source or ""}'
        event_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        body = {
            'event_id': event_id,
            'timestamp': ts,
            'message': message,
            'level': level,
            'tags': ','.join(tags),
            'source': source or '',
        }

        # Write to stream
        stream_entry_id = self.conn.xadd(self.stream_key, body, maxlen=None)

        # Index by tag
        pipe = self.conn.pipeline()
        for tag in tags:
            tag_key = f'{TAG_SET_PREFIX}{tag}'
            pipe.sadd(tag_key, event_id)
            # Set TTL on tag index if configured
            if self.ttl_hours > 0:
                pipe.expire(tag_key, self.ttl_hours * 3600)
        # Index by source
        if source:
            pipe.sadd(SOURCE_SET_KEY, source)
        pipe.execute()

        # Trim if configured
        if self.trim_on_log:
            self.conn.xtrim(self.stream_key, maxlen=MAX_EVENTS, approximate=True)

        logger.debug('Logged event %s: %s', stream_entry_id, message[:80])
        return stream_entry_id

    # ------------------------------------------------------------------
    # Query events
    # ------------------------------------------------------------------
    def query_events(self, tags: list = None, level: str = None,
                     source: str = None, since: str = None, until: str = None,
                     limit: int = 10) -> list:
        """
        Query events from the stream, filtered by tags, level, source, or time range.

        Returns a list of dicts sorted newest-first.
        """
        limit = limit or 10

        # If tags are provided, intersect tag sets to get candidate event_ids
        if tags:
            tag_keys = [f'{TAG_SET_PREFIX}{t}' for t in tags]
            try:
                candidate_ids = self.conn.sinter(tag_keys)
            except redis.ResponseError:
                candidate_ids = set()
            if not candidate_ids:
                return []
            # Fetch from stream — we need to scan stream entries to match event_ids
            all_entries = self._fetch_all_stream_entries(since=since, until=until)
            matched = [e for e in all_entries if e.get('event_id') in candidate_ids]
        else:
            matched = self._fetch_all_stream_entries(since=since, until=until)

        # Filter by level
        if level:
            matched = [e for e in matched if e.get('level', '').upper() == level.upper()]

        # Filter by source
        if source:
            matched = [e for e in matched if e.get('source', '') == source]

        # Sort newest-first by stream_id
        matched.sort(key=lambda e: e.get('_stream_id', '0'), reverse=True)

        return matched[:limit]

    def _fetch_all_stream_entries(self, since: str = None, until: str = None) -> list:
        """Fetch stream entries, optionally filtered by time range."""
        since_id = '-'
        until_id = '+'
        if since:
            try:
                dt = datetime.fromisoformat(since)
                # Convert to Redis stream timestamp format (milliseconds)
                ms = int(dt.timestamp() * 1000)
                since_id = f'{ms}-0'
            except ValueError:
                pass
        if until:
            try:
                dt = datetime.fromisoformat(until)
                ms = int(dt.timestamp() * 1000)
                until_id = f'{ms}-9999999999999'
            except ValueError:
                pass

        raw = self.conn.xrange(self.stream_key, min=since_id, max=until_id, count=10000)
        entries = []
        for stream_id, fields in raw:
            entry = dict(fields)
            entry['_stream_id'] = stream_id
            entry['tags'] = [t for t in entry.get('tags', '').split(',') if t]
            entries.append(entry)
        return entries

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def get_stats(self) -> dict:
        """Return statistics about the event store."""
        total = self.conn.xlen(self.stream_key)
        tag_keys = self.conn.keys(f'{TAG_SET_PREFIX}*')
        tag_counts = {}
        for key in tag_keys:
            tagname = key.replace(TAG_SET_PREFIX, '', 1)
            count = self.conn.scard(key)
            tag_counts[tagname] = count

        sources = self.conn.smembers(SOURCE_SET_KEY)
        return {
            'total_events': total,
            'max_events': self.max_events,
            'tags': tag_counts,
            'sources': sorted(sources) if sources else [],
            'redis_host': self.host,
            'redis_port': self.port,
            'stream_key': self.stream_key,
        }

    # ------------------------------------------------------------------
    # Clear all data
    # ------------------------------------------------------------------
    def clear_all(self) -> int:
        """Delete all chronology data. Returns number of keys deleted."""
        keys = [self.stream_key]
        keys += self.conn.keys(f'{TAG_SET_PREFIX}*')
        keys.append(SOURCE_SET_KEY)
        deleted = 0
        for key in keys:
            deleted += self.conn.delete(key)
        return deleted

    # ------------------------------------------------------------------
    # Trim manually
    # ------------------------------------------------------------------
    def trim_events(self, maxlen: int = None) -> int:
        """Explicitly trim the stream to maxlen entries. Returns count of deleted entries."""
        target = maxlen or self.max_events
        return self.conn.xtrim(self.stream_key, maxlen=target, approximate=True)


# ===================================================================
# Async version (for use inside async agents)
# ===================================================================
class AsyncChronologyEngine:
    """Async version of ChronologyEngine using redis.asyncio."""

    def __init__(self, host: str = None, port: int = None, db: int = None,
                 stream_key: str = None, max_events: int = None,
                 ttl_hours: int = None, trim_on_log: bool = None):
        if aioredis is None:
            raise ImportError('redis.asyncio not available. Install with: pip install redis')

        self.host = host or REDIS_HOST
        self.port = port or REDIS_PORT
        self.db = db or REDIS_DB
        self.stream_key = stream_key or STREAM_KEY
        self.max_events = max_events or MAX_EVENTS
        self.ttl_hours = ttl_hours or TTL_HOURS
        self.trim_on_log = trim_on_log if trim_on_log is not None else TRIM_ON_LOG
        self._redis = None

    @property
    async def conn(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
            )
            await self._redis.ping()
        return self._redis

    async def close(self):
        if self._redis is not None:
            await self._redis.close()
            self._redis = None

    async def log_event(self, message: str, tags: list = None,
                        level: str = 'INFO', source: str = None,
                        timestamp: str = None) -> str:
        tags = tags or []
        level = level.upper()
        if level not in ('DEBUG', 'INFO', 'WARN', 'ERROR'):
            raise ChronologyError(f'Invalid level: {level}')

        ts = timestamp or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        sorted_tags = ','.join(sorted(tags))
        raw = f'{ts}:{message}:{level}:{sorted_tags}:{source or ""}'
        event_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        body = {
            'event_id': event_id,
            'timestamp': ts,
            'message': message,
            'level': level,
            'tags': ','.join(tags),
            'source': source or '',
        }

        c = await self.conn
        stream_entry_id = await c.xadd(self.stream_key, body, maxlen=None)

        pipe = c.pipeline()
        for tag in tags:
            tag_key = f'{TAG_SET_PREFIX}{tag}'
            pipe.sadd(tag_key, event_id)
            if self.ttl_hours > 0:
                pipe.expire(tag_key, self.ttl_hours * 3600)
        if source:
            pipe.sadd(SOURCE_SET_KEY, source)
        await pipe.execute()

        if self.trim_on_log:
            await c.xtrim(self.stream_key, maxlen=self.max_events, approximate=True)

        return stream_entry_id

    async def query_events(self, tags: list = None, level: str = None,
                           source: str = None, since: str = None, until: str = None,
                           limit: int = 10) -> list:
        c = await self.conn
        limit = limit or 10

        if tags:
            tag_keys = [f'{TAG_SET_PREFIX}{t}' for t in tags]
            candidate_ids = await c.sinter(tag_keys)
            if not candidate_ids:
                return []
            all_entries = await self._fetch_all_stream_entries(since=since, until=until)
            matched = [e for e in all_entries if e.get('event_id') in candidate_ids]
        else:
            matched = await self._fetch_all_stream_entries(since=since, until=until)

        if level:
            matched = [e for e in matched if e.get('level', '').upper() == level.upper()]
        if source:
            matched = [e for e in matched if e.get('source', '') == source]

        matched.sort(key=lambda e: e.get('_stream_id', '0'), reverse=True)
        return matched[:limit]

    async def _fetch_all_stream_entries(self, since: str = None, until: str = None) -> list:
        c = await self.conn
        since_id = '-'
        until_id = '+'
        if since:
            try:
                dt = datetime.fromisoformat(since)
                ms = int(dt.timestamp() * 1000)
                since_id = f'{ms}-0'
            except ValueError:
                pass
        if until:
            try:
                dt = datetime.fromisoformat(until)
                ms = int(dt.timestamp() * 1000)
                until_id = f'{ms}-9999999999999'
            except ValueError:
                pass

        raw = await c.xrange(self.stream_key, min=since_id, max=until_id, count=10000)
        entries = []
        for stream_id, fields in raw:
            entry = dict(fields)
            entry['_stream_id'] = stream_id
            entry['tags'] = [t for t in entry.get('tags', '').split(',') if t]
            entries.append(entry)
        return entries

    async def get_stats(self) -> dict:
        c = await self.conn
        total = await c.xlen(self.stream_key)
        tag_keys = await c.keys(f'{TAG_SET_PREFIX}*')
        tag_counts = {}
        for key in tag_keys:
            tagname = key.replace(TAG_SET_PREFIX, '', 1)
            count = await c.scard(key)
            tag_counts[tagname] = count
        sources = await c.smembers(SOURCE_SET_KEY)
        return {
            'total_events': total,
            'max_events': self.max_events,
            'tags': tag_counts,
            'sources': sorted(sources) if sources else [],
            'redis_host': self.host,
            'redis_port': self.port,
            'stream_key': self.stream_key,
        }

    async def clear_all(self) -> int:
        c = await self.conn
        keys = [self.stream_key]
        keys += await c.keys(f'{TAG_SET_PREFIX}*')
        keys.append(SOURCE_SET_KEY)
        deleted = 0
        for key in keys:
            deleted += await c.delete(key)
        return deleted

    async def trim_events(self, maxlen: int = None) -> int:
        c = await self.conn
        target = maxlen or self.max_events
        return await c.xtrim(self.stream_key, maxlen=target, approximate=True)


# ===================================================================
# Direct CLI entry point
# ===================================================================
if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.WARN)

    engine = ChronologyEngine()
    if len(sys.argv) > 1 and sys.argv[1] == 'stats':
        stats = engine.get_stats()
        print(json.dumps(stats, indent=2, default=str))
    elif len(sys.argv) > 1 and sys.argv[1] == 'clear':
        engine.clear_all()
        print('All chronology events cleared.')
    else:
        print(f'chronology_engine: {len(sys.argv)-1} entries processed')
