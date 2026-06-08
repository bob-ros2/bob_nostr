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

"""Combined Repository and Skill Guideline Tests for Bob Nostr."""

import configparser
import os
import stat

import pytest

import yaml

# Paths
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SOURCE_DIR = os.path.join(ROOT, 'bob_nostr')
SKILLS_ROOT = os.path.join(ROOT, 'skills')
# Path for learned/autonomous skills (usually host-mapped volume)
PERSISTENT_SKILLS_ROOT = os.environ.get(
    'PERSISTENT_SKILLS_PATH',
    '/home/ros/agent/skills'
)
SETUP_CFG = os.path.join(SOURCE_DIR, 'setup.cfg')

# Constants
ALLOWED_IN_SKILLS_ROOT = {'.gitkeep', 'TEMPLATE_SPEC.md'}


# --- Helper Functions ---

def get_skill_dirs():
    """Return list of all skill directories from both core and persistent roots."""
    roots = [SKILLS_ROOT]
    if os.path.exists(PERSISTENT_SKILLS_ROOT):
        roots.append(PERSISTENT_SKILLS_ROOT)

    skill_entries = []
    for root in roots:
        if not os.path.exists(root):
            continue
        for d in os.listdir(root):
            full_path = os.path.join(root, d)
            if os.path.isdir(full_path) and not d.startswith('.'):
                skill_entries.append((root, d, full_path))
    return skill_entries


def get_all_scripts():
    """Return list of all script files under skills/<skill>/scripts/."""
    scripts = []
    for root, skill, skill_dir in get_skill_dirs():
        scripts_dir = os.path.join(skill_dir, 'scripts')
        if not os.path.isdir(scripts_dir):
            continue
        for fname in os.listdir(scripts_dir):
            fpath = os.path.join(scripts_dir, fname)
            # Skip module files and hidden/meta files
            if (fname == '__init__.py'
                    or fname.startswith('.')
                    or fname == '__pycache__'):
                continue
            if os.path.isfile(fpath):
                scripts.append((skill, fname, fpath))
    return scripts


# --- Repository Structure Tests ---

def test_node_file_naming():
    """Rule: All .py files in bob_nostr/ (except __init__.py) must end with _node.py."""
    python_files = [
        f for f in os.listdir(SOURCE_DIR)
        if f.endswith('.py') and f != '__init__.py'
    ]
    invalid_files = [f for f in python_files if not f.endswith('_node.py')]
    assert not invalid_files, (
        f'Naming Error: Files in bob_nostr/ must end with "_node.py".\n'
        f'Invalid: {invalid_files}'
    )


def test_setup_cfg_consistency():
    """Rule: setup.cfg entry points must match files and follow naming policy."""
    expected_nodes = {
        f[:-3] for f in os.listdir(SOURCE_DIR) if f.endswith('_node.py')
    }
    config = configparser.ConfigParser()
    config.read(SETUP_CFG)

    has_cs = ('options.entry_points' in config and
              'console_scripts' in config['options.entry_points'])
    if not has_cs:
        pytest.fail('setup.cfg is missing console_scripts definition.')

    scripts_raw = config['options.entry_points']['console_scripts'].strip().split('\n')
    entry_points = {}
    for line in scripts_raw:
        if '=' not in line:
            continue
        name, target = line.split('=')
        entry_points[name.strip()] = target.strip()

    # Check: Short name policy
    long_execs = [name for name in entry_points.keys() if name.endswith('_node')]
    assert not long_execs, f'Executables must not have "_node" suffix: {long_execs}'

    # Check: All nodes registered
    registered = {
        target.split(':')[0].split('.')[-1] for target in entry_points.values()
    }
    missing = expected_nodes - registered
    assert not missing, f'Missing setup.cfg registration for: {missing}'

    # Check: Valid targets
    for name, target in entry_points.items():
        module_name = target.split(':')[0].split('.')[-1]
        assert module_name.endswith('_node'), f'"{name}" points to non-node module.'
        file_path = os.path.join(SOURCE_DIR, f'{module_name}.py')
        assert os.path.exists(file_path), f'"{name}" points to missing file: {file_path}'


# --- Skills Guideline Tests ---

def test_no_stray_files_in_skills_root():
    """No files allowed directly in skills/ except .gitkeep and TEMPLATE_SPEC.md."""
    if not os.path.exists(SKILLS_ROOT):
        pytest.skip('Skills directory missing.')
    violations = [
        e for e in os.listdir(SKILLS_ROOT)
        if os.path.isfile(os.path.join(SKILLS_ROOT, e))
        and e not in ALLOWED_IN_SKILLS_ROOT
    ]
    assert not violations, f'Stray files in skills/: {violations}'


def test_no_stray_files_in_skill_dirs():
    """No files allowed in skills/<skill>/ except SKILL.md, docs and .gitignore."""
    violations = []
    for root, skill, skill_dir in get_skill_dirs():
        for entry in os.listdir(skill_dir):
            full_path = os.path.join(skill_dir, entry)
            # We only check files at the skill root level
            if not os.path.isfile(full_path):
                continue
            if entry == 'SKILL.md' or entry.endswith('.md') or entry == '.gitignore':
                continue
            violations.append(f'{os.path.basename(root)}/{skill}/{entry}')
    assert not violations, f'Stray files in skill dirs: {violations}'


def test_skill_dirs_have_skill_md():
    """Every skill directory must contain a SKILL.md file."""
    missing = [
        f'{os.path.basename(root)}/{s}/SKILL.md' for root, s, sp in get_skill_dirs()
        if not os.path.isfile(os.path.join(sp, 'SKILL.md'))
    ]
    assert not missing, f'Missing SKILL.md in: {missing}'


def test_skill_md_frontmatter():
    """Verify that every SKILL.md has a valid YAML frontmatter conforming to TEMPLATE_SPEC.md."""
    for root, skill, skill_dir in get_skill_dirs():
        skill_md_path = os.path.join(skill_dir, 'SKILL.md')
        if not os.path.isfile(skill_md_path):
            continue

        with open(skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        parts = content.split('---')
        assert len(parts) >= 3, (
            f"Missing YAML frontmatter delimiters '---' in {skill}/SKILL.md."
        )

        frontmatter_str = parts[1]
        try:
            metadata = yaml.safe_load(frontmatter_str)
        except Exception as e:
            pytest.fail(f'Invalid YAML in {skill}/SKILL.md frontmatter: {e}')

        assert isinstance(metadata, dict), (
            f'YAML frontmatter in {skill}/SKILL.md is not a dictionary.'
        )

        # Verify required keys
        required_keys = ['name', 'description', 'version', 'category']
        for key in required_keys:
            assert key in metadata, (
                f"Missing required key '{key}' in {skill}/SKILL.md frontmatter."
            )
            assert metadata[key], (
                f"Value for '{key}' in {skill}/SKILL.md frontmatter cannot be empty."
            )

        # Verify name matches directory name
        assert metadata['name'] == skill, (
            f"Skill name '{metadata['name']}' in frontmatter does not match "
            f"directory name '{skill}'."
        )


def test_scripts_are_executable():
    """All script files under skills/<skill>/scripts/ must be executable."""
    violations = [
        f'{s}/scripts/{fn}' for s, fn, fp in get_all_scripts()
        if not (os.stat(fp).st_mode & stat.S_IXUSR)
    ]
    assert not violations, f'Scripts missing +x: {violations}'


def test_scripts_have_shebang():
    """All script files under skills/<skill>/scripts/ must start with a shebang (#!)."""
    violations = []
    for s, fn, fp in get_all_scripts():
        try:
            with open(fp, 'rb') as f:
                if f.read(2) != b'#!':
                    violations.append(f'{s}/scripts/{fn}')
        except Exception:
            violations.append(f'{s}/scripts/{fn} (read error)')
    assert not violations, f'Scripts missing shebang: {violations}'
