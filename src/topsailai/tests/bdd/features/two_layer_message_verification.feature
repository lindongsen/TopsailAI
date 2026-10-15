Feature: Interactive CLIs expose consistent two-layer messages
  As an operator I inspect persisted User2Agent history and runtime Agent2LLM
  messages independently without introducing new business turns.

  Scenario: Agent chats retains three multi-line direct exchanges
    Given an isolated "agent_chats" CLI with scripted direct replies
    Then the CLI advertises "multiline" input
    When I complete three direct exchanges
    Then both message layers contain the ordered direct exchanges
    And only three HTTP completions were requested

  Scenario: Plan tasks accepts single-line input without a stray EOF task
    Given an isolated "plan_tasks" CLI with scripted direct replies
    Then the CLI advertises "single" input
    When I complete three direct exchanges
    Then both message layers contain the ordered direct exchanges
    And only three HTTP completions were requested

  Scenario: Plan tasks persists four messages for each real delegation
    Given an isolated "plan_tasks" CLI with scripted delegation replies
    Then the CLI advertises "single" input
    When I complete two delegated exchanges
    Then both layers preserve ordered delegation results with four-message growth
    And only six HTTP completions were requested
