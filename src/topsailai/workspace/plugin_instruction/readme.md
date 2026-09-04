# Instructions With Plugin Mode

Supported keys:

- INSTRUCTIONS, dict, key is name, value is function.

## Key Format

`module_name.action`, example: `ctx.del_msg`, `ctx.del_msgs`, `env.get`

## Command-Line Testing

Use `topsailai_agent_call_instruction` to execute an instruction handler directly and print its real output without starting an interactive agent session.

For example, test `/agent.tokens` with:

```text
topsailai_agent_call_instruction -i '/agent.tokens'
```

Expected output shape:

```text
Model: DeepSeek-V4-Flash-Preview

Agent2LLM:
  Messages: 3
  Estimated tokens: 20,630

User2Agent: (ephemeral/unsaved session)
  Messages: 0
  Estimated tokens: 1

Context:
  Model maximum: 256,000
  Completion reserve: 30,000
  Input send limit: 226,000
  Agent2LLM usage: 9.1%
  Watermark: NORMAL
```

The values depend on the active model and messages. The report must be printed exactly once; duplicate `/agent.tokens` registration was fixed in commit `3ee34ad`.
