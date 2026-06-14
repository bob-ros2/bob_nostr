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
demo_usage.py — Demonstrates how to use the Chronology skill programmatically.

Run with: python3 examples/demo_usage.py

Requires a running Redis server (see docker/compose-redis.yaml).
"""

import os
import sys
import time

# Add scripts directory to path so we can import the engine
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from chronology_engine import ChronologyEngine  # noqa: E402


def main():
    equals_line = '=' * 60
    print(equals_line)
    logo_icon = '\U0001f537'
    print(f'{logo_icon} Chronology Skill \u2014 Demo Usage')
    print(equals_line)

    # Initialize engine (defaults from environment or localhost:6379)
    engine = ChronologyEngine()

    try:
        # --- Log some events ---
        one_icon = '1\ufe0f\u20e3'
        print(f'\n{one_icon}  Logging events...')

        engine.log_event(
            message='Task scheduler started',
            tags=['scheduler', 'system'],
            level='INFO',
            source='demo_script',
        )
        check_icon = '\u2705'
        print(f'   {check_icon} Logged: Task scheduler started')

        time.sleep(0.5)

        engine.log_event(
            message='Executed cleanup task: removed 42 stale items',
            tags=['scheduler', 'cleanup'],
            level='INFO',
            source='cleanup_agent',
        )
        print(f'   {check_icon} Logged: cleanup task')

        time.sleep(0.3)

        engine.log_event(
            message='Container restart detected \u2014 reconnecting to relay',
            tags=['container', 'relay', 'reconnect'],
            level='WARN',
            source='nostr_client',
        )
        print(f'   {check_icon} Logged: container restart warning')

        engine.log_event(
            message='Failed to publish event: relay timeout',
            tags=['nostr', 'publish', 'error'],
            level='ERROR',
            source='nostr_client',
        )
        print(f'   {check_icon} Logged: publish failure')

        engine.log_event(
            message='Connection re-established to wss://relay.damus.io',
            tags=['nostr', 'relay', 'connection'],
            level='INFO',
            source='nostr_client',
        )
        print(f'   {check_icon} Logged: reconnection success')

        # --- Query all recent events ---
        two_icon = '2\ufe0f\u20e3'
        print(f'\n{two_icon}  Querying last 5 events...')
        events = engine.query_events(limit=5)
        for ev in events:
            ev_level = ev['level']
            ev_ts = ev['timestamp']
            ev_tags = ','.join(ev['tags'])
            ev_src = ev['source']
            ev_msg = ev['message']
            print(f'   [{ev_level}] {ev_ts} | [{ev_tags}] | {ev_src}')
            print(f'      {ev_msg}')

        # --- Query by tag ---
        three_icon = '3\ufe0f\u20e3'
        print(f"\n{three_icon}  Querying events tagged with 'nostr'...")
        nostr_events = engine.query_events(tags=['nostr'], limit=10)
        print(f"   Found {len(nostr_events)} events tagged 'nostr'")

        # --- Query by level ---
        four_icon = '4\ufe0f\u20e3'
        print(f'\n{four_icon}  Querying ERROR level events...')
        err_events = engine.query_events(level='ERROR', limit=10)
        err_count = len(err_events)
        print(f'   Found {err_count} ERROR events')
        bullet = '\u2022'
        for ev in err_events:
            ev_msg = ev['message']
            print(f'   {bullet} {ev_msg}')

        # --- Stats ---
        five_icon = '5\ufe0f\u20e3'
        print(f'\n{five_icon}  Chronology Statistics:')
        stats = engine.get_stats()
        total = stats['total_events']
        tags = stats['tags']
        sources = stats['sources']
        print(f'   Total events: {total}')
        print(f'   Tags: {tags}')
        print(f'   Sources: {sources}')

        print(f'\n{check_icon} Demo complete! All operations succeeded.\n')

    except Exception as e:
        x_icon = '\u274c'
        print(f'\n{x_icon} Error during demo: {e}')
        print('   Make sure Redis is running (docker compose -f compose-redis.yaml up -d)')
        return 1
    finally:
        engine.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
