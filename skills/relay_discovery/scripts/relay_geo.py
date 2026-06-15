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
Relay Geo-IP Resolution – Resolves geographic location of relay hosts.

Uses the free ip-api.com service (no API key required, rate-limited to 45/min).
Results include country, city, ISP, lat/lng for mapping.
"""

import argparse
import json
import socket
from typing import Dict, Optional
import urllib.parse
from urllib.parse import urlparse
import urllib.request


def extract_hostname(relay_url: str) -> str:
    """Extract hostname from relay URL."""
    parsed = urlparse(relay_url)
    return parsed.hostname or relay_url


def resolve_geo(hostname: str, timeout: int = 5) -> Dict[str, Optional[str]]:
    """Resolve geo-IP for a hostname using ip-api.com."""
    result = {
        'hostname': hostname,
        'ip': None,
        'country': None,
        'country_code': None,
        'region': None,
        'city': None,
        'lat': None,
        'lng': None,
        'isp': None,
        'org': None,
        'error': None
    }

    # Resolve hostname to IP first
    try:
        ip = socket.gethostbyname(hostname)
        result['ip'] = ip
    except socket.gaierror as exc:
        result['error'] = f'DNS resolution failed: {exc}'
        return result

    # Query ip-api.com
    try:
        api_url = (
            f'http://ip-api.com/json/{ip}?fields='
            'status,country,countryCode,regionName,city,lat,lon,isp,org'
        )
        req = urllib.request.Request(api_url, headers={'User-Agent': 'nostr-relay-scanner/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('status') == 'success':
                result['country'] = data.get('country')
                result['country_code'] = data.get('countryCode')
                result['region'] = data.get('regionName')
                result['city'] = data.get('city')
                result['lat'] = data.get('lat')
                result['lng'] = data.get('lon')
                result['isp'] = data.get('isp')
                result['org'] = data.get('org')
            else:
                result['error'] = f"API error: {data.get('message', 'unknown')}"
    except urllib.error.URLError as exc:
        result['error'] = f'HTTP error: {exc}'
    except Exception as exc:
        result['error'] = str(exc)

    return result


def format_marker(geo: Dict) -> Dict:
    """Format geo data as a map marker for GUI display."""
    if geo.get('lat') and geo.get('lng'):
        return {
            'type': 'marker',
            'hostname': geo['hostname'],
            'lat': geo['lat'],
            'lng': geo['lng'],
            'label': geo.get('city') or geo.get('country') or geo['hostname'],
            'country': geo.get('country'),
            'isp': geo.get('isp')
        }
    return {'type': 'unresolved', 'hostname': geo['hostname']}


def main():
    parser = argparse.ArgumentParser(
        description='Relay Geo-IP – Resolve geographic location of relay hosts'
    )
    parser.add_argument(
        'relay', nargs='+',
        help='Relay URL(s) to resolve (e.g., wss://nos.lol)'
    )
    parser.add_argument(
        '--timeout', type=int, default=5,
        help='Timeout per query in seconds (default: 5)'
    )
    parser.add_argument(
        '--markers', action='store_true',
        help='Output in map-marker format'
    )
    args = parser.parse_args()

    results = []
    for relay in args.relay:
        hostname = extract_hostname(relay)
        print(f'[*] Resolving {hostname}...')
        geo = resolve_geo(hostname, timeout=args.timeout)
        geo['url'] = relay

        if args.markers:
            results.append(format_marker(geo))
        else:
            results.append(geo)

        if geo.get('error'):
            print(f"  ✗ {hostname}: {geo['error']}")
        else:
            location = f"{geo.get('city', '?')}, {geo.get('country', '?')}"
            print(f"  ✓ {hostname}: {location} ({geo.get('isp', '?')})")

    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
