# LLM make mistakes

## Variables & Functions

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
