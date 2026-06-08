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
Coder Toolset.

Provides absolute filesystem and shell power.
Allows the AI to act as a true software engineer on the host system.
"""

import argparse
import os
import shlex
import subprocess
import sys


def read_file(path: str, start_line: int = 1, end_line: int = 800) -> str:
    """
    Read the content of a file (1-indexed, inclusive).

    :param path: Path to the file.
    :param start_line: First line to read.
    :param end_line: Last line to read.
    :return: File content or error message.
    """
    if not os.path.exists(path):
        return f'Error: File "{path}" not found.'

    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Adjustment for 1-indexing
        requested_lines = lines[start_line - 1: end_line]
        if not requested_lines:
            return f'Empty or out of bounds (File has {len(lines)} lines).'

        content = ''.join(requested_lines)
        return (
            f'--- {path} (Lines {start_line}-'
            f'{min(end_line, len(lines))}) ---\n{content}'
        )
    except Exception as e:
        return f'Error reading file: {str(e)}'


def write_file(path: str, content: str, overwrite: bool = True) -> str:
    """
    Write content to a file.

    Creates directories if they don't exist.
    Use this to save your code creations or modify settings.

    :param path: Destination path.
    :param content: Text to write.
    :param overwrite: Whether to overwrite existing files.
    :return: Success or error message.
    """
    if os.path.exists(path) and not overwrite:
        return f'Error: File "{path}" already exists and overwrite is False.'

    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f'Successfully saved {len(content)} characters to {path}.'
    except Exception as e:
        return f'Error writing file: {str(e)}'


def list_dir(path: str = '.') -> str:
    """
    List files and directories at the specified path.

    Defaults to the current working directory.

    :param path: Directory to list.
    :return: Formatted list of contents.
    """
    if not os.path.exists(path):
        return f'Error: Path "{path}" not found.'

    try:
        items = os.listdir(path)
        formatted_items = []
        for i in items:
            is_dir = os.path.isdir(os.path.join(path, i))
            prefix = '[DIR] ' if is_dir else '      '
            formatted_items.append(f'{prefix}{i}')
        formatted_items.sort()
        header = f'Contents of {os.path.abspath(path)}:\n'
        return header + '\n'.join(formatted_items)
    except Exception as e:
        return f'Error listing directory: {str(e)}'


def run_command(command: str, timeout: float = 120.0) -> str:
    """
    Execute a shell command on the host (Linux).

    Allows running compilers (e.g. g++), build tools (colcon), or git.

    :param command: Shell command to run.
    :param timeout: Maximum execution time.
    :return: Command output or error.
    """
    try:
        # Standard safety: No interactive shells, use shlex
        args = shlex.split(command)
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )

        output = result.stdout.strip()
        if result.returncode != 0:
            output += f'\n[Error {result.returncode}]: {result.stderr.strip()}'

        if not output:
            return '[Success: Command returned no output]'
        return output
    except Exception as e:
        return f'Command failed: {str(e)}'


def search_text(directory: str, query: str, pattern: str = '*') -> str:
    r"""
    Search for a string recursively in a directory using grep-like logic.

    :param directory: Where to start searching.
    :param query: The text to find.
    :param pattern: File glob pattern (e.g. '*.py').
    :return: Search results.
    """
    try:
        # We use the built-in 'grep' command for high performance
        cmd = ['grep', '-rn', '--include', pattern, query, directory]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30.0,
            check=False
        )

        output = result.stdout.strip()
        if not output:
            return 'No matches found.'
        return output[:5000]  # Cap output for LLM context
    except Exception as e:
        return f'Search failed: {str(e)}'


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description='Coder CLI')
    parser.add_argument('--func', required=True, help='Function to call')
    parser.add_argument('--path', help='File/Dir path')
    parser.add_argument('--content', help='Content to write')
    parser.add_argument('--command', help='Shell command to run')
    parser.add_argument('--query', help='Search query')
    parser.add_argument('--pattern', default='*', help='File pattern for search')
    parser.add_argument('--start', type=int, default=1, help='Start line')
    parser.add_argument('--end', type=int, default=800, help='End line')
    parser.add_argument(
        '--overwrite', type=str, default='True', help='Overwrite flag (True/False)'
    )

    args = parser.parse_args()

    try:
        if args.func == 'read_file':
            print(read_file(args.path, args.start, args.end))
        elif args.func == 'write_file':
            ov = args.overwrite.lower() == 'true'
            print(write_file(args.path, args.content, ov))
        elif args.func == 'list_dir':
            print(list_dir(args.path or '.'))
        elif args.func == 'run_command':
            print(run_command(args.command))
        elif args.func == 'search_text':
            print(search_text(args.path or '.', args.query, args.pattern))
        else:
            print(f'Error: Unknown function "{args.func}"')
            sys.exit(1)
    except Exception as e:
        print(f'CLI Error: {str(e)}')
        sys.exit(1)


if __name__ == '__main__':
    main()
