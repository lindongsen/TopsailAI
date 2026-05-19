# TopsailAI Agent

## Support to add messages into session

会话有两层：
1. User2Agent, User chatting to agent，user面向抽象层ai-agent,不直接面向LLM。-> 当任务正在运行时，支持在这一层增加消息，即 agent2llm 执行完毕后的下一个任务就能读到新增的消息。
2. Agent2LLM, Agent chatting to LLM，ai-agent直接面向LLM去执行明确的任务。

DONE: TopsailAI/cli/topsailai_session_add_message.py
