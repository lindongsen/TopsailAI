---
maintainer: human
---
# Test

Enhance unit tests.

Run all of tests via this script: `tests/run_tests.sh`

## Test Sequence

- Common Utils
  - logger/
  - utils/
  - human/        -> General methods closely related to humans, such as defining names, identity identifiers, etc.

- Agent Core
  - prompt_hub/   -> Prompt Management & External
  - skill_hub/    -> Skill Management & External
  - tools/        -> Agent can use these Tools
  - context/      -> Context Messages Management
  - ai_base/      -> LLM/Agent Enginering Framework

- Agent Workers
  - ai_team/      -> A team work mode
  - workspace/    -> Worker Entry
