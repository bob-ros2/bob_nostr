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
chronology_cli.py — Command-line interface for the Chronology skill.

Usage:
  chronology_cli.py log -m "message" -t tag1,tag2 -l INFO -s source
  chronology_cli.py query [--tags tag1,tag2] [--level INFO] [--limit 10]
                         [--since "2026-01-01 00:00:00"] [--until "2026-12-31 23:59:59"]
  chronology_cli.py stats
  chronology_cli.py clear [--force]
  chronology_cli.py trim [--maxlen 5000]
"""

import argparse
import json
import sys

from chronology_engine import ChronologyEngine, ChronologyError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='chronology',
        description='Persistent, tagged event diary backed by Redis.',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # ---- log ----
    p_log = sub.add_parser('log', help='Log a new event')
    p_log.add_argument('-m', '--message', required=True, help='Event message')
    p_log.add_argument('-t', '--tags', default='', help='Comma-separated tags')
    p_log.add_argument('-l', '--level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARN', 'ERROR'],
                       help='Severity level (default: INFO)')
    p_log.add_argument('-s', '--source', default='', help='Source component name')

    # ---- query ----
    p_query = sub.add_parser('query', help='Query events')
    p_query.add_argument('-t', '--tags', default='', help='Comma-separated tag filter')
    p_query.add_argument('-l', '--level', default='',
                         choices=['', 'DEBUG', 'INFO', 'WARN', 'ERROR'],
                         help='Filter by severity level')
    p_query.add_argument('-s', '--source', default='', help='Filter by source')
    p_query.add_argument('--since', default='', help='Start time (ISO-8601)')
    p_query.add_argument('--until', default='', help='End time (ISO-8601)')
    p_query.add_argument('-n', '--limit', type=int, default=10,
                         help='Max results (default: 10)')
    p_query.add_argument('--json', action='store_true',
                         help='Output raw JSON instead of table')

    # ---- stats ----
    sub.add_parser('stats', help='Show event store statistics')

    # ---- clear ----
    p_clear = sub.add_parser('clear', help='Delete ALL chronology events')
    p_clear.add_argument('--force', action='store_true',
                         help='Skip confirmation prompt')

    # ---- trim ----
    p_trim = sub.add_parser('trim', help='Trim stream to maxlen entries')
    p_trim.add_argument('--maxlen', type=int, default=0,
                        help='Target max entries (default: CHRONO_MAX_EVENTS)')

    return parser


def cmd_log(args, engine: ChronologyEngine):
    tags = [t.strip() for t in args.tags.split(',') if t.strip()]
    event_id = engine.log_event(
        message=args.message,
        tags=tags,
        level=args.level,
        source=args.source or None,
    )
    print(f'✅ Event logged (stream_id: {event_id})')
    return 0


def cmd_query(args, engine: ChronologyEngine):
    tags = [t.strip() for t in args.tags.split(',') if t.strip()]
    level = args.level if args.level else None
    source = args.source if args.source else None

    events = engine.query_events(
        tags=tags or None,
        level=level,
        source=source,
        since=args.since or None,
        until=args.until or None,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(events, indent=2, default=str))
        return 0

    if not events:
        info_icon = '\u2139\ufe0f'
        print(f'{info_icon}  No events found.')
        return 0

    clipboard_icon = '\U0001f4cb'
    print(f'{clipboard_icon} Found {len(events)} event(s):\n')
    for i, ev in enumerate(events, 1):
        ts = ev.get('timestamp', '?')
        lvl = ev.get('level', '?').ljust(5)
        tags_str = ','.join(ev.get('tags', [])) or '-'
        src = ev.get('source', '') or '-'
        msg = ev.get('message', '?')
        eid = ev.get('_stream_id', '?')
        box_draw = '\u2514\u2500'
        print(f'  [{i:3d}] {ts} | {lvl} | [{tags_str}] | {src}\n'
              f'        {msg}\n'
              f'        {box_draw} stream: {eid}')
    return 0


def cmd_stats(args, engine: ChronologyEngine):
    stats = engine.get_stats()
    chart_icon = '\U0001f4ca'
    print(f'{chart_icon} Chronology Statistics')
    print('=' * 40)
    total = stats['total_events']
    max_ev = stats['max_events']
    redis_host = stats['redis_host']
    redis_port = stats['redis_port']
    stream_key = stats['stream_key']
    print(f'  Total events : {total}')
    print(f'  Max events   : {max_ev}')
    print(f'  Redis server : {redis_host}:{redis_port}')
    print(f'  Stream key   : {stream_key}')
    if stats['tags']:
        tags = stats['tags']
        print(f'\n  Tags ({len(tags)}):')
        bullet = '\u2022'
        for tag, count in sorted(tags.items()):
            print(f'    {bullet} {tag}: {count} events')
    if stats['sources']:
        sources = stats['sources']
        print(f'\n  Sources ({len(sources)}):')
        bullet = '\u2022'
        for src in sources:
            print(f'    {bullet} {src}')
    return 0


def cmd_clear(args, engine: ChronologyEngine):
    if not args.force:
        warning_icon = '\u26a0\ufe0f'
        ans = input(f'{warning_icon}  This will DELETE ALL chronology events. Continue? [y/N] ')
        if ans.lower() not in ('y', 'yes'):
            print('Aborted.')
            return 1
    deleted = engine.clear_all()
    trash_icon = '\U0001f5d1\ufe0f'
    print(f'{trash_icon}  Deleted {deleted} key(s). All chronology data cleared.')
    return 0


def cmd_trim(args, engine: ChronologyEngine):
    target = args.maxlen if args.maxlen > 0 else None
    deleted = engine.trim_events(maxlen=target)
    scissors_icon = '\u2702\ufe0f'
    print(f'{scissors_icon}  Trimmed {deleted} event(s) from stream.')
    return 0


def main():
    parser = build_parser()
    args = parser.parse_args()

    engine = ChronologyEngine()

    try:
        if args.command == 'log':
            return cmd_log(args, engine)
        elif args.command == 'query':
            return cmd_query(args, engine)
        elif args.command == 'stats':
            return cmd_stats(args, engine)
        elif args.command == 'clear':
            return cmd_clear(args, engine)
        elif args.command == 'trim':
            return cmd_trim(args, engine)
        else:
            parser.print_help()
            return 1
    except ChronologyError as e:
        x_icon = '\u274c'
        print(f'{x_icon} Error: {e}', file=sys.stderr)
        return 1
    except Exception as e:
        x_icon = '\u274c'
        print(f'{x_icon} Unexpected error: {e}', file=sys.stderr)
        return 1
    finally:
        engine.close()


if __name__ == '__main__':
    sys.exit(main())
