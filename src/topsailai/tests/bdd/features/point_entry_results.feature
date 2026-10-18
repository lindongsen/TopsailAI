@bdd
Feature: Business callers receive original Hook Point values and exceptions
  The business caller can inspect a normal value or the exact ordinary exception
  without losing subsequent observations or swallowing host control flow.

  Scenario: Normal Module value is accessible to the business caller
    Given result Modules configured for normal execution
    When the caller invokes the named input Hook Point
    Then the original normal value is accessible in a successful envelope

  Scenario Outline: Module failure preserves the original exception and continues
    Given result Modules configured for <case> execution
    When the caller invokes the named input Hook Point
    Then the original exception is accessible and the next Module still succeeds
    Examples:
      | case   |
      | raises |
      | async  |
      | import |

  Scenario Outline: Host control flow is not converted into a result
    Given result Modules configured for <case> execution
    When the caller invokes the named input Hook Point
    Then the exact host interruption propagates instead of an envelope
    Examples:
      | case      |
      | interrupt |
      | exit      |
      | cancel    |
