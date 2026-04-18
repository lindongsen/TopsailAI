# Task Control

This (Task Control) method is only effective when `workspace` and `task_name` are explicitly defined.

- Check if the file `{workspace}/tasks/{task_name}.DONE` exists?
  - If it exists, read the file content as the final answer.
  - If it does not exist, complete the task objective and write the final result to this file.
