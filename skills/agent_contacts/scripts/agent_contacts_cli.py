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
agent_contacts_cli.py — CLI for managing Nostr agent contacts.

All important parameters are configurable via environment variables:

  NOSTR_SIGNER_URL                 (default: http://nostr-signer:8080)
  NOSTR_RELAYS                     (default: ws://localhost:8781,ws://localhost:8782)
  AGENT_CONTACTS_REDIS_HOST         (default: localhost)
  AGENT_CONTACTS_REDIS_PORT         (default: 6379)
  AGENT_PROFILE_NAME / _ABOUT / _PICTURE

Usage:
  agent_contacts_cli.py add --pubkey <hex> --name <alias> [--relays <urls>]
  agent_contacts_cli.py list [--json]
  agent_contacts_cli.py remove --pubkey <hex>
  agent_contacts_cli.py send-dm --pubkey <hex> --message <text>
  agent_contacts_cli.py set-profile [--name <n>] [--about <a>] [--picture <u>]
  agent_contacts_cli.py show-profile
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

# ---------------------------------------------------------------------------
# Path setup: allow imports from sibling modules and from nostr_memory
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(_SCRIPT_DIR)
_AGENT_CONTACTS_DIR = _SKILL_DIR
_SKILLS_DIR = os.path.dirname(_AGENT_CONTACTS_DIR)
_NOSTR_MEMORY_DIR = os.path.join(_SKILLS_DIR, 'nostr_memory', 'scripts')
_CHRONOLOGY_DIR = os.path.join(_SKILLS_DIR, 'chronology', 'scripts')

for _p in [_SCRIPT_DIR, _NOSTR_MEMORY_DIR, _CHRONOLOGY_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from agent_contacts_db import AgentContactsDB, AgentContactsError  # noqa: E402
from nostr_publisher import NostrPublisher, NostrPublisherError  # noqa: E402

logger = logging.getLogger('agent_contacts.cli')

# ASCII icons
ICON_OK = '\u2705'
ICON_FAIL = '\u274c'
ICON_WARN = '\u26a0\ufe0f'
ICON_INFO = '\u2139\ufe0f'


def _load_env():
    """Load .env for local testing."""
    current_dir = _SCRIPT_DIR
    for _ in range(8):
        env_path = os.path.join(current_dir, '.env')
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            key, val = line.split('=', 1)
                            key = key.strip()
                            val = val.strip().strip("'\"")
                            if key and key not in os.environ:
                                os.environ[key] = val
            except Exception:
                pass
            return
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent


_load_env()


# ---------------------------------------------------------------------------
# Command: add
# ---------------------------------------------------------------------------
def cmd_add(args):
    """Add an agent to the contact list and publish Kind 3."""
    db = AgentContactsDB()
    pub = NostrPublisher()

    try:
        relays_list = []
        if args.relays:
            relays_list = [r.strip() for r in args.relays.split(',') if r.strip()]

        is_new = db.add_agent(
            pubkey=args.pubkey,
            name=args.name,
            relays=relays_list,
        )
    except AgentContactsError as e:
        print(f'{ICON_FAIL} {e}')
        db.close()
        return 1

    # Publish updated Kind 3 (follow list) to relays
    try:
        all_agents = db.list_agents()
        result = pub.publish_kind3(all_agents)
        label = 'New agent added' if is_new else 'Agent updated'
        print(f'{ICON_OK} {label}: {args.name or args.pubkey[:12]}...')
        print(f'   Kind 3 published | Event ID: {result["event_id"][:16]}... '
              f'| Relays: {result["relay_count"]} | Follows: {result["agent_count"]}')
    except NostrPublisherError as e:
        print(f'{ICON_WARN} Agent saved to Redis, but Kind 3 publish failed: {e}')
    except Exception as e:
        print(f'{ICON_WARN} Agent saved, but publish error: {e}')

    db.close()
    return 0


# ---------------------------------------------------------------------------
# Command: list
# ---------------------------------------------------------------------------
def cmd_list(args):
    """List all known agents."""
    db = AgentContactsDB()
    agents = db.list_agents()
    db.close()

    if not agents:
        print(f'{ICON_INFO} No agents in contact list. Add one with:')
        print('   agent_contacts_cli.py add --pubkey <hex> --name <alias>')
        return 0

    if args.json:
        print(json.dumps(agents, indent=2))
        return 0

    # Table output
    print(f'\n{"Pubkey":<20} {"Name":<20} {"Relays":<8} {"Added":<12} {"Last Seen":<12}')
    print('-' * 80)
    for a in agents:
        pk_short = a['pubkey'][:12] + '...'
        name = a['name'] or '(unnamed)'
        relay_count = str(len(a['relays']))
        added = _ts_to_short(a.get('added_at', ''))
        last_seen = _ts_to_short(a.get('last_seen', ''))
        print(f'{pk_short:<20} {name:<20} {relay_count:<8} {added:<12} {last_seen:<12}')

    print(f'\n{len(agents)} agent(s) total.\n')
    return 0


# ---------------------------------------------------------------------------
# Command: remove
# ---------------------------------------------------------------------------
def cmd_remove(args):
    """Remove an agent and publish updated Kind 3."""
    db = AgentContactsDB()
    pub = NostrPublisher()

    # Check if agent exists
    agent = db.get_agent(args.pubkey)
    if not agent:
        print(f'{ICON_WARN} Agent {args.pubkey[:12]}... not found in contact list.')
        db.close()
        return 1

    name = agent.get('name', '') or args.pubkey[:12] + '...'

    try:
        db.remove_agent(args.pubkey)
    except AgentContactsError as e:
        print(f'{ICON_FAIL} {e}')
        db.close()
        return 1

    # Publish updated Kind 3
    try:
        all_agents = db.list_agents()
        result = pub.publish_kind3(all_agents)
        print(f'{ICON_OK} Removed agent: {name}')
        print(f'   Kind 3 published | Event ID: {result["event_id"][:16]}... '
              f'| Relays: {result["relay_count"]} | Follows: {result["agent_count"]}')
    except NostrPublisherError as e:
        print(f'{ICON_WARN} Agent removed from Redis, but Kind 3 publish failed: {e}')
    except Exception as e:
        print(f'{ICON_WARN} Agent removed, but publish error: {e}')

    db.close()
    return 0


# ---------------------------------------------------------------------------
# Command: send-dm
# ---------------------------------------------------------------------------
def cmd_send_dm(args):
    """Send an encrypted DM via NIP-17 Gift Wrap."""
    db = AgentContactsDB()
    pub = NostrPublisher()

    # Validate receiver exists in contact list
    agent = db.get_agent(args.pubkey)
    if not agent:
        print(f'{ICON_WARN} Agent {args.pubkey[:12]}... not in contact list.')
        print('   Add them first: agent_contacts_cli.py add --pubkey ... --name ...')
        db.close()
        return 1

    name = agent.get('name', '') or args.pubkey[:12] + '...'

    try:
        result = pub.publish_kind1059(
            receiver_pubkey=args.pubkey,
            message=args.message,
        )
        db.update_last_dm(args.pubkey)
        print(f'{ICON_OK} DM sent to {name}')
        print(f'   Event ID: {result["event_id"][:16]}... | Relays: {result["relay_count"]}')
    except NostrPublisherError as e:
        print(f'{ICON_FAIL} DM failed: {e}')
        db.close()
        return 1
    except Exception as e:
        print(f'{ICON_FAIL} DM error: {e}')
        db.close()
        return 1

    db.close()
    return 0


# ---------------------------------------------------------------------------
# Command: set-profile
# ---------------------------------------------------------------------------
def cmd_set_profile(args):
    """Publish a Kind 0 profile event."""
    pub = NostrPublisher()

    try:
        profile = {}
        if args.name is not None:
            profile['name'] = args.name
        if args.about is not None:
            profile['about'] = args.about
        if args.picture is not None:
            profile['picture'] = args.picture

        result = pub.publish_kind0(profile=profile if profile else None)
        print(f'{ICON_OK} Profile published (Kind 0)')
        print(f'   Event ID: {result["event_id"][:16]}... | Relays: {result["relay_count"]}')
        print(f'   Name: {result["profile"]["name"]}')
        print(f'   About: {result["profile"]["about"]}')
    except NostrPublisherError as e:
        print(f'{ICON_FAIL} Profile publish failed: {e}')
        return 1
    except Exception as e:
        print(f'{ICON_FAIL} Profile error: {e}')
        return 1

    return 0


# ---------------------------------------------------------------------------
# Command: show-profile
# ---------------------------------------------------------------------------
def cmd_show_profile(args):
    """Fetch and display the current Kind 0 profile from relays."""
    try:
        from nostr_memory_tool import NostrMemoryTool
    except ImportError:
        print(f'{ICON_FAIL} nostr_memory_tool not available. Make sure it is installed.')
        return 1

    # Get our own pubkey
    pub = NostrPublisher()
    try:
        our_pubkey = pub.get_public_key_hex()
    except Exception as e:
        print(f'{ICON_FAIL} Cannot get public key from signer: {e}')
        return 1

    async def _fetch():
        tool = NostrMemoryTool()
        events = await tool.fetch_events(kind=0, authors=[our_pubkey], limit=1)
        if not events:
            print(f'{ICON_INFO} No profile event (Kind 0) found for this agent.')
            return False
        ev = events[0]
        try:
            content = json.loads(ev['content'])
        except (json.JSONDecodeError, KeyError):
            content = {'raw': ev.get('content', '(unparseable)')}

        print(f'\n{ICON_INFO} Current Profile (Kind 0):')
        print(f'   Event ID: {ev.get("event_id", ev.get("id", "(unknown"))}')
        print(f'   Created: {ev.get("created_at", "(unknown)")}')
        print('   Content:')
        for k, v in content.items():
            print(f'      {k}: {v}')
        print()
        return True

    try:
        asyncio.run(_fetch())
    except Exception as e:
        print(f'{ICON_FAIL} Failed to fetch profile: {e}')
        return 1

    return 0


# ---------------------------------------------------------------------------
# Helper: timestamp to short date
# ---------------------------------------------------------------------------
def _ts_to_short(ts_str: str) -> str:
    """Convert unix timestamp string or ISO string to short readable date."""
    if not ts_str:
        return '-'
    try:
        # Unix timestamp (seconds)
        ts = int(ts_str)
        return time.strftime('%Y-%m-%d', time.gmtime(ts))
    except (ValueError, TypeError):
        pass
    # Try ISO format
    if len(ts_str) >= 10:
        return ts_str[:10]
    return ts_str


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog='agent_contacts',
        description='Manage Nostr agent contacts (add/list/remove/send-dm/profile).',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # ---- add ----
    p_add = sub.add_parser('add', help='Add an agent to the contact list')
    p_add.add_argument('--pubkey', required=True, help='64-char hex public key')
    p_add.add_argument('--name', default='', help='Human-readable alias')
    p_add.add_argument('--relays', default='',
                       help='Comma-separated relay URLs the agent uses')

    # ---- list ----
    p_list = sub.add_parser('list', help='List all known agents')
    p_list.add_argument('--json', action='store_true',
                        help='Output raw JSON instead of table')

    # ---- remove ----
    p_remove = sub.add_parser('remove', help='Remove an agent from the contact list')
    p_remove.add_argument('--pubkey', required=True, help='64-char hex public key')

    # ---- send-dm ----
    p_dm = sub.add_parser('send-dm', help='Send encrypted DM via NIP-17')
    p_dm.add_argument('--pubkey', required=True, help='Recipient 64-char hex public key')
    p_dm.add_argument('--message', required=True, help='Message text')

    # ---- set-profile ----
    p_prof = sub.add_parser('set-profile', help='Publish Kind 0 profile event')
    p_prof.add_argument('--name', default=None, help='Display name')
    p_prof.add_argument('--about', default=None, help='Short bio/description')
    p_prof.add_argument('--picture', default=None, help='Profile picture URL')

    # ---- show-profile ----
    sub.add_parser('show-profile', help='Show current Kind 0 profile from relays')

    # ---- debug: count ----
    p_count = sub.add_parser('count', help='Show number of known agents (debug)')
    p_count.add_argument('--json', action='store_true', help='Output JSON')

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # Route commands
    cmd_map = {
        'add': cmd_add,
        'list': cmd_list,
        'remove': cmd_remove,
        'send-dm': cmd_send_dm,
        'set-profile': cmd_set_profile,
        'show-profile': cmd_show_profile,
        'count': cmd_count,
    }

    handler = cmd_map.get(args.command)
    if handler:
        try:
            return handler(args)
        except KeyboardInterrupt:
            print('\nInterrupted.')
            return 130
        except Exception as e:
            print(f'{ICON_FAIL} Unexpected error: {e}', file=sys.stderr)
            logger.exception('Unexpected error in CLI')
            return 1
    else:
        parser.print_help()
        return 1


def cmd_count(args):
    """Debug: count known agents."""
    db = AgentContactsDB()
    count = db.count()
    db.close()
    if args.json:
        print(json.dumps({'count': count}))
    else:
        print(f'{ICON_INFO} Known agents: {count}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
