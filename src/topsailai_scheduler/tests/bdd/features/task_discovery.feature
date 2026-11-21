Feature: Task discovery and validity
  As an operator running the scheduler
  I want every task file to be discovered, identified and validated
  So that a broken or disabled task is visible instead of silently skipped

  A task is a pair of files: a YAML configuration and a Markdown content file.
  Discovery walks the tasks folder, so nesting depth is unlimited and adding or
  removing a task needs no restart. A file that cannot be loaded is reported as
  invalid rather than dropped, because a task that vanishes without a message is
  worse than one that fails loudly.


  Scenario: A nested task keeps its relative identity
    Given a task nested two folders deep
    When I launch that task and wait for it
    Then the provider received the relative task id
    And the provider received the task's own folder

  Scenario: A task whose content file is missing is reported invalid
    Given a task whose Markdown file is missing
    When the scheduler rescans the task tree
    Then that task is reported as invalid
    And that task is never launched

  Scenario: A task whose content file is empty is rejected
    Given a task whose Markdown content is empty
    When the scheduler rescans the task tree
    Then that task is reported as invalid
    And the reason names the character count
    And that task is never launched

  Scenario: A task whose content is too short is rejected
    Given a task whose Markdown content is too short
    When the scheduler rescans the task tree
    Then that task is reported as invalid
    And the reason names the character count
    And that task is never launched

  Scenario: A disabled task is reported disabled and refused
    Given a disabled task
    When I launch that task
    Then the launch is refused as disabled
    And that task is reported as disabled
    And that task is never launched

  Scenario: A task whose YAML names an unknown key is rejected
    Given a task whose YAML names an unknown key
    When the scheduler rescans the task tree
    Then that task is reported as invalid
    And that task is never launched

  Scenario: A task whose YAML names no schedule is rejected
    Given a task whose YAML names no schedule
    When the scheduler rescans the task tree
    Then that task is reported as invalid

  Scenario: A task added after startup is discovered without a restart
    Given a task written after the scheduler started
    Then that task is discovered without a restart

  Scenario: A task removed after startup disappears without a restart
    Given a task written after the scheduler started
    When I remove that task
    Then that task is no longer reported
