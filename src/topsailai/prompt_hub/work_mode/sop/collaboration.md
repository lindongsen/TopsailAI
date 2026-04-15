# Collaboration for subagents or team or group or multiple-agents

Each member(agent/assistant) only handles a single task at a time.
When a certain stage or step or task is completed, member should output `final_answer` so that to await/transfer next task.

Example Scenarios:
    awaiting something from x;
    execute the next step by x;
    execute something by x;

## Human and Assistant

Trigger Condition: User explicitly requests "re-{action}", for example "re-analysis", "re-test", "re-review" or similar intents.

Mandatory Action:

1. Ignore Prior Context: Do not rely on, summarize, or reference previous conclusions.
2. Full Reprocessing: You must re-evaluate the entire problem space from the beginning.
3. Comprehensive Output: Ensure the new analysis is thorough, detailed, and fully implemented as if it were the first time.
