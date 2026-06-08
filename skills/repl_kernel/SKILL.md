---
name: repl_kernel
description: Provides a persistent Python REPL environment for iterative system engineering and stateful calculations.
version: "1.0.0"
category: "system"
author: Antigravity
---

# REPL Kernel Skill
This skill grants Agent access to a persistent Python REPL environment and a physical "Scratchpad" directory.

## Paradigms
1. **Interactive REPL (`repl_execute`)**:
   - Best for stateful engineering, quick calculations, and iterative logic.
   - **Persistence**: Variables and imports survive between calls.
   - **Timeout**: 15s limit. Do NOT use for long delays/sleeps.
2. **Scratchpad Execution (`execute_skill_script`)**:
   - Best for long-running tasks, background scripts, or multi-threaded operations.
   - Use `write_skill_file` to create a script in this directory, then run it.
   - Scripts are executed as independent subprocesses.

## Tools
- `repl_execute(code)`: Run Python logic with persistent state (15s timeout).
- `repl_reset()`: Clear the persistent global namespace.
- `repl_list_history()`: Return a summary of current variables and imports.

## Usage
To use this skill, call **`execute_skill_script()`** with the following parameters:
- **`skill_name`**: `"repl_kernel"`
- **`script_path`**: `"scripts/repl_tool.py"`
- **`args`**: `"--func <FUNCTION_NAME> --code <code>"`

### Example call (Execute Code)
```json
execute_skill_script({
  "skill_name": "repl_kernel",
  "script_path": "scripts/repl_tool.py",
  "args": "--func repl_execute --code \"print('Hello from Agent')\""
})
```
