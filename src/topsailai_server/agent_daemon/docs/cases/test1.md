# Construct actual testing scenarios to ensure successful functional testing

Steps:
1. Startup agent_daemon server;
2. Call ReceiveMessage to give a message;
3. Call RetrieveMessages to check response;
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
