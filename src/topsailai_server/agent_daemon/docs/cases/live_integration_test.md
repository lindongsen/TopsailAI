# Live Integration Test

Construct actual testing scenarios to ensure successful functional testing

Steps:
1. Startup agent_daemon server; `export HOME=/path/to/tests/integration; nohup ./topsailai_agent_daemon.py start --processor ,,, --summarizer ... > /tmp/topsailai_agent_daemon.log 2>&1 &`
2. Call ReceiveMessage to give a message; `./topsailai_agent_client.py send-message ...`
3. Call RetrieveMessages to check response; Waiting amoment for response;
4. If exists task, call RetrieveTasks to check response;
5. Go to step2 and Loop many times

## script: `TOPSAILAI_AGENT_DAEMON_PROCESSOR`

Simulate two types of results:

1. Reply directly and call ReceiveMessage
2. Generate a task and call SetTaskResult

By RetrieveMessages, it is possible to directly verify whether these two results meet expectations.

## script: `TOPSAILAI_AGENT_DAEMON_SUMMARIZER`

```shell
# Observe whether the environmental variables meet expectations
env
```

## script: `TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER`

Simulate two types of results:

1. Print "idle"
2. Print "processing"

---

NOTE: You MUST use these scripts for Integration Testing,
folder `scripts/`: test_processor.sh  test_session_state_checker.sh  test_summarizer.sh

Focus on this log file for errors: /topsailai/log/agent_daemon.log

执行这个测试脚本必须设置重定向输出日志到文件，日志内容会很长: tests/integration/test_live_integration.py
