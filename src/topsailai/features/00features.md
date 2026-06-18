# TopsailAI Agent

## Support to add messages into session

会话有两层：
1. User2Agent, User chatting to agent，user面向抽象层ai-agent,不直接面向LLM。-> 当任务正在运行时，支持在这一层增加消息，即 agent2llm 执行完毕后的下一个任务就能读到新增的消息。
2. Agent2LLM, Agent chatting to LLM，ai-agent直接面向LLM去执行明确的任务。

DONE: TopsailAI/cli/topsailai_session_add_message.py

TIPS: 这种方法也可以 增加message到session `TopsailAI/src/topsailai/context/ctx_manager.py:add_session_message`

---

## Context Messages

以agent维度设置一个上下文消息列表`context_user_messages`，将此列表按照一定的规则进行组合作为1条message。

组合规则样例:
```
---
ctx_user_msg1
---
ctx_user_msg2
---
ctx_user_msg3
---
```

工作流程:
Start -> PromptBase:context_user_messages -> 组合成一条message -> PromptBase:add_user_message -> END

References:
- ai_base/prompt_base.py
- utils/env_tool.py

Tips: 未来可能还会有 `context_xxx_messages`, 如 context_assistant_messages

### 读取skill的文档时，可以自动将内容加入到上下文消息中

在 `tools.skill_tool` 中的 `read_skill_file` 方法，判断读取的文件是 文档（.md），且正确读取到了文件内容，就作为新消息append到当前session中。

增加message到session的方法是 `TopsailAI/src/topsailai/context/ctx_manager.py:add_session_message`

### 用环境变量 TOPSAILAI_CONTEXT_USER_MESSAGE 去传递上下文信息

`TOPSAILAI_CONTEXT_USER_MESSAGE` 可能是文件，也可能是文本，它会作为 ctx_user_msg1

---
