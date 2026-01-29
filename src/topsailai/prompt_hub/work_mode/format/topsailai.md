# Output format requirements

The `step_name` must have a prefix of `topsailai.`

`step_name` and `raw_text` MUST be different Lines.

Format:
```
topsailai.{step_name}
{raw_text}
```

Example:
```
topsailai.thought
Hello World
```

Example final_answer:
```
topsailai.final_answer
HelloWorld
```
