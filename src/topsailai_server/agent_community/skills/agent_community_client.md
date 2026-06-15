---
workspace: /TopsailAI/src/topsailai_server/agent_community/skills
programming_language: python
---
# Agent Community Client

根据API文档实现对 group 全生命周期管理的skill

## call_agent

有一个专门用于调用agent的脚本，参数 `-m, --message` 用于传递 message_text。

环境变量有：
ACS_AGENT_ID   -> member_id
ACS_AGENT_NAME -> member_name
ACS_AGENT_TYPE -> member_type
ACS_AGENT_TIMEOUT
ACS_GROUP_ID
ACS_MESSAGE_ID

工作逻辑是：

1. 发送一条消息到group, 得到 new_msg_id1， 消息体要求:
  mentions 只能1个，即 message_text 中只能 `@` 一个 agent, example: `@agent-1 hello`;
  sender_id=ACS_AGENT_ID;
  sender_type=ACS_AGENT_TYPE;
  group_id=ACS_GROUP_ID;
  processed_msg_id=ACS_MESSAGE_ID;

2. 调用api主动去触发 new_msg_id1。
3. 等待 group中存在 processed_message_id=new_msg_id1 的消息记录 new_msg_id2, 超时时间是 ACS_AGENT_TIMEOUT
4. 如果 超时，则任务失败，脚本退出；否则返回 new_msg_id2 的消息内容。
