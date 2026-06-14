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
Task Scheduler Daemon - Entry point for the background process.

Starts the AgentTaskScheduler, monitors the PID file, and handles POSIX
signals for graceful shutdown / reload.

Usage:
  ros2 run bob_nostr task_scheduler        # start daemon
  ros2 run bob_nostr task_scheduler --status  # print status from running daemon

Signals:
  SIGTERM / SIGINT  - graceful shutdown
  SIGHUP            - reload tasks.json
  SIGUSR1           - print status to stderr
"""

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys

from bob_nostr.task_scheduler.config import settings
from bob_nostr.task_scheduler.scheduler import AgentTaskScheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_logging() -> None:
    log_dir = os.path.dirname(settings.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(settings.log_file),
            logging.StreamHandler(sys.stderr),
        ],
    )


logger = logging.getLogger('task_scheduler.daemon')


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def _write_pid() -> None:
    pid_dir = os.path.dirname(settings.pid_file)
    if pid_dir:
        os.makedirs(pid_dir, exist_ok=True)
    with open(settings.pid_file, 'w') as fh:
        fh.write(str(os.getpid()))
    logger.info('PID %d written to %s', os.getpid(), settings.pid_file)


def _remove_pid() -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(settings.pid_file)


def _print_status_from_pid() -> None:
    """Print the scheduler status from PID file when ``--status`` is used."""
    if not os.path.isfile(settings.pid_file):
        sys.exit(1)

    with open(settings.pid_file) as fh:
        fh.read().strip()


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


class Daemon:
    """Manages the scheduler's lifetime and signal handling."""

    def __init__(self) -> None:
        self._scheduler = AgentTaskScheduler()
        self._shutdown_event = asyncio.Event()

    async def run(self) -> None:
        _write_pid()
        logger.info('Daemon starting (PID %d).', os.getpid())

        await self._scheduler.start()
        logger.info('Daemon ready - waiting for signals.')

        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self._scheduler.stop()
            _remove_pid()
            logger.info('Daemon stopped.')

    def shutdown(self) -> None:
        logger.info('Shutdown signal received.')
        self._shutdown_event.set()

    def reload(self) -> None:
        """SIGHUP handler - re-read tasks.json."""
        logger.info('SIGHUP received - reloading tasks...')
        asyncio.create_task(self._scheduler._storage.reload())  # noqa

    def print_status(self) -> None:
        """SIGUSR1 handler - write runtime status to stderr."""
        self._scheduler.get_status()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog='task_scheduler',
        description='Task Scheduler Daemon - ROS 2 executable',
    )
    parser.add_argument(
        '--status', action='store_true',
        help='Print scheduler status and exit',
    )
    # Use parse_known_args so that ROS 2 arguments (--ros-args, -r __node:=…)
    # are silently ignored instead of causing a fatal error.
    args, _ = parser.parse_known_args()

    if args.status:
        _print_status_from_pid()
        return

    _setup_logging()
    daemon = Daemon()

    # Register signal handlers
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, daemon.shutdown)
        except NotImplementedError:
            # Fallback for Windows (not expected here)
            signal.signal(sig, lambda s, f: daemon.shutdown())

    with contextlib.suppress(Exception):
        loop.add_signal_handler(signal.SIGHUP, daemon.reload)

    with contextlib.suppress(Exception):
        loop.add_signal_handler(signal.SIGUSR1, daemon.print_status)

    try:
        loop.run_until_complete(daemon.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == '__main__':
    main()
