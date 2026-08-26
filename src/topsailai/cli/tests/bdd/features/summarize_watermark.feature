@bdd @noninteractive
Feature: Summarize context watermark enforcement
  As a user running a long TopsailAI session
  I want context pressure classified against model-aware watermarks
  So that summarization happens before the model context is exceeded

  Background:
    Given a deterministic summarize watermark harness

  Scenario Outline: Token pressure is classified at inclusive boundaries
    Given the current context contains <tokens> tokens
    When the context watermark is classified
    Then the watermark level is <level>
    And the summary-safe limit is 800 tokens
    And the send limit is 900 tokens

    Examples:
      | tokens | level  |
      | 583    | NORMAL |
      | 584    | LOW    |
      | 743    | LOW    |
      | 744    | HIGH   |
      | 899    | HIGH   |
      | 900    | HARD   |
      | 901    | HARD   |

  Scenario Outline: Invalid watermark ratios use documented defaults
    Given LOW and HIGH watermark ratios of <low> and <high>
    And the current context contains 584 tokens
    When the context watermark is classified
    Then the effective ratios are 0.73 and 0.93
    And the watermark level is LOW

    Examples:
      | low  | high |
      | 0    | 0.90 |
      | 0.50 | 1    |
      | 0.50 | 0.50 |
      | 0.80 | 0.70 |
      | null | 0.90 |
      | 0.50 | null |
      | NaN  | 0.90 |
      | 0.50 | inf  |

  Scenario Outline: Invalid safety coefficients use 1.05
    Given a token safety coefficient of <coefficient>
    And a raw context estimate of 100 tokens
    When safe tokens are estimated
    Then the safe token estimate is 105 tokens

    Examples:
      | coefficient |
      | 0.99        |
      | NaN         |
      | inf         |
      | -inf        |
      | invalid     |
      | null        |

  Scenario: A valid safety coefficient rounds upward
    Given a token safety coefficient of 1.05
    And a raw context estimate of 101 tokens
    When safe tokens are estimated
    Then the safe token estimate is 107 tokens

  Scenario Outline: Non-positive raw estimates are clamped
    Given a token safety coefficient of 2.0
    And a raw context estimate of <tokens> tokens
    When safe tokens are estimated
    Then the safe token estimate is 0 tokens

    Examples:
      | tokens |
      | 0      |
      | -1     |

  Scenario Outline: Operation margin changes the summary-safe limit
    Given a summary operation margin of <margin> tokens
    When context limits are computed
    Then the summary-safe limit is <safe_limit> tokens
    And the send limit is 900 tokens

    Examples:
      | margin | safe_limit |
      | 0      | 900        |
      | 100    | 800        |
      | 950    | -50        |
      | -1     | -7292      |

  Scenario: Missing dynamic context disables the watermark
    Given no positive model context limit is configured
    When the context watermark is classified
    Then no dynamic watermark result is produced

  Scenario: Explicit messages always use realtime token counting
    Given cached token usage is 1200 tokens
    And the runtime token counter returns 400 tokens
    When current tokens are requested for explicit messages
    Then current token usage is 400 tokens

  Scenario Outline: Session messages are dropped at the configured maximum ratio
    Given the Agent2LLM quantity threshold is 100 messages
    And the session maximum ratio is <ratio>
    And Agent2LLM has 60 messages and User2Agent has <session_count> messages
    When Agent2LLM session retention is evaluated
    Then session messages are <retention>

    Examples:
      | ratio | session_count | retention |
      | 0.5   | 49            | kept      |
      | 0.5   | 50            | dropped   |
      | 0.5   | 51            | dropped   |
      | -1    | 49            | kept      |
      | -1    | 50            | dropped   |

  Scenario: NaN session maximum ratio falls back to the default
    Given the Agent2LLM quantity threshold is 100 messages
    And the session maximum ratio is NaN
    And Agent2LLM has 60 messages and User2Agent has 10 messages
    When Agent2LLM session retention is evaluated
    Then session messages are kept

  Scenario: Cached mode uses TokenStat without counting messages
    Given realtime token calculation is disabled
    And cached token usage is 1200 tokens
    When current tokens are requested without explicit messages
    Then current token usage is 1200 tokens

  Scenario: Realtime mode counts the runtime context
    Given realtime token calculation is enabled
    And cached token usage is 1200 tokens
    And the runtime token counter returns 800 tokens
    When current tokens are requested without explicit messages
    Then current token usage is 800 tokens


  Scenario: NORMAL pre-chat does not summarize either layer
    Given the real pre-chat hook classifies NORMAL then NORMAL
    When the real summarize pre-chat hook is invoked
    Then neither layer is summarized by the pre-chat hook

  Scenario: LOW pre-chat performs ordinary summarization
    Given the real pre-chat hook classifies LOW then NORMAL
    When the real summarize pre-chat hook is invoked
    Then both layers are summarized without force by the pre-chat hook

  Scenario: HIGH pre-chat forces both layer summaries
    Given the real pre-chat hook classifies HIGH then LOW
    When the real summarize pre-chat hook is invoked
    Then both layers are summarized with force by the pre-chat hook

  Scenario: HARD pre-chat forces summarization and permits recovery
    Given the real pre-chat hook classifies HARD then HIGH
    When the real summarize pre-chat hook is invoked
    Then both layers are summarized with force by the pre-chat hook
    And the pre-chat hook does not raise a context window error

  Scenario: HARD pre-chat blocks when summarization cannot recover
    Given the real pre-chat hook classifies HARD then HARD
    When the real summarize pre-chat hook is invoked
    Then the pre-chat hook raises a context window error
