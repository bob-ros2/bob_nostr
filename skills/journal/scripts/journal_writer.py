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
Journal Writer – Creates structured agent journal markdown files locally.

Collects system state (ROS 2 nodes, Docker containers, relay status, recent actions)
and writes a timestamped journal entry. Does NOT use nostr-sdk directly;
publishing to Nostr relays is delegated to the nostr_memory skill.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess


# ---------------------------------------------------------------------------
# Data collectors – each returns a string summary or structured data
# ---------------------------------------------------------------------------

def _run_cmd(cmd: list, timeout: int = 10) -> str:
    """Run a command and return stdout or error string."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip() or result.stderr.strip() or ''
    except FileNotFoundError:
        return f'[cmd not found: {cmd[0]}]'
    except subprocess.TimeoutExpired:
        return '[timeout]'
    except Exception as exc:
        return f'[error: {exc}]'


def collect_ros2_nodes() -> str:
    """Collect active ROS 2 nodes and topics."""
    nodes = _run_cmd(['ros2', 'node', 'list'])
    topics = _run_cmd(['ros2', 'topic', 'list'])
    parts = []
    if nodes and '[cmd not found' not in nodes and '[error' not in nodes:
        parts.append(f"Nodes: {', '.join(nodes.splitlines()[:10])}")
    else:
        parts.append('Nodes: N/A (ros2 CLI not available)')
    if topics and '[cmd not found' not in topics and '[error' not in topics:
        parts.append(f"Topics: {', '.join(topics.splitlines()[:15])}")
    return ' | '.join(parts) if parts else 'N/A'


def collect_docker_containers() -> str:
    """Collect running Docker containers."""
    out = _run_cmd(
        ['docker', 'ps', '--format', '{{.Names}}:{{.Status}}']
    )
    if not out or '[cmd not found' in out or '[error' in out:
        return 'N/A (docker CLI not available)'
    containers = [c.strip() for c in out.splitlines() if c.strip()]
    return ', '.join(containers[:20]) if containers else 'None'


def collect_relay_status() -> list:
    """Collect relay status via nostr_relay_manager if available."""
    relay_mgr = os.path.join(
        os.path.dirname(__file__), '..', '..', 'nostr_memory',
        'scripts', 'nostr_relay_manager.py'
    )
    relay_mgr = os.path.abspath(relay_mgr)
    if not os.path.exists(relay_mgr):
        return []
    out = _run_cmd(['python3', relay_mgr, '--action', 'status'], timeout=15)
    if not out or '[error' in out:
        return []
    # Parse the output for relay status lines
    relays = []
    for line in out.splitlines():
        line = line.strip()
        if 'online' in line.lower() or 'offline' in line.lower():
            relays.append(line)
    return relays


def collect_uptime() -> str:
    """Collect system uptime."""
    out = _run_cmd(['uptime', '-p'])
    if not out or '[cmd not found' in out:
        # Try reading /proc/uptime
        try:
            secs = float(Path('/proc/uptime').read_text().split()[0])
            h = int(secs // 3600)
            m = int((secs % 3600) // 60)
            return f'up {h} hours, {m} minutes'
        except Exception:
            pass
        return 'N/A'
    return out.strip()


def collect_memory_usage() -> str:
    """Collect memory usage."""
    out = _run_cmd(['free', '-m'])
    if not out or '[cmd not found' in out:
        return 'N/A'
    lines = out.splitlines()
    if len(lines) >= 2:
        parts = lines[1].split()
        if len(parts) >= 3:
            return f'{parts[2]} MB / {parts[1]} MB'
    return 'N/A'


def collect_recent_actions(actions_file: str = None) -> str:
    """Read recent actions from a log file if available."""
    if actions_file and os.path.exists(actions_file):
        try:
            lines = Path(actions_file).read_text().splitlines()
            return '\n'.join(f'- {idx}' for idx in lines[-10:])
        except Exception:
            pass
    return 'No recent actions recorded.'


def collect_errors(error_file: str = None) -> str:
    """Check for recent errors from log file."""
    if error_file and os.path.exists(error_file):
        try:
            lines = Path(error_file).read_text().splitlines()
            error_lines = [ln for ln in lines if 'error' in ln.lower()
                           or 'exception' in ln.lower()
                           or 'traceback' in ln.lower()]
            if error_lines:
                return f'{len(error_lines)} error(s) found'
            return 'none'
        except Exception:
            pass
    return 'unknown'


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def load_template(template_path: str = None) -> str:
    """Load journal template, with built-in fallback."""
    if template_path and os.path.exists(template_path):
        return Path(template_path).read_text(encoding='utf-8')

    builtin = os.path.join(
        os.path.dirname(__file__), '..', 'resources', 'journal_template.md'
    )
    builtin = os.path.abspath(builtin)
    if os.path.exists(builtin):
        return Path(builtin).read_text(encoding='utf-8')

    # Absolute minimal built-in
    return (
        '# Agent Journal: {timestamp}\n'
        '## Status\n{agent_status}\n\n'
        '## System\n{relay_table}\n'
    )


def render_journal(template: str, context: dict) -> str:
    """Fill template placeholders with collected data."""
    # Simple placeholder substitution
    result = template
    for key, value in context.items():
        result = result.replace('{' + key + '}', str(value))
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Journal Writer – Creates structured agent journal files'
    )
    parser.add_argument(
        '--output-dir', default='journal/',
        help='Directory for journal files (default: journal/)'
    )
    parser.add_argument(
        '--template', default=None,
        help='Path to custom template file'
    )
    parser.add_argument(
        '--collect', action='store_true',
        help='Collect system data automatically'
    )
    parser.add_argument(
        '--recent-actions-file', default=None,
        help='Path to recent actions log file'
    )
    parser.add_argument(
        '--error-file', default=None,
        help='Path to error log file'
    )
    parser.add_argument(
        '--model', default=os.environ.get('LLM_MODEL', 'unknown'),
        help='Model info string (default from LLM_MODEL env)'
    )
    parser.add_argument(
        '--agent-status', default='operational',
        help='Agent status description'
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve output directory
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = Path(os.getcwd()) / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect system data
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = now.strftime('%Y%m%d_%H%M%S')
    timestamp_display = now.strftime('%Y-%m-%d %H:%M UTC')

    context = {
        'timestamp': timestamp_display,
        'agent_status': args.agent_status,
        'model_info': args.model,
        'active_nodes': 'N/A',
        'relay_status': 'N/A',
        'recent_actions': 'No recent actions recorded.',
        'uptime': 'N/A',
        'memory_usage': 'N/A',
        'error_count': 'unknown',
        'relay_table': '| N/A | unknown | N/A |',
    }

    if args.collect:
        context['active_nodes'] = collect_ros2_nodes()
        context['uptime'] = collect_uptime()
        context['memory_usage'] = collect_memory_usage()

        docker_info = collect_docker_containers()
        if docker_info and 'N/A' not in docker_info:
            context['active_nodes'] += f' | Containers: {docker_info}'

        relays = collect_relay_status()
        if relays:
            online = sum(1 for r in relays if 'online' in r.lower())
            total = len(relays)
            context['relay_status'] = f'{online}/{total} online'
            rows = []
            for r in relays:
                # Extract relay name and status info
                parts = r.split()
                name = parts[0] if parts else 'unknown'
                status = 'online' if 'online' in r.lower() else 'offline'
                rows.append(f'| {name} | {status} | N/A |')
            if rows:
                context['relay_table'] = '\n'.join(rows)
        else:
            context['relay_status'] = 'N/A (nostr_relay_manager not available)'

        context['recent_actions'] = collect_recent_actions(
            args.recent_actions_file
        )
        context['error_count'] = collect_errors(args.error_file)

    # Render and write
    template = load_template(args.template)
    journal_md = render_journal(template, context)

    filename = f'{timestamp_str}_agent_journal.md'
    filepath = output_dir / filename
    filepath.write_text(journal_md, encoding='utf-8')

    print(json.dumps({
        'status': 'created',
        'file': str(filepath),
        'timestamp': timestamp_display,
        'next': (
            'To publish to Nostr: '
            'execute_skill_script nostr_memory scripts/cli_agent_memory.py '
            f'encode session-journal --input {filepath} '
            '--output /tmp/packed.json --compress gz'
        )
    }, indent=2))


if __name__ == '__main__':
    main()
