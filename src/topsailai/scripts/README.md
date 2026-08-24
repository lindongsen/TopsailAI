---
maintainer: AI
author: DawsonLin
workspace: ..
ProjectFolder: ..
ProjectRootFolder: ../../..
ProjectCode: TOPSAILAI
programming_language: python
---

# Script Configuration Convention

Standalone scripts in this folder should keep their runtime configuration and environment-variable documentation beside the script.

## File Layout

For a script named `{script_name}.py`, use these companion files in the same folder:

- `{script_name}.env` — local runtime configuration.
- `{script_name}.md` — concise environment-variable and usage documentation.

Resolve companion paths from `__file__`, not from the current working directory. This keeps configuration discovery stable when a script is launched from another folder.

## Environment Loading

Load `{script_name}.env` immediately after imports and before importing modules with startup side effects or reading any configuration values.

Use `python-dotenv` with `override=False`. Configuration precedence is:

1. Existing process environment
2. `{script_name}.env`
3. Script built-in defaults

A missing file should be ignored. If an existing file cannot be loaded, log a warning and continue rather than terminating the script.

Minimal loader skeleton:

```python
import logging
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_ENV_FILE = SCRIPT_DIR / f"{Path(__file__).stem}.env"


def _load_script_env(env_file: Path = SCRIPT_ENV_FILE) -> None:
    """Load script-local configuration without overriding process values."""
    if not env_file.is_file():
        return
    try:
        load_dotenv(env_file, override=False)
    except Exception as error:
        logger.warning("failed to load script environment file %s: %s", env_file, error)


_load_script_env()
```

Keep built-in defaults safe so the script can start when the companion environment file is absent.

## Companion Documentation

Document every script-owned environment variable in `{script_name}.md`. Keep descriptions in English and concise, stating purpose, default behavior, and valid values. Set `maintainer: AI` in the document frontmatter and reference the script and its companion environment file.

The `.env` file may contain local operational values. Do not place credentials, tokens, private keys, or other secrets in shared documentation.

## Configuration Ownership

Classify each variable by inspecting its actual reader before documenting it:

- A variable read by the standalone script or its helper modules is script-owned. Document it in `{script_name}.md`, optionally provide it in `{script_name}.env`, and do not add it to `env_template` or `docs/Environment_Variables.md`.
- A variable read by TopsailAI core, a dispatcher, or another framework component is TopsailAI-owned. Keep it in `env_template` and `docs/Environment_Variables.md`, even when its value selects or invokes a script.

Search the repository for the variable name and identify the production-code reader; do not classify ownership from the variable prefix or intended use alone.

For example, `mem_graph_sync.py` owns the Mem Graph endpoint, request, retry, identity, port-check, and outbox settings documented in `mem_graph_sync.md`. `TOPSAILAI_MEMORY_SYNC_HOOKS` remains centrally managed because the TopsailAI memory-hook dispatcher reads it.

## Review Checklist

- Companion paths derive from `Path(__file__)`, never `cwd`.
- Loading occurs before configuration reads and startup-side-effect imports.
- `override=False` preserves process-environment precedence.
- Missing files are harmless and load failures only warn.
- Script-owned variables appear only in the companion documentation.
- TopsailAI-owned variables remain in the central template and reference.
- No hardcoded absolute paths or sensitive values appear in documentation.
