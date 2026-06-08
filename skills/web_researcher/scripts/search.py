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

"""Search the web using SearXNG via the API Gateway."""

import json
import os
import sys

import requests


def search_web(query: str, num_results: int = 3) -> str:
    """
    Search the web using SearXNG.

    :param query: The search query string.
    :param num_results: Number of results to return.
    :return: A JSON string containing results or error.
    """
    # Use the centralized gateway URL if available, fallback to internal nginx
    searxng_url = os.environ.get(
        'MASTER_SEARXNG_URL',
        'http://api-gateway:8080/search'
    ).strip()

    # Automatically prepend protocol if missing
    if not (searxng_url.startswith('http://') or searxng_url.startswith('https://')):
        searxng_url = 'http://' + searxng_url

    # Ensure URL ends with /search
    if not (searxng_url.endswith('/search') or searxng_url.endswith('/search/')):
        searxng_url = searxng_url.rstrip('/') + '/search'

    params = {
        'q': query,
        'format': 'json',
        'language': os.environ.get('MASTER_SEARXNG_LANGUAGE', 'en-US')
    }

    try:
        response = requests.get(searxng_url, params=params, timeout=15.0)
        response.raise_for_status()
        data = response.json()

        results = []
        for res in data.get('results', [])[:num_results]:
            results.append({
                'title': res.get('title', ''),
                'content': res.get('content', ''),
                'url': res.get('url', ''),
                'score': res.get('score', 0.0)
            })

        if not results:
            return json.dumps({'status': 'no_results', 'message': 'No relevant matches found.'})

        return json.dumps(
            {'status': 'success', 'query': query, 'results': results},
            ensure_ascii=False,
            indent=2
        )

    except requests.exceptions.RequestException as e:
        return json.dumps({'status': 'error', 'type': 'network_error', 'message': str(e)})
    except Exception as e:
        return json.dumps({'status': 'error', 'type': 'system_error', 'message': str(e)})


def main():
    """CLI entrypoint for the web search skill."""
    import argparse

    parser = argparse.ArgumentParser(description='Web Research Tool')
    parser.add_argument('--query', '-q', required=True, help='Search query')
    parser.add_argument('--num_results', '-n', type=int, default=3, help='Max results')

    # Handle cases where args might be passed without flags for compatibility
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        query = ' '.join(sys.argv[1:])
        print(search_web(query))
        return

    args = parser.parse_args()
    print(search_web(args.query, args.num_results))


if __name__ == '__main__':
    main()
