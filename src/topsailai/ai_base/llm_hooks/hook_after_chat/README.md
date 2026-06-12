# LLM make mistakes by Model

LLM makes mistakes and outputs some incorrect formats. This folder method can solve these errors.

Each file have a function `def hook_execute(content:any) -> list[dict] | str:` to return right content.

Save each model with different files, Example:
```
- kimi.py
- minimax.py
- kimi1.py -> Splitting files if there are too many lines of code
- kimi2.py
```

## Check Method

```python
from topsailai.ai_base.llm_control.message import format_response
new_response = format_response(message)
# check the new_response
```
