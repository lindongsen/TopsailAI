# About of topsailai_agent_client

所有关于时间的显示，都只需要保留到“秒"

要将所有支持的操作（Client operations）都测试一遍，确保集成测试通过，确保所有功能正常可用

## session

### list-sessions

1. 当 session_id == session_name, 只需显示一个
```
  [2026-04-13 23:27:53] test-session-123: test-session-123
    Task: None, Processed: 126d3ebbdc452e7

这里的 test-session-123 重复了，当相同时，只需要显示一个即可。
```

## message

### list-messages

1. 时间只需保留到“秒”
2. 如果有 task_id, task_result 也要一并和消息一起显示出来
3. 使用 list-messages 作为操作名字
4. 显示完整的消息内容，不要省略
5. 第一行显示出 session_id, 第一行格式："Retrieved {TOTAL_COUNT} message(s), Session: {SESSION_ID}".
```
root@ai-dev:~/ai/TopsailAI/src/topsailai_server/agent_daemon# ./topsailai_agent_client.py list-messages
Retrieved 48 message(s), Session: ai-dev
...
内容中不需要显示 session_id
```

## task

### list-tasks

1. 要显示对应的 session_id, message，显示完整的message，不可省略
2. 使用 list-tasks 作为操作名字
