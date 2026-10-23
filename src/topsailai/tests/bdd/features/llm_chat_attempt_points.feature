Feature: Standalone LLM chat attempt metadata observation
  These scenarios verify the Hook-first contract only, not LLMModel integration.
  Real HTTP and SSE lifecycle acceptance is deferred until Unit 2 installs core calls.

  Scenario Outline: Named attempt points deliver exact metadata to real Modules
    Given a standalone <phase> attempt point with a <behavior> Module
    When the named attempt point receives valid metadata
    Then the standalone observation has <status> status and exact metadata

    Examples:
      | phase  | behavior | status                |
      | before | normal   | success               |
      | after  | normal   | success               |
      | error  | normal   | success               |
      | before | failing  | completed_with_errors |
      | after  | failing  | completed_with_errors |
      | error  | failing  | completed_with_errors |

  Scenario: Unapproved content never reaches a Module
    Given a standalone before attempt point with a normal Module
    When the named attempt point receives message content
    Then no standalone Module is invoked
