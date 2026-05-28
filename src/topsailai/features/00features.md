# TopsailAI Agent

## Support to add messages into session

会话有两层：
1. User2Agent, User chatting to agent，user面向抽象层ai-agent,不直接面向LLM。-> 当任务正在运行时，支持在这一层增加消息，即 agent2llm 执行完毕后的下一个任务就能读到新增的消息。
2. Agent2LLM, Agent chatting to LLM，ai-agent直接面向LLM去执行明确的任务。

DONE: TopsailAI/cli/topsailai_session_add_message.py

## 读取skill的文档时，可以自动将内容加入到上下文消息中

1. 在 `tools.skill_tool` 中的 `read_skill_file` 方法，判断读取的文件是 文档（.md），就作为新消息保存到 user2agent 的session中。
2. 要判断历史消息是否存在这个记录，不要重复性加入。
