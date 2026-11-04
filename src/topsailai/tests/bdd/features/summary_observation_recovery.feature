Feature: Recover work space without repeatedly summarizing startup material
  The user needs a long task to progress while large startup observations remain available through a summary.

  Scenario Outline: Replace oversized startup context only when recovery is needed
    Given a recovery runtime using a private HTTP provider for <layer> in <mode> mode with stream <stream>
    When the oversized startup context is summarized once
    Then the provider received the original material in exactly one request
    And both context layers retain the task without the oversized observation
    And subsequent file reading does not immediately trigger another summary

    Examples:
      | layer      | mode    | stream |
      | user2agent | runtime | 0      |
      | agent2llm  | runtime | 0      |
      | user2agent | message | 0      |
      | agent2llm  | message | 0      |
      | user2agent | runtime | 1      |
      | agent2llm  | runtime | 1      |
      | user2agent | message | 1      |
      | agent2llm  | message | 1      |
