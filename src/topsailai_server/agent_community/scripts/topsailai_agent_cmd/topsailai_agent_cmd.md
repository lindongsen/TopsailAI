---
maintainer: human
workspace: /TopsailAI/src/topsailai_server/agent_community/scripts/
programming_language: python
references:
  - topsailai_agent_cmd_check_health.py
  - topsailai_agent_cmd_check_status.py
  - topsailai_agent_cmd_chat.py

  - local_topsailai_agent_cmd_check_health.sh
  - local_topsailai_agent_cmd_check_status.sh
  - local_topsailai_agent_cmd_chat.sh
---

# Implement topsailai_agent_cmd scripts

## topsailai_CLI

你无需读取和 `topsailai_CLI` 相关的所有命令的代码,这些CLI的用法已经描述得足够清晰了。

### Local Agent

- topsailai_llm_chat, 直接和LLM进行交流，可以通过环境变量传递 system_prompt(SYSTEM_PROMPT)、session_id(SESSION_ID)、message(TOPSAILAI_USER_MESSAGE)。对于一些需要直接给出回答的场景可以直接使用，如：内容汇总，内容优化，发表看法 等。
Example:
```md
# --- cmd ---
~# SESSION_ID="" SYSTEM_PROMPT="user say hi, you say hello" TOPSAILAI_USER_MESSAGE="hi" topsailai_llm_chat
# --- stdout ---
hello
```

- topsailai_session_status, 获得session的状态
Example:
```
~# TOPSAILAI_SESSION_ID=test topsailai_session_status
idle
```

- topsailai_agent_chat, 执行agent，并返回结果, 可以通过环境变量传递 system_prompt(SYSTEM_PROMPT)、session_id(SESSION_ID)、message(TOPSAILAI_USER_MESSAGE)
Example:
```
~# TOPSAILAI_USER_MESSAGE=hello SYSTEM_PROMPT="user say hello, you just output 'hello world'" SESSION_ID=test TOPSAILAI_INTERACTIVE_MODE=0 topsailai_agent_chat
hello world
```
这个参数`TOPSAILAI_INTERACTIVE_MODE=0`必须设置为0

### Remote Agent

- topsailai_send_message, 发送消息给agent执行，并等待执行结果，通过环境变量传递参数：
```md
| Environment Variable | Corresponding Flag | Default |
|---------------------|-------------------|---------|
| `TOPSAILAI_AGENT_DAEMON_API_BASE` | `--api-base` | `http://localhost:7373` |
| `TOPSAILAI_AGENT_DAEMON_API_KEY` | `--api-key` | (none) |
| `TOPSAILAI_AGENT_DAEMON_AUTH_STYLE` | `--auth-style` | `x-api-key` |
| `TOPSAILAI_SESSION_ID` | `--session-id` | (none) |
| `TOPSAILAI_MESSAGE` | `--message` | (none) |
| `TOPSAILAI_MESSAGE_ROLE` | `--role` | `user` |
| `WAIT_INTERVAL` | `--wait-interval` | `2` |
| `MAX_WAIT_TIME` | `--max-wait-time` | `600` |
| `DEBUG` |  | 1 |
```

Example:
```md
export DEBUG=0
export TOPSAILAI_AGENT_DAEMON_API_BASE="http://172.18.0.8:7373"
export TOPSAILAI_AGENT_DAEMON_API_KEY=""

# 获得健康信息
# --- cmd ---
~# TOPSAILAI_MESSAGE="/health" topsailai_send_message
# --- stdout ---
{"code":0,"data":{"status":"healthy","database":"healthy","timestamp":"2026-05-26T03:16:17.395269"},"message":"OK"}

# 获得会话状态
# --- cmd ---
~# TOPSAILAI_MESSAGE="/status" TOPSAILAI_SESSION_ID="file-ro" topsailai_send_message
# --- stdout ---
idle

# 发送消息
# --- cmd ---
~# TOPSAILAI_MESSAGE="hello" TOPSAILAI_SESSION_ID="file-ro" topsailai_send_message
# --- stdout ---
hi
```

## 关键参数的构成

### 已知调用 `references` 的cmd时，会带入这些环境变量

> 基础信息
ACS_AGENT_API_BASE
ACS_AGENT_API_KEY
ACS_AGENT_API_AUTH
ACS_AGENT_ID
ACS_AGENT_NAME
ACS_AGENT_TYPE

> 事务信息
ACS_AGENT_MODE
ACS_AGENT_MESSAGE -> context_messages
ACS_AGENT_TIMEOUT
ACS_AGENT_PROMPT
ACS_GROUP_ID
ACS_GROUP_NAME
ACS_GROUP_CONTEXT
ACS_SENDER_ID
ACS_SENDER_NAME
ACS_MESSAGE_ID
ACS_MESSAGE_MENTIONS
ACS_MESSAGE_TRIGGER_TYPE

### 参数构成

- SESSION_ID = ACS_GROUP_ID
- SYSTEM_PROMPT = ACS_AGENT_PROMPT
- TOPSAILAI_MESSAGE = ACS_AGENT_MESSAGE

---

## Implement `topsailai_agent_cmd_chat.py`

Use `topsailai_llm_chat` or `topsailai_send_message`

- 当 ACS_GROUP_CONTEXT 存在时，先尝试调用 `topsailai_agent_cmd_check_status.py`，exit_code!=0 且 存在 "Session not found" 在 stdout，就发送消息：
`TOPSAILAI_MESSAGE_ROLE=assistant TOPSAILAI_MESSAGE="${ACS_GROUP_CONTEXT}" TOPSAILAI_SESSION_ID=${SESSION_ID} topsailai_send_message`
使用 assistant role 将 ACS_GROUP_CONTEXT 作为消息 发送到agent；之后再去发送真正的消息内容。

- 当 ACS_AGENT_MODE=chat 且 ACS_AGENT_TYPE="manager-agent" 就调用 topsailai_llm_chat 得到结果, 否则使用 topsailai_send_message 去发送消息。

- 当 ACS_AGENT_MODE=chat 且 ACS_AGENT_TYPE!="manager-agent", 给`TOPSAILAI_MESSAGE`附加上一行消息: `! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !`

## Implement `topsailai_agent_cmd_check_health.py`

Use `topsailai_send_message`

## Implement `topsailai_agent_cmd_check_status.py`

Use `topsailai_send_message`

---

## Implement `local_topsailai_agent_cmd_check_health.sh`

始终返回 healthy, exit_code=0

## Implement `local_topsailai_agent_cmd_check_status.sh`

Use `topsailai_session_status`

## Implement `local_topsailai_agent_cmd_chat.sh`

Use `topsailai_agent_chat` or `topsailai_llm_chat`

- 当 ACS_AGENT_MODE=chat 且 ACS_AGENT_TYPE="manager-agent" 就调用 topsailai_llm_chat 得到结果，否则使用 topsailai_agent_chat

- 当 ACS_AGENT_MODE=chat 且 ACS_AGENT_TYPE!="manager-agent", 给`TOPSAILAI_USER_MESSAGE`附加上一行消息: `! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !`

---
