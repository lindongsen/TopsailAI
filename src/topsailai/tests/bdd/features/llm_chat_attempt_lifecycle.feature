Feature: Real LLM chat attempt observations
  Named Hook Points describe completed chat attempts without changing provider work.

  Scenario Outline: Successful responses preserve the selected return mode
    Given a real <transport> provider and <behavior> observation Modules
    When chat completes in <mode> mode
    Then one successful attempt and one exact provider request are observed

    Examples:
      | transport | behavior | mode                |
      | HTTP      | normal   | raw                 |
      | SSE       | normal   | raw                 |
      | HTTP      | failing  | parsed              |
      | SSE       | failing  | response_and_parsed |

  Scenario Outline: A failed SSE attempt retries without false success
    Given a real retry provider and <behavior> observation Modules
    When chat completes in raw mode
    Then two numbered attempts have exclusive error and success terminals

    Examples:
      | behavior |
      | normal   |
      | failing  |
