# About of topsailai_agent_client

所有关于时间的显示，都只需要保留到“秒"

要将所有支持的操作（Client operations）都测试一遍，确保集成测试通过，确保所有功能正常可用

按照 api-routes 将各种 client operations 放到 `{workspace}/client/` 文件夹中，for example:
```
{workspace}/client/
- message.py    # 保存message相关的操作方法
- message_do.py # 保存do_xxx 相关的函数
- session.py    # 保存session相关的操作方法
- session_do.py
```
注意：client文件夹中的这些模块不需要解释器（shebang）如:`#!/usr/bin/env python3`

## session

### list-sessions

1. 当 session_id == session_name, 只需显示一个

Example
```
Retrieved Sessions: {TOTAL_COUNT}

=============================================================================
[2026-04-13 23:27:53] test-session-123: test-session-123    ->  这里的 test-session-123 重复了，当相同时，只需要显示一个即可。
Task content

>>> Processed: 126d3ebbdc452e7

```

## message

### list-messages

1. 时间只需保留到“秒”
2. 如果有 task_id, task_result 也要一并和消息一起显示出来
3. 使用 list-messages 作为操作名字
4. 显示完整的消息内容，不要省略

Example:
```
Retrieved Messages: {TOTAL_COUNT}, Session: {SESSION_ID}

=============================================================================
[2026-04-14 09:32:51] [{MSG_ID}] [{ROLE}]
hello

>>> task_id: aaa
>>> task_result:
content

```

## task

### list-tasks

1. 要显示对应的 session_id, message，显示完整的message，不可省略
2. 使用 list-tasks 作为操作名字

Example:
```
Retrieved Tasks: {TOTAL_COUNT}

=============================================================================
[2026-04-14 13:31:36] task=[{TASK_ID}] session=[{SESSION_ID}] msg=[{MSG_ID}]
Task: task content
---
task result

```
