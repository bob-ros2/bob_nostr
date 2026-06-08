---
name: core_coder
description: Professional filesystem and shell power for software engineering tasks.
version: "1.0.0"
category: "system"
---

# Core Coder Skill

This skill grants the power of a software engineer on her host system. She can manage files, execute system commands, and search through codebases.

## Functions

### read_file
Read the content of a file with line-range support.
- **Arguments**: `path` (str), `start_line` (int, default=1), `end_line` (int, default=800)
- **Returns**: File content snippet.

### write_file
Write or modify file content.
- **Arguments**: `path` (str), `content` (str), `overwrite` (bool, default=True)
- **Returns**: Success message.

### list_dir
List directory contents.
- **Arguments**: `path` (str, default='.')
- **Returns**: Formatted list of files and directories.

### run_command
Execute a shell command on the host.
- **Arguments**: `command` (str), `timeout` (float, default=120.0)
- **Returns**: stdout/stderr output.

### search_text
Recursive string search using grep logic.
- **Arguments**: `directory` (str), `query` (str), `pattern` (str, default='*')
- **Returns**: Found matches with line numbers.

## Usage
To use this skill, call **`execute_skill_script()`** with the following parameters:
- **`skill_name`**: `"core_coder"`
- **`script_path`**: `"scripts/coder_tool.py"`
- **`args`**: `"--func <FUNCTION_NAME> --path <PATH> ..."`

### Example call (Reading a file)
```json
execute_skill_script({
  "skill_name": "core_coder",
  "script_path": "scripts/coder_tool.py",
  "args": "--func read_file --path '/ros2_ws/src/bob_nostr/package.xml'"
})
```

Essential for self-evolution, debugging, and system orchestration.
