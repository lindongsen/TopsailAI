---
maintainer: human
# A markdown file's Maintainer can be `human` or `AI`, If it is human, you CANNOT modify this markdown file.

workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
ProjectRootFolder: /root/ai/TopsailAI
programming_language: python

TestsFolder: {workspace}/tests
# tests subfolders:
# - `unit/`, unit test
# - `integration/`, integration test, If you are performing integration testing, be sure to set the environment variable HOME to this folder

IssuesFolder: {workspace}/issues
# This IssuesFolder will store various issue files
# Put the processing results of the issue into the corresponding subfolders
# issues subfolders:
# - `done/`, the issues have fixed;
# - `undo/`, the issues can be ignored;

DocsFolder: {workspace}/docs
# docs files:
# - Code_Improvement_Proposal.md, AI as maintainer, Fully maintained by AI
# docs subfolders:
# - `cases/`, some test/use cases, When you are making a test plan, you must read all the files in this folder

Note:
  - The beginning of the markdown(md) file may define some information. When the maintainer is defined as human, this file will become a fact file, and you cannot modify any "fact file"
---

# Agent Daemon

agent_daemon, 一个接收用户消息并自动调度 AI-Agent 去处理消息的编排服务， CLI 名字是 topsailai_agent_daemon, 后台模式运行。

核心能力:
- 管理用户的会话消息
- 自动处理会话消息，在适当时机启动新的`TOPSAILAI_AGENT_DAEMON_PROCESSOR`进程去处理消息。`TOPSAILAI_AGENT_DAEMON_PROCESSOR` 是来自环境变量配置的脚本。

核心组件:
- Storage, 保存业务数据，保存会话消息；
- Configer，设置 环境变量；
- Http，默认监听7373端口；
- Croner，启动各种周期性检查事务，独立的定时执行模块，约定周期时间、触发条件和执行方法。

## Component: Storage

SQLAlchemy-based storage class

### Schema of Database

#### session, code folder `storage/session_manager/`

table_name: session
columns:
    - session_id, text, primary key;
    - session_name, text;
    - task, text, the task info, default null;
    - create_time, creation time of this record; default is local time;
    - update_time, When a field in a record is updated, the value will be updated accordingly
    - processed_msg_id, text, recently processed messages, relation to `message.msg_id`, need index

#### message, code folder `storage/message_manager/`

table_name: message
columns:
    - msg_id, text;
    - session_id, text, Identifier for the session.
    - role, text, user/assistant; need index;
    - message, text, the message content;
    - create_time, the creation time of this record;
    - update_time, When a field in a record is updated, the value will be updated accordingly
    - task_id, text, A task has been generated at this message point, default null; need index
    - task_result, text, the task result, default null;
primary_keys: (msg_id, session_id)

#### Key Infomations

- 能够设置最近处理过的消息点（processed_msg_id），就可以按时间（create_time）从未处理的消息开始，把未处理过的消息抓取出来作为一条消息，启动环境变量所配置的脚本`TOPSAILAI_AGENT_DAEMON_PROCESSOR`形成新进程去处理这条消息。
Example:
```
假设一个session有消息列表按create_time排序（越后面越晚）如下：
msg1
msg2
msg3  -> processed_msg_id
msg4
msg5

msg3 是最近处理过的消息点，那么就会自动将 msg3 之后的消息（msg4, msg5）合成一条消息作为“待处理消息”并处理这条消息，注意："待处理消息"不包括 processed_msg_id 即 msg3，也不包括role是`assistant`的消息.
当`TOPSAILAI_AGENT_DAEMON_PROCESSOR`执行完毕后，它会主动调用API'告知'结果，processed_msg_id 就会变成 msg5。
在消息处理完毕后，有两种可能结果：
1. 直接产生一条新消息msg6，这种情况是因为消息可以直接做出回答，所以无需生成任务去处理。
2. msg5 在message表中对应的记录会产生 task_id，会产生task_result。

值得注意：如果 msg3 还没处理完成，那么后续的消息不会被处理。
如果某个消息中存在 task_id 和 task_result,要把它们也作为“待处理消息”的一部分，不可省略。
```

”待处理消息“的内容格式是markdown：以"---"分隔，以”---“开头和结束。
例如：
```
---
msg4内容
---
msg5内容
>>> task_id: msg5的task_id
>>> task_result: msg5的task_result
---
```
其中 task_id, task_result 仅存在值时才会加入到”待处理消息“当中

## Component: Configer

These environment variables MUST exist, otherwise the service will fail to start:

- `TOPSAILAI_AGENT_DAEMON_PROCESSOR`, 一个脚本文件，用来处理消息。当它处理完毕后，会主动将结果记录到 `storage` 中。
  运行该脚本需要设置以下“运行时”的环境变量：
  - TOPSAILAI_MSG_ID, 对应message表中的msg_id，最新的、未处理的msg_id。
  - TOPSAILAI_TASK, 消息内容
  - TOPSAILAI_SESSION_ID

- `TOPSAILAI_AGENT_DAEMON_SUMMARIZER`, 一个脚本文件，用来汇总消息。本服务无需关心汇总结果，这个结果和`TOPSAILAI_AGENT_DAEMON_PROCESSOR`的处理逻辑紧密相关。
  运行该脚本需要设置以下“运行时”的环境变量：
  - TOPSAILAI_SESSION_ID
  - TOPSAILAI_TASK, 消息内容

- `TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER`, 一个脚本文件，可以得到session的状态，idle/processing，没有消息在处理中就是idle。
  运行该脚本需要设置以下“运行时”的环境变量：
  - TOPSAILAI_SESSION_ID

这里提到的 processor, summarizer 等都属于 worker 性质。
这种 worker 和 agent_daemon 完全分离、各自独立的设计，使得 agent_daemon 具备通用性和灵活性。

## Component: API

restful api

统一的response格式：

- code, int, 0 is ok
- data, list|dict|str|any, response content
- message: str, some info for error or warning

### session, uri_path:api/v1/session

#### ListSessions

parameters:
- session_ids, list[str], optional
- start_time: if null, no limit it
- end_time: if null, no limit it
- offset: int, default 0
- limit: int, default 1000
- sort_key: str, default is create_time
- order_by: str, desc or asc, default is desc

response:
- data: list[dict]

#### DeleteSessions

delete session and messages

parameters:
- session_ids, list[str]

#### ProcessSession

判断 session 表中的 processed_msg_id 是否为最新的消息，如果不是，进入到执行 `TOPSAILAI_AGENT_DAEMON_PROCESSOR` 的流程。

parameters:
- session_id: str, required

response:
- message: 说明是否有 "待处理消息"
- data: dict
```
{
  "processed_msg_id": 当前 session 表中的 processed_msg_id

  # 当存在 "待处理消息" 需要被处理时, 有以下内容
  "processing_msg_id": "待处理消息"中创建时间最新的 msg_id
  "messages": list[dict], 该行为所发起的"待处理消息"的内容
  "processor_pid": 调用processor的进程id
}
```

### message, uri_path:api/v1/message

#### ReceiveMessage

parameters:
- message: str, required, message content
- session_id: str, required
- role: str, user/assistant, default is user
- processed_msg_id: str, 对应上述提到的 TOPSAILAI_MSG_ID, 当 processor 处理完毕，它有一种结果，直接生成答案，无需生成task。此时，该session的processed_msg_id就会变成该值。

记录完毕后，判断 session表中的processed_msg_id是否为最新的消息，如果不是，进入到执行 `TOPSAILAI_AGENT_DAEMON_PROCESSOR` 的流程。

#### RetrieveMessages

parameters:
- session_id: str, required
- start_time: if null, no limit it
- end_time: if null, no limit it
- offset: int, default 0
- limit: int, default 1000
- sort_key: str, default is create_time
- order_by: str, desc or asc, default is desc

response:
- data: list[dict]

### task, uri_path:api/v1/task

#### SetTaskResult

parameters:
- session_id: str, required
- processed_msg_id: str, required, 对应上述提到的 TOPSAILAI_MSG_ID
- task_id: str, required
- task_result: str,

当 processor 处理完毕，它有一种结果，生成一个任务，当任务完成时，调用此API以记录任务信息。
记录完毕后，判断 session表中的processed_msg_id是否为最新的消息，如果不是，进入到执行 `TOPSAILAI_AGENT_DAEMON_PROCESSOR` 的流程。

#### RetrieveTasks

parameters:
- task_ids: list
- session_id: str, required
- start_time: if null, no limit it
- end_time: if null, no limit it
- offset: int, default 0
- limit: int, default 1000
- sort_key: str, default is create_time
- order_by: str, desc or asc, default is desc

response:
- data: list[dict]

## Component: Croner

触发器的设计可参考该信息：`ai-tools help croner`

### 消费消息
定期每分钟查出最近10分钟的message表记录，得到一个没有重复的session_id列表，判断session表中的processed_msg_id是否为最新的消息，如果不是，进入到执行 `TOPSAILAI_AGENT_DAEMON_PROCESSOR`的流程。

### 汇总消息
定期每日1点，查出最近1天的message表记录，汇总相关session。注意：消息要按照create_time顺序输出。
汇总的脚本使用环境变量: `TOPSAILAI_AGENT_DAEMON_SUMMARIZER`

### 清理会话
定期每月1日1点，清理1年之前的session记录（按 update_time 查询），包括session相关的messages。

## 流程:`TOPSAILAI_AGENT_DAEMON_PROCESSOR`

1. 如果 processed_msg_id 就是 最新消息，打印日志提示信息并退出。
2. 如果 processed_msg_id 到 最新消息 之间，不包括 processed_msg_id, 包括 最新消息，全都是role=assistant，则打印日志提示信息并退出。避免无限循环。
3. 设置必要的、相关的环境变量去执行脚本`TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER`，返回idle则继续，返回processing表示该会话的消息正在处理中、就退出。对于脚本的返回结果要打印日志信息。
4. 将最新消息ID作为 TOPSAILAI_MSG_ID, 设置必要的、相关的环境变量，执行processor脚本

## About log

Using this module: `from topsailai_server.agent_daemon import logger`

默认的日志文件保存在：/topsailai/log/agent_daemon.log
测试过程要特别关注日志文件的内容，确保及时发现BUG

Example
```python
from topsailai_server.agent_daemon import logger
logger.info("hello")
```

DONOT use this writing style:
```python
logger.info(f"hello: {msg}")

try:
    ...
except Exception as e:
    logger.error(f"hello: {e}")
```

To use this writing style:
```python
logger.info("hello: %s", msg)

try:
    ...
except Exception as e:
    logger.exception("hello: %s", e)
```

## About CLI

### topsailai_agent_daemon

start/stop server

cli_file: topsailai_agent_daemon.py

supported_args: refer to `env_template`, If parameters are specified, CLI will set these parameters to the environment variables.

- `--host`, listen ip, default "0.0.0.0"
- `--port`, listen port, default "7373"
- `--db_url`, database url, default "sqlite:///topsailai_agent_daemon.db"
- `--processor`, a script file
- `--summarizer`, a script file
- `--session_state_checker`, a script file

Running in the background: `export HOME=/path/to/tests/integration; nohup ./topsailai_agent_daemon.py start --processor ,,, --summarizer ... > /tmp/topsailai_agent_daemon.log 2>&1 &`

### topsailai_agent_client

call api to server

cli_file: topsailai_agent_client.py

## Scripts

ScriptsFolder: {workspace}/scripts

- processor_callback.py
  If exists `TOPSAILAI_TASK_ID` in environ, call SetTaskResult, `TOPSAILAI_FINAL_ANSWER` is `task_result`;
  Else call ReceiveMessage, `TOPSAILAI_FINAL_ANSWER` is `message`.

## Reference Modules

这些模块可以直接复用：

- `from topsailai.utils import ...`

agent_daemon模块是: `from topsailai_server.agent_daemon.xxx import yyy`
不要出现 `from src.topsailai...`, 也不要出现 `from agent_daemon...`

## References

There are many places worth referencing in this folder: `{workspace}/docs/`

- env_template, The template is ready for developers to copy to `.env` and customize for their deployment.

---

You need to establish a clear development and testing workflow/workplan.

@km-k25 Review the content and documents and give some suggestions to mm-m25, let mm-m25 finish it
@km-k25 Reviewer
@mm-m25 Developer, Finish each module/file (one by one), and after each modification, provide km-k25 with a review

Task objective: Ensure that all of features are fully functional and usable, passing both unit testing and basic functionality testing.
