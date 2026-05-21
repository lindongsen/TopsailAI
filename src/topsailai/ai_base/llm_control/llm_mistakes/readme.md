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
