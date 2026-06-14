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
Journal Retention – Manages local journal file lifecycle.

Lists journal files, removes old ones beyond a configurable max age,
and optionally compresses old journals into tar.gz archives.
Does NOT interact with Nostr relays – Nostr-side retention is handled
by the nostr_memory skill.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import tarfile


def find_journals(directory: Path) -> list:
    """Find all journal markdown files in directory, sorted by name."""
    if not directory.exists():
        return []
    journals = sorted(directory.glob('*_agent_journal.md'))
    return journals


def get_journal_date(filename: str) -> datetime.datetime:
    """Extract date from journal filename YYYYMMDD_HHMMSS_agent_journal.md."""
    try:
        date_part = filename.split('_agent_journal.md')[0]
        return datetime.datetime.strptime(date_part, '%Y%m%d_%H%M%S')
    except (ValueError, IndexError):
        # Return a very old date as fallback (to be deleted if age policy active)
        return datetime.datetime(2000, 1, 1)


def archive_journals(journals: list, archive_path: Path) -> str:
    """Compress a list of journal file paths into a tar.gz archive."""
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode='w:gz', compresslevel=6) as tar:
        for jp in journals:
            if jp.exists():
                tar.add(str(jp), arcname=jp.name)
    return str(archive_path)


def cmd_list(args):
    directory = Path(args.directory)
    if not directory.is_absolute():
        directory = Path(os.getcwd()) / directory

    journals = find_journals(directory)
    if not journals:
        print('No journal files found.')
        return

    print(f"\n  {'Filename':<40} {'Size':>10}  {'Date (UTC)'}")
    print(f"  {'-'*40} {'-'*10}  {'-'*20}")
    total_size = 0
    for jp in journals:
        size = jp.stat().st_size
        total_size += size
        date = get_journal_date(jp.name)
        print(f"  {jp.name:<40} {size:>10,}  {date.strftime('%Y-%m-%d %H:%M')}")
    print(f"  {'-'*40} {'-'*10}")
    print(f"  {'Total: ' + str(len(journals)) + ' files':<40} {total_size:>10,}\n")


def cmd_clean(args):
    directory = Path(args.directory)
    if not directory.is_absolute():
        directory = Path(os.getcwd()) / directory

    journals = find_journals(directory)
    if not journals:
        print('No journal files to clean.')
        return

    max_age = int(args.max_age)
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age)

    old = []
    keep = []
    for jp in journals:
        date = get_journal_date(jp.name)
        if date < cutoff:
            old.append(jp)
        else:
            keep.append(jp)

    if not old:
        print(f'No journals older than {max_age} days. Keeping all {len(keep)} files.')
        return

    if args.dry_run:
        print(f'DRY RUN: Would archive/delete {len(old)} files older than {max_age} days:')
        for jp in old:
            date = get_journal_date(jp.name)
            print(f"  - {jp.name} ({date.strftime('%Y-%m-%d')})")
        print(f'Would keep {len(keep)} files.')
        return

    # Archive old journals if requested
    if args.archive:
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        archive_name = f'journal_archive_{timestamp}.tar.gz'
        archive_path = directory / archive_name
        archive_journals(old, archive_path)
        print(f'Archived {len(old)} journal(s) to {archive_path}')

    # Remove old files
    removed = 0
    for jp in old:
        try:
            jp.unlink()
            removed += 1
        except OSError as exc:
            print(f'[WARN] Could not remove {jp}: {exc}', file=sys.stderr)

    print(json.dumps({
        'status': 'cleaned',
        'removed': removed,
        'kept': len(keep),
        'archive': str(archive_path) if args.archive else None
    }, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(
        description='Journal Retention – Manage local journal file lifecycle'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p_list = sub.add_parser('list', help='List all local journal files')
    p_list.add_argument(
        '--directory', default='journal/',
        help='Directory containing journal files (default: journal/)'
    )

    p_clean = sub.add_parser('clean', help='Remove old journal files')
    p_clean.add_argument(
        '--directory', default='journal/',
        help='Directory containing journal files (default: journal/)'
    )
    p_clean.add_argument(
        '--max-age', default=30,
        help='Maximum age in days before removal (default: 30)'
    )
    p_clean.add_argument(
        '--archive', action='store_true',
        help='Create tar.gz archive of old journals before removal'
    )
    p_clean.add_argument(
        '--dry-run', action='store_true',
        help='Show what would be deleted without actually removing'
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == 'list':
        cmd_list(args)
    elif args.command == 'clean':
        cmd_clean(args)


if __name__ == '__main__':
    main()
