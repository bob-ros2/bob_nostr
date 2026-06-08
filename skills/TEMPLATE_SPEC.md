# Anthropic Agent Skills Specification (TEMPLATE_SPEC)

This document defines the standardized structure for all modular skills. All new skills MUST comply with this specification to ensure interoperability and self-documentation.

## 1. Directory Structure
Each skill resides in its own folder under the central skill directory:
```text
skills/[skill_name]/
├── SKILL.md            # The primary documentation and entry point (MANDATORY)
├── scripts/            # Executable logic (e.g., .py, .sh, .js)
├── resources/          # Static assets, configs, templates, or JSON data
└── examples/           # Example usage scripts or demonstration data
```

## 2. SKILL.md Format
The `SKILL.md` file MUST start with a YAML frontmatter block for machine readability.

### 2.1 Metadata (YAML Frontmatter)
```yaml
---
name: [skill_name]
description: "[One-sentence summary of what the skill does]"
version: "1.0.0"
category: "[e.g. vision, system, research]"
---
```

### 2.2 Markdown Sections
- `# [Skill Title]`: A clear, human-readable name.
- `## Goal`: A concise statement of what the skill is intended to achieve.
- `## Description`: A detailed explanation of the functionality and mechanisms.
- `## Usage`: Practical code snippets or commands showing how to call the skill.
  - *Example:* `execute_skill_script("vision_llm", "scripts/vision_query.py", "--prompt '...' --image_path '...'")`
- `## Parameters`: A table or list of all command-line arguments or environment variables.
- `## Requirements`: List any dependencies, hardware, or other skills required (e.g., "Gemma 3 Vision Container running on Port 8022").
- `## Technical Details`: Explain the internal logic, ROS topics used, or API interactions.
- `## Best Practices`
  - **Environment Variables**: Use `os.environ.get()` for all external connections (API-URLs, Paths).
  - **Central Configuration**: Keep these variables in the root `.env` file and update `.env.template`.
  - **Pragmatic Approach**: Use env vars for portability. Standard hardcoded defaults are acceptable if the skill is fixed within the container environment.

## 3. Implementation Guidelines
- **Self-Contained**: A skill should bundle all its logic in the `scripts/` folder.
- **Shebangs**: All scripts must have a proper shebang (e.g., `#!/usr/bin/env python3`) and be made executable.
- **Error Handling**: Scripts should provide clear error messages and exit codes (0 for success, non-zero for failure).
- **Tool Logic**: When creating a skill, write the `SKILL.md` first to define the contract, then implement the `scripts/`.

## 4. Execution Pattern
Skills are primarily executed through the `execute_skill_script(skill_name, script_path, args)` tool provided by `bob_llm`.
- `skill_name`: Folder name in the skills directory.
- `script_path`: Relative path starting from the skill root (e.g., `scripts/run.py`).
- `args`: Command-line arguments string.
