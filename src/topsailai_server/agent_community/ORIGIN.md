---
maintainer: human
programming_language: go
related_technology_stack:
  - postgresql
  - nats
keywords:
  - cloud native
  - k8s
  - ai-agent
  - chat-system
---
# AI-Agent Community Server (ACS)

这是一个无状态的分布式服务，集群中的多个节点都能在同一时间正常工作。
服务要支持优雅关闭。

Build an AI community and rely on the power of the community to solve problems.

> Case: group

1. Create group, one group is one community, group is session
2. Join agents into group as members
3. Chat with the group

每个group都有一个或多个 `manager-agent` (alias internal-agent or system-agent)，所有的事务都由`manager-agent`进行协调，manager-agent会根据需要去调用其它agent来完成任务。

> Case: one human, multiple agents

一个人类和多个agents在一个group里面。

> Case: multiple-human, multiple-agents
Human can use group_key to join into the group, chatting together with humans & agents.

## Environment

所有的环境变量以 `ACS_` 开头，如：ACS_GROUP_MANAGER_AGENT_API_BASE="http://127.0.0.1:7373"

## Database

### Table: group

Columns:
- group_id, primary key
- group_name
- group_context, plaintext
- group_key, a secret key hash string, default null is public
- creator_id, group creator

### Table: group_member

Columns:
- group_id
- member_id, the user/agent id, contains only alphanumeric characters, hyphens, and underscores
- member_name, the user/agent name, contains only alphanumeric characters, hyphens, and underscores
- member_description,
- member_status, online/offline/idle/processing
- member_type, user/worker-agent/manager-agent, 下面描述的 xxx_agent/xxx-agent 是指 worker-agent, manager-agent, 可以用后缀 `-agent` 进行判断即可。
- member_interface, agent interface
- last_read_message_id

primary_keys(group_id, member_id)

> member_type
1. user, human is member
2. manager-agent, group manager-agent, internal/system agent
3. worker-agent, normal worker-agent

### Table: group_messages

group is session, group_id is session_id

Columns:
- group_id
- message_id, primary key
- message_text
- message_attachments, such as pictures or files, JSON, list_dict, [{data, size, format}], data can be base64-string/s3-url/etc.
- sender_id, {member_id}
- sender_type, {member_type}
- processed_msg_id, related to history message_id
- mentions, JSON, list_dict, [{member_id, member_name, member_type}]
- is_deleted
- delete_at_ms

---

## member_interface (agent_interface)

JSON string:
```json
{
    "{KEYWORD}": {VALUE} // value can be ANY
}
```

Example keywords:
```yaml
adaptor: topsailai_agent
environments:
  ACS_AGENT_API_BASE: "http://172.18.0.4:7373"
  ACS_AGENT_API_KEY: “I-Love-Dawson” # any string, a secret key for the connection base on `Bearer Token`
  ACS_AGENT_API_AUTH: "bearer"

timeout_check_health: 5 # default is 5 seconds
timeout_check_status: 5 # default is 5 seconds
timeout_chat: 600 # default is 600 seconds

# 这些`cmd_xxx`一般都不用配置，直接使用默认值
cmd_check_health: "" # get agent healthy info, ret_code=0 is healthy; optional, default value is `{adaptor}_cmd_check_health`, example `topsailai_agent_cmd_check_health`
cmd_check_status: "" # get agent status info, if ret_code=0, stdout will output status (example: idle, processing); optional, default value is `{adaptor}_cmd_check_status`
cmd_chat: "" # Execute this command with env to send a message to AI-Agent; optional, default value is `{adaptor}_cmd_chat`
```
其中 `topsailai_agent` 仅仅是一种 adaptor，在实现`agent_interface`的时候，要支持通用的 cmd 方式。

### manager-agent

manager-agent 的 `ACS_AGENT_API_BASE` 如果没有配置，就使用环境变量 `ACS_GROUP_MANAGER_AGENT_API_BASE`，由此类推：ACS_AGENT_API_KEY和ACS_AGENT_API_AUTH也同理。

当环境变量配置了这些信息时，创建group后，要自动加入1个 manager-agent:
```
# required
ACS_GROUP_MANAGER_AGENT_CMD_CHAT

# optional
ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH -> 如果没有配置，就永远是healthy
ACS_GROUP_MANAGER_AGENT_CMD_CHECK_STATUS
ACS_GROUP_MANAGER_AGENT_API_BASE
ACS_GROUP_MANAGER_AGENT_API_KEY
ACS_GROUP_MANAGER_AGENT_API_AUTH

ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHAT
ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_HEALTH
ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_STATUS
```

## How to trigger agent

[NO_TRIGGER_CASES] 这些情况下不会触发：
1. 消息的 sender_type 是 xxx-agent；
2. 消息的 processed_msg_id 有值；
3. 获取 消息 之前的10条消息和之后的10条消息，当这20条中存在连续超过10条（滑动窗口）都是 member_type=xxx-agent 的属性

Note: 支持一个api接口去主动触发特定的消息，此时 `NO_TRIGGER_CASES` 就会被忽略。

目标是决定出 pending_message 需要去消费的agents。

### trigger via mentions

消息中带有 @member_id / @member_name 识别出所有的 mentions，将member信息记录到消息记录的 mentions字段。

1. mentions 只有一个member时，且 member_type 是 xxx-agent，调用对应的 member_interface 执行 cmd_chat, ACS_AGENT_MODE=agent;
2. mentions 有多个member时，且 存在多个 xxx-agent 的memebers，不存在 manager-agent，可以并发调用对应的 member_interface 执行 cmd_chat, ACS_AGENT_MODE=agent, `ACS_AGENT_MESSAGE` 附加一段内容到最后一行:`! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !`;
3. mentions 有多个member时，且 存在 manager-agent, 若有多个，则随机取1个，去调用 manager-agent 对应的 member_interface 执行 cmd_chat, ACS_AGENT_MODE=agent;
4. 当消息中存在 @all 则触发 manager-agent, ACS_AGENT_MODE=agent; 这个情况 优先级 高;

### auto-trigger

1. 当group中只有1个user时，消息中没有任何 mentions，触发 manager-agent，ACS_AGENT_MODE=agent;
2. 当最后一条消息的sender_type是user，且超过10分钟（该时间可通过环境变量去设定），触发 manager-agent, ACS_AGENT_MODE=agent; 这种情况需要一个周期性的定时任务来筛选。使用 nats KV (Key-Value) Store 去实现分布式锁，拿到锁后，才会去做这个筛选和判断逻辑。

### trigger agent with environment variables

> 基础信息
ACS_AGENT_API_BASE
ACS_AGENT_API_KEY
ACS_AGENT_API_AUTH
ACS_AGENT_ID   -> member_id
ACS_AGENT_NAME -> member_name
ACS_AGENT_TYPE -> member_type

> 事务信息
ACS_AGENT_MODE    -> chat/agent, chat是仅聊天、直接对话、不使用工具，agent会使用工具。默认是agent。
ACS_AGENT_MESSAGE -> context_messages
ACS_AGENT_TIMEOUT -> agent_interface.timeout_chat
ACS_AGENT_PROMPT
ACS_GROUP_ID
ACS_GROUP_NAME
ACS_GROUP_CONTEXT
ACS_GROUP_CREATOR_ID
ACS_SENDER_ID
ACS_SENDER_NAME
ACS_MESSAGE_ID
ACS_MESSAGE_MENTIONS
ACS_MESSAGE_TRIGGER_TYPE

Note:
- ACS_GROUP_CONTEXT 就是 group_context 信息，仅当 last_read_message_id 为空时才会传递这个环境变量。
- ACS_AGENT_PROMPT 来自服务的环境变量 ACS_AGENT_PROMPT。

## 分布式锁

使用 nats KV (Key-Value) Store 去实现分布式锁

- Key 格式：`acs:lock:{lock_type}:{resource_id}`
- TTL：7200 秒（必须大于任务执行时间）
- 获取策略：`kv.Create()` → 成功则持有，失败则跳过
- Fencing Token：使用 UUID，任务执行前校验一致性
- 续约机制：每 10 秒 `kv.Update()`，完成后主动删除

## AgentWorkPool

通过 nats(Neural Autonomic Transport System) 的`Queueing Group`去将`触发agent以消费待处理的消息`的动作发给分布式服务集群中的一个节点去处理。
多个相同的服务实例（ACS）启动时，订阅同一个主题（如 acs.group.pending-message），并加入同一个队列组（如 pending-message-workers）。
客户端发起请求，只需向 `acs.group.pending-message` 主题发送消息，完全不需要知道这 3 个服务实例的具体 IP 和端口。
NATS 服务器接收到请求后，自动从队列组中挑选一个当前可用的实例进行处理。

使用 NATS JetStream `MsgID:AgentID` 去重，避免重复消费，header中设置`{message_id}:{agent_id}`。

The in-memory AgentWorkPool will lose pending messages on restart; consider persisting pending work or using NATS JetStream as a durable queue.

### Main Logical

1. 判断消息是否需要触发agent，如果需要，则该消息设定为 pending_message;
2. 将 pending_message 发给nats对应的主题；
3. 某个服务节点开始处理 pending_message，放入 AgentWorkPool 去处理。

### 需要被agent处理的消息（pending_message）会放入 AgentWorkPool 中，按先到先消费的原则处理

- 考虑`Edge Cases`, 例如：当发现agent(member)不存在，则拒绝处理消息；当发现group已经删除，拒绝处理消息。
- 从 pending_message 的 mentions 中可以得到 agents，决定出来 context_messages (UNPROCESSED_MESSAGES) 会发给 这些agents 或 1个agent 去处理。
- context_messages 发给AI-Agents并处理完成后，会得到一个返回结果，这个结果会作为一条新消息添加到group中。为新消息打上必要的信息，如：sender_id(agent_id), sender_name(agent_name), processed_msg_id(来自pending_message) 等。
- 如果agent调用失败，也会得到一个系统生成的`错误结果`，这个消息使用 manager-agent 的身份进行标识（新消息的 sender 是 manager-agent），避免无限重试。

### 可以通过环境变量控制并发数，并发模型使用`信号量`

对各个服务节点的 `AgentWorkPool` 进行并发控制

- AgentWorkPoolPerNode 的并发数，默认并发数10，节点中工作池能同时处理的agent消息数。
- AgentWorkPoolPerUser 的并发数，默认并发数5，能同时处理每个人的agent消息数。
- AgentWorkPoolPerGroup 的并发数，默认并发数5，能同时处理每个group的agent消息数。

达到上限时消息在 NATS 层面延迟投递（NATS JetStream redelivery），而非内存排队；全局达到上限时触发流控告警。

Note: Before dispatching to agents, verify they are alive to avoid worker starvation.

### 如何决定发给agent的消息内容（context_messages）?

找到 对应的 group_member 记录，判断是否存在 `group_member.last_read_message_id` 值:
**如果不存在**
1. 获得init_context_message;
2. 获取最近1天的消息, 即 recent_message;
3. init_context_message + recent_message = context_messages，得到 context_messages;
**如果存在**
就根据 last_read_message_id 按下述方式得到 context_messages;

Note: agent处理完成后，要更新 pending_message 的消息ID 到 `group_member.last_read_message_id`;
processed_msg_id 也是 group_messages 的一个字段，agent处理后的结果，作为新消息去记录的时候，要设置该字段值。

获取 pending_message 之前的消息，从 msg_id=last_read_message_id 的消息(包括) 到 pending_message（包括） 之间的消息，这段消息内容就作为 context_messages (unprocessedMessages) 。

> case1: 这是一个没有 last_read_message_id 记录的消息列表，例如：刚创建的group,消息刚产生等情况
```
# 按时间从最老到最新
msg1
msg2
msg3
msg4 -> 这里检测到需要触发 agent
```
按照上述的 `如果不存在` 的处理方式来得到 context_messages 。

> case2: 存在 last_read_message_id
```
msg1
msg2
msg3 -> 存在 processed_msg_id = last_read_message_id, 如： processed_msg_id 可能是 msg1 的id
msg4
msg5
msg6
msg7 -> 这里检测到需要触发 agent
msg8
msg9
```
此时的 unprocessedMessages（context_messages） 是范围 (last_read_message_id 到 msg7) ，假设 last_read_message_id 就是 msg1_id，那么范围即 (msg1 到 msg7)，包括 last_read_message_id 本身。

## Init Context Message Format

init_context_message 是 group_info:
```md
## group
id={group_id}
name={group_name}

> GROUP CONTEXT START
{group_context}
> GROUP CONTEXT END

## group_member

- id: {member_id}
  name: {member_name}
  description: {member_description}
  type: {member_type}

- id: {member_id}
  name: {member_name}
  ...

{more members}

## ME (Receiver)

I AM `{member_name}`({member_id})

```
其中的 `ME` 是指即将发送消息给目标agent的agent身份信息。

## Send Message Format

```
---
> sender: id={id}, name={name}
> message:
{message}
---
```

## member_status of group_member

### 主动更新机制

1. 当 agent 被调用时，直接设置为 `processing`；调用结束时，直接设置为 `idle`。

---

## NATS Message Bus

Environment Variables:
```shell
ACS_NATS_SERVERS=nats://localhost:4222
ACS_NATS_STREAM_GROUP=acs_group
ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX=acs.group.pending-message # e.g. `{ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX}.{group_id}`
ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX=acs.group.message # e.g. `{ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX}.{group_id}`
```
可以通过环境变量来定义关键的变量信息。

- pending-message 的消息结构与api的查询消息接口的返回内容格式一致，额外增加：`trigger`, JSON FORMAT, example: {type(mention/auto), agent_id(由该agent执行)}
- message 的消息结构与api的查询消息接口的返回内容格式一致

### Publish/Subscribe: `{ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX}.{group_id}`

- 将group相关的信息变化封装成`PublishMessage`Publish出去，包括group的基本信息、消息信息等，`PublishMessage`的格式与API的返回格式一致。

`PublishMessage` 的内容格式：
```
{ type: "", action: "", groupId: "", data: {} }
```

这些情况会 Publish:
1. type message, 增、删、改, 包括：新增消息，修改消息，删除消息（仅清空消息内容，但记录还在，即”撤回消息“）
2. type group, 增、删、改, 包括：新增group，修改group，删除group
3. type group_member, 增、删，包括：新成员加入group，成员离开group

增删改的`action`对应：create/delete/modify
数据内容`data`遵循 "GET api" 的response格式
无论是增删改，`data`所构造的格式都是 "GET api"的response格式。

## NATS Service Discovery by Micro-Framework (Service-Leader)

服务启动后，会注册服务信息到NATS。
服务可以拉取所有的注册信息，在注册信息中，服务可以通过id去判断某个记录是否为自己。
id值最小的一个服务可以作为 `Service-Leader`。

---

## API

- default_http_port: 7370

---
