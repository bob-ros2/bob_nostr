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

"""Memory Type Registry - loads spec and resolves types."""

import os

import yaml

# SPEC_PATH is resolved relative to this file's location:
#   scripts/registry.py -> ../resources/memory_spec.yaml
_SPEC_DIR = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.environ.get(
    'AGENT_MEMORY_SPEC',
    os.path.join(_SPEC_DIR, '..', 'resources', 'memory_spec.yaml')
)

_SPEC = None


def load_spec(path: str = SPEC_PATH) -> dict:
    global _SPEC
    if _SPEC is not None:
        return _SPEC
    with open(path) as f:
        spec = yaml.safe_load(f)
    spec['_by_name'] = {}
    for mt in spec.get('memory_types', []):
        spec['_by_name'][mt['name']] = mt
    _SPEC = spec
    return spec


def get_memory_type(name: str) -> dict:
    spec = load_spec()
    mt = spec.get('_by_name', {}).get(name)
    if not mt:
        raise ValueError(f'Unknown memory type: {name}. Available: {list_types()}')
    return mt


def list_types() -> list:
    spec = load_spec()
    return list(spec.get('_by_name', {}).keys())


def get_serialization_config() -> dict:
    spec = load_spec()
    return spec.get('serialization', {})


def get_obfuscation_config() -> dict:
    spec = load_spec()
    return spec.get('obfuscation', {})
