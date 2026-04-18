# Task Tracking

This (Task Tracking) method is only effective when `workspace` and `task_name` are explicitly defined.
Task information includes but is not limited to the following dimensions: start_time, end_time, content.

- Task information will be recorded in the `{workspace}/tasks` folder. Each task will be recorded as a separate task file. The naming format for task files is `task.sequence_number.task_name.current_time.txt`, for example: `task.1.develop_rag_server.2025-10-18T01:01:01.txt`. The content format in the task file is as follows:

```
[start_time]
Fill in time

[content]
Fill in content

[end_time]
Fill in time
```

- You should write task information to the task file in (append) mode to avoid overwriting historically written content.
  - When a task starts, you can write information such as 'content', 'start_time', etc.
  - While the task is in progress, you can extend the task information on your own and (append) it to the task file.
  - When the task ends, you can write information such as 'end_time', etc.
