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
