# LLM make mistakes

LLM makes mistakes and outputs some incorrect formats. This folder method can solve these errors.
Each file will have a variable record function dictionary `MISTAKES`, and the format of the function is `def func_name(message:str|list, **kwargs) -> str|dict|list:`, where message is the return content of LLM.
When a message is a `list`, the elements inside are usually `dict`, and the format needs to be strictly judged.

The expected correct return content can refer to the definition here: src/topsailai/ai_base/data/message.py

## Variables & Functions

message: str or list_dict,

- MISTAKES: assert error / format message, `def func(message, **kwargs) -> str|dict|list:`, if have any changes, return new_message, else return None; if assert error, raise sth.

Example:
```python
def check_mistake1(message, **kwargs):

def check_mistake2(message, **kwargs):

def fix_mistake1(message, **kwargs):

def fix_mistake2(message, **kwargs):

def ...

MISTAKES = dict(
    check_mistake1=check_mistake1,
    ...
)
```

## Check Method

```python
from topsailai.ai_base.llm_control.message import format_response
new_response = format_response(message)
# check the new_response
```

```shell
root@ai-dev:/TopsailAI/src/topsailai# topsailai_format_response tests/mistakes/response/parsing-action-vs-final-answer.txt
```

## Methodology: Fixing Conflicting Steps and Early-Return Reference Capture

This section summarizes the methodology used to fix a response-parsing bug where the LLM emitted both an `action` step and a `final_answer` step in the same response, or produced `final_answer` prematurely.

### Diagnosing Early-Return Reference-Capture Bugs

`format_response()` in `src/topsailai/ai_base/llm_control/message.py` contains several early `return response` statements inside the `try` block. When `response` is a list, these statements return a reference to the same list object that the local variable `response` points to.

The `finally` block then computes a corrected `new_response` and attempts to publish it with `response = new_response`. However, because the caller has already captured the original list reference, rebinding the local variable does not affect the returned object. The caller receives the uncorrected list.

Symptoms of this class of bug:
- A mistake fixer reports success during unit tests, but the corrected content is not visible to the agent.
- The issue only appears for response formats that take an early `return` path (for example, the `topsailai.` format).
- Formats that fall through to the end of the function work correctly because the local variable is still the live return value.

### Why In-Place List Mutation Is Sometimes Required in `finally`

When the early-return path is taken, the only way to affect the value seen by the caller is to mutate the list object in place. The safe pattern is:

```python
if isinstance(response, list):
    response.clear()
    if isinstance(new_response, list):
        response.extend(new_response)
    else:
        response.append(new_response)
else:
    response = new_response
```

This pattern preserves the original assignment behavior for non-list responses while ensuring that list responses are corrected in place. The non-list branch remains important because `response` may be a string or other type in some code paths.

### Design Principle for Conflicting Step Types

When the LLM emits conflicting step types, such as both `action` and `final_answer`, the preferred resolution is to convert the premature or conflicting step into a `thought` step rather than silently dropping it.

Rationale:
- Dropping `final_answer` loses information that the model considered relevant.
- Converting it to `thought` preserves the content, keeps the response structurally valid, and allows the agent to continue with the planned action.
- This approach generalizes to other conflicting step pairs: downgrade the step that would prematurely terminate execution into a non-terminating step type.

The fixer `action_with_final_answer.py` applies this principle by scanning the parsed response list. If it finds an `action` step together with a `final` or `final_answer` step, the `final`/`final_answer` step is rewritten as a `thought` step.

### Registering a New Mistake Fixer

Mistake fixers are discovered automatically. `llm_mistakes/base/init.py` scans the `llm_mistakes` package for modules that expose a `MISTAKES` dictionary and merges them into the global registry.

To add a new fixer:

1. Create a new Python file in `src/topsailai/ai_base/llm_control/llm_mistakes/`.
2. Define one or more functions with the signature `def func_name(message: str | list, **kwargs) -> str | dict | list | None`.
3. Expose them in a module-level `MISTAKES` dictionary.
4. Import or reference the module so that it is loaded when `llm_mistakes/base/init.py` builds the registry.

Example structure:

```python
def fix_action_with_final_answer(message, **kwargs):
    # Detect and rewrite conflicting steps.
    ...

MISTAKES = dict(
    fix_action_with_final_answer=fix_action_with_final_answer,
)
```

After adding the fixer, verify it through `format_response()` end-to-end, not only by calling the fixer directly. Unit tests should cover both the fixer in isolation and the full `format_response()` path for the affected response format.



## Methodology: Removing Consecutive Duplicate Action Steps

When the LLM emits the same `action` step multiple times in a row, the agent may execute the same tool call repeatedly within a single turn. The fixer `duplicate_consecutive_steps.py` detects and removes consecutive duplicate `action` steps from an already-parsed `list[dict]` response.

### Scope and Matching Rules

- Only items with `step_name == "action"` are considered.
- Duplicates are determined by comparing a normalized signature of `tool_call` and `tool_args`:
  - `tool_call` must be a non-empty string.
  - `tool_args` is JSON-normalized with sorted keys and no insignificant whitespace.
  - This makes the comparison robust against formatting differences in raw LLM output.
- A single left-to-right pass removes the earlier item of any matching consecutive pair.

Example:

```python
[
    {"step_name": "thought", "raw_text": "Let me read the file."},
    {"step_name": "action", "tool_call": "file_tool-read_file", "tool_args": {"files": ["/tmp/1.txt"]}},
    {"step_name": "action", "tool_call": "file_tool-read_file", "tool_args": {"files": ["/tmp/1.txt"]}},
]
```

becomes:

```python
[
    {"step_name": "thought", "raw_text": "Let me read the file."},
    {"step_name": "action", "tool_call": "file_tool-read_file", "tool_args": {"files": ["/tmp/1.txt"]}},
]
```

### Failure Safety

The fixer is wrapped so that any unexpected exception is caught and logged. If the deduplication logic fails, the original response is returned unchanged and `format_response()` continues normally. This prevents a bug in the fixer from breaking the upstream parsing flow.

### Input-Format Limitation

The `topsailai.` text format is parsed into an `OrderedDict` keyed by `step_name` in `format_tool.parse_topsailai_format()`, so duplicate `action` keys are already collapsed by the parser. The deduplication fixer therefore applies primarily to:

- JSON string responses that parse to a `list[dict]`.
- Direct `list[dict]` inputs passed to `format_response()`.

### Registration

Like other fixers, `duplicate_consecutive_steps.py` exposes its handler in a module-level `MISTAKES` dictionary and is auto-discovered by `llm_mistakes/base/init.py`. It runs during `format_response_finally()` so that earlier fixers (e.g., `missing_tool_args.py`, `action_with_final_answer.py`) have already normalized action content before duplication detection runs.

## Diagnosing `parsing response` Failures from `topsailai.log.ec`

Search `topsailai.log.ec` for `parsing response` and ignore entries whose tail contains `(unit-test:)`. Inspect the raw LLM response enclosed between `>>>` and `<<<`.

- If the parsing error is immediately followed by an `LLM Mistake` log, the system recognized a repairable pattern and will attempt recovery.
- If no `LLM Mistake` log follows, no repair method matched and the response will fail to parse.

Use this distinction to decide whether to add a new mistake fixer or improve an existing one.

## Model-Specific Hook Scripts (Subprocess Contract)

Beyond the in-process `MISTAKES` fixers, a model may ship a folder of case
scripts that run as independent subprocesses. This makes the fix logic
extensible without modifying core code or restarting the agent.

### Folder Layout

Each model folder lives under `llm_mistakes/`, e.g.
`deepseek_hook_scripts/`. Eligible scripts are `*.py` files whose name does
not start with `_` and does not end with a temp/backup suffix (`.tmp`,
`.new`, `.bak`, `~`, `.swp`, `.pyc`). Files are executed in lexicographic
filename order, so use a `pNNN_<case>.py` prefix to control priority.

### Discovery

The folder is rescanned on every call (no import cache). Scripts added,
removed, or changed between responses take effect on the next response
without a restart.

### Execution

Each script is spawned as an independent subprocess via `sys.executable`
(no shell, no executable-bit requirement). The working directory is the
script folder. A timeout (default 5s) kills the whole process group; stdout
is capped (default 1MB).

### Environment Contract

| Variable | Meaning |
|---|---|
| `TOPSAILAI_LLM_MISTAKE_MODEL` | Resolved model name (empty if unknown). |
| `TOPSAILAI_LLM_MISTAKE_RESPONSE` | Raw response when small enough (default <= 64KB). |
| `TOPSAILAI_LLM_MISTAKE_RESPONSE_FILE` | Temp file path for larger responses (default <= 10MB). |
| `TOPSAILAI_LLM_MISTAKE_SCRIPT` | Absolute path of the executed script. |
| `TOPSAILAI_LLM_MISTAKE_SCRIPT_DIR` | Absolute path of the script folder. |

Responses above the hard cap (default 10MB) skip all scripts and fall back
to the model's parser. The child environment is a minimal curated set
(PATH, PYTHONPATH, LANG, LC_ALL, HOME plus the `TOPSAILAI_LLM_MISTAKE_*`
variables) so parent secrets are not leaked.

### Output Contract

- **Success**: valid JSON on stdout that passes the agent step schema
  (`list[dict]`, each with a non-empty `step_name`; `action` steps require a
  non-empty `tool_call` and a `dict` `tool_args`). The first success
  short-circuits.
- **Not handled**: empty/whitespace stdout. Continue to the next script.
- **Failure**: invalid JSON, oversized output, or timeout. Log the reason
  and continue to the next script.
- **stderr**: captured for diagnostics only; never a success/failure signal.

### Wiring

A model handler (e.g. `deepseek.py`) resolves the script folder via
`importlib.resources.files()` and calls `run_hook_scripts(script_dir,
model_name, message)`. If it returns a validated result, the handler returns
it; otherwise the handler falls back to its in-process parser.
